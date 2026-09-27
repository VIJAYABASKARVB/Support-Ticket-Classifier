import os
import logging

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI,HTTPException
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel,Field

from graph import run_pipeline
from production_modules.prompt_versioning import list_versions, get_active_version
from production_modules.cost_calculator import session_tracker

load_dotenv(override=True)
logging.basicConfig(
  level=logging.INFO,
  format="%(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)


# REQUEST/RESPONSE MODELS
class ClassifyRequest(BaseModel):
  ticket_text: str = Field(
    # field is required
    ...,
    # The string must contain at least 5 and max 4000 characters.
    min_length=5,
    max_length=4000,
  )
  channel: str = Field(
    default="web_form",
    pattern="^(web_form|email)$"
  )

class ClassifyResponse(BaseModel):
    issue_category: str
    assigned_team: str
    priority: str
    user_sentiment: str
    confidence_score: float
    reasoning: str
    requires_human_review: bool
    pii_detected: bool
    prompt_version: str | None
    cost_info: dict | None
    injection_blocked: bool


# STARTING BANNER
def print_banner():
    model = os.getenv("DEFAULT_MODEL", "llama-3.3-70b-versatile")
    prompt_version = get_active_version()
    pii_enabled = True   # always on in this build
    cost_tracking = os.getenv("LOG_COSTS", "true").lower() == "true"

    banner = f"""
+============================================================+
|       AI-Powered Support Ticket Classifier                 |
+------------------------------------------------------------+
|  Model          : {model:<38} |
|  Prompt Version : {prompt_version:<38} |
|  PII Redaction  : {'enabled' if pii_enabled else 'disabled':<38} |
|  Cost Tracking  : {'enabled' if cost_tracking else 'disabled':<38} |
+============================================================+
"""
    print(banner)

@asynccontextmanager
async def lifespan(app : FastAPI):
  print_banner()
  # Before yield = when server starts
  # After yield = when server stops
  yield
  summary = session_tracker.summary
  logger.info(
    "Session ended.Total cost: $%.6f over %d calls",
    summary["total_cost_usd"],
    summary["calls"],
  )

app = FastAPI(
    title="Support Ticket Classifier",
    description="LangGraph + FastAPI ticket classification pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ROUTES
@app.get("/health")
async def health():
   return{
      "status" : "ok"
   }

@app.get("/prompts")
async def get_prompts():
    return {
      "versions": list_versions(), 
      "active": get_active_version()
    }

@app.post(
  "/classify",
  response_model=ClassifyResponse
)
async def classify(request: ClassifyRequest):
  try:
    state = run_pipeline(
      request.ticket_text,
      request.channel
    )
  except Exception as exc:
     logger.exception("Pipeline error: %s",exc)
     raise HTTPException(
        status_code=500,
        detail = str(exc)
     )

  classification = state.get("classification")
  if classification is None:
    raise HTTPException(
      status_code=422, 
      detail=state.get("error", "Classification failed")
    )
   
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

