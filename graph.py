import logging
import os

from dotenv import load_dotenv
from langgraph.graph import StateGraph,START,END

from schema import TicketClassification
from production_modules.pii_redaction import redact_pii
from production_modules.prompt_injection import check_injection
from production_modules.prompt_versioning import get_active_prompt, get_active_version
from production_modules.structured_output import classify_with_json_mode
from production_modules.validate_response import validate_classification
from production_modules.cost_calculator import calculate_cost, count_tokens
from production_modules.fallback_retry import classify_with_fallback, SAFE_CLASSIFICATION


load_dotenv(override=True)
logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "openai/gpt-oss-120b")


# NODE-1 -> PII-REDACT
def pii_reddact_node(state:dict) -> dict:
  result = redact_pii(state["raw_ticket"])
  print(result)
  return{
    **state,
    "redacted_ticket": result.redacted_text,
    "pii_detected": result.pii_detected,
  }

# NODE-2 -> PROMPT INJECTION CHECK
def injection_check_node(state: dict) -> dict:
  check = check_injection(state["raw_ticket"])

  if not check.is_safe:
    logger.warning("Injection Detected: %s",check.detected_pattern)

    return{
      **state,
      "injection_blocked" : True,
      "error" : f"Injection Detected:{check.detected_pattern}",
      "classification" : SAFE_CLASSIFICATION,
      "validation_status" : "blocked"
    }

  return {
    **state,
    "injection_blocked" : False
  }


# NODE-3 -> TICKET CLASSIFICATION
def classify_node(state: dict) -> dict:
  if state.get("injection_blocked"):
      return state

  active = get_active_prompt()
  version = get_active_version()
  ticket_text = state.get("redacted_ticket") or state["raw_ticket"]

  try:
    classification = classify_with_json_mode(
      ticket_text=ticket_text,
      system_prompt=active["template"],
      model = DEFAULT_MODEL
    )

    return {
      **state,
      "classification":classification,
      "prompt_version":version,
    }

  except Exception as exc:
    logger.error("Classify_node failed: %s",exc)
    return {
      **state,
      "error": str(exc),
      "classification" : None,
      "prompt_version" : version
    }


