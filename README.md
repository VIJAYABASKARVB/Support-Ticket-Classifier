# AI-Powered Support Ticket Classifier

![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688?style=flat-square&logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2.0-1C3C3C?style=flat-square)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)

A production-grade **LangGraph + FastAPI** service that turns raw customer support tickets into structured triage decisions — category, owning team, priority, sentiment, confidence, and human-review flags — behind a pipeline of PII redaction, prompt-injection guarding, schema validation, retry/fallback, versioned prompts, and per-call cost accounting.

---

## Demo Screenshot

![Demo](demo-ui/screenshot.png)

> Run the app and take a screenshot, save as `demo-ui/screenshot.png`.

---

## Project Overview

### The problem it solves

Support teams receive thousands of free-text tickets that must be routed instantly to the right team at the right priority. Doing this manually is slow and inconsistent; calling an LLM directly is fast but unreliable — it hallucinates fields, leaks PII into third-party APIs, follows malicious instructions embedded in tickets, and gives no audit trail of which prompt produced which answer.

This project wraps the LLM in a **deterministic, observable pipeline** that:

- **Redacts PII** (emails, phone numbers, credit cards) *before* the text ever reaches the model.
- **Blocks prompt-injection attacks** with a separate guard LLM that fails safe.
- **Validates every LLM output** against a strict Pydantic schema *and* business rules.
- **Retries and falls back** to a safe default instead of crashing when the model misbehaves.
- **Versions prompts** so any classification can be traced to the exact prompt that produced it.
- **Tracks token cost** per request and per session.

### Who uses this in a real company

- **Support operations / tier-1 triage teams** auto-routing tickets from a web form or shared inbox.
- **Customer-experience engineering** embedding classification into a Zendesk / Intercom workflow.
- **Platform teams** needing a hardened LLM microservice with security (PII + injection) and FinOps (cost) guardrails before an LLM touches production traffic.

### Example

**Input ticket** (`POST /classify`):

```json
{
  "ticket_text": "I was charged twice for order #9981 and my card 4111 1111 1111 1111 shows two payments. Please refund one immediately!",
  "channel": "email"
}
```

**Output** (real field names from `schema.py` and `main.py`):

```json
{
  "issue_category": "payment_issue",
  "assigned_team": "payments_team",
  "priority": "high",
  "user_sentiment": "angry",
  "confidence_score": 0.95,
  "reasoning": "Customer reports a duplicate charge on order #9981 and demands an immediate refund.",
  "requires_human_review": false,
  "pii_detected": true,
  "prompt_version": "v2",
  "cost_info": {
    "model": "openai/gpt-oss-120b",
    "input_tokens": 312,
    "output_tokens": 96,
    "total_cost_usd": 0.000094
  },
  "injection_blocked": false
}
```

Note that `pii_detected` is `true` — the credit card was stripped from the text *before* it reached the LLM (the classification itself is unaffected).

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│  DEMO UI  —  demo-ui/index.html  (static, single-file triage console)    │
│  • 10 sample tickets   • channel select   • live /health polling         │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ fetch("http://localhost:8000/classify")
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  HTTP LAYER  —  main.py  (FastAPI + CORS)                                │
│                                                                          │
│   GET  /health    → {"status": "ok"}                                     │
│   GET  /prompts   → prompt_versioning.list_versions() / get_active_...() │
│   POST /classify  → ClassifyRequest ─▶ run_pipeline() ─▶ ClassifyResponse│
│        request validation: ticket_text 5–4000 chars,                     │
│                            channel ∈ {web_form, email}                   │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ run_pipeline(raw_ticket, channel)
                                ▼
┌══════════════════════════════════════════════════════════════════════════┐
║  LANGGRAPH PIPELINE  —  graph.py  (StateGraph, state = dict)             ║
║                                                                          ║
║   START                                                                  ║
║     │                                                                    ║
║     ▼                                                                    ║
║  ┌─────────────────────┐   production_modules/pii_redaction.py           ║
║  │  1. pii_redact      │──▶ redact_pii(raw_ticket)                       ║
║  └──────────┬──────────┘   writes → redacted_ticket, pii_detected        ║
║             ▼                                                            ║
║  ┌─────────────────────┐   production_modules/prompt_injection.py        ║
║  │  2. injection_check │──▶ check_injection(raw_ticket)   [GUARD LLM]    ║
║  └──────────┬──────────┘   if unsafe → injection_blocked=True,           ║
║             │                 classification=SAFE_CLASSIFICATION,        ║
║             │                 validation_status="blocked"                ║
║             ▼                                                            ║
║  ┌─────────────────────┐   production_modules/prompt_versioning.py       ║
║  │  3. classify        │──▶ get_active_prompt() / get_active_version()   ║
║  └──────────┬──────────┘   production_modules/structured_output.py       ║
║             │                  ▶ classify_with_json_mode(...) [LLM]      ║
║             │                 writes → classification, prompt_version    ║
║             ▼                                                            ║
║  ┌─────────────────────┐   production_modules/validate_response.py       ║
║  │  4. validate        │──▶ validate_classification(classification)      ║
║  └──────────┬──────────┘   writes → validation_status ∈ {pass, fail}      ║
║             │                                                            ║
║      ┌──────┴──────────── route_after_validate(state)  [CONDITIONAL]     ║
║      │ injection_blocked OR status == "pass"           status == "fail"   ║
║      ▼                                            ▼                      ║
║  ┌──────────────┐   production_modules/    ┌────────────────────────┐     ║
║  │ 6. cost_log  │◀── cost_calculator.py    │ 5. fallback            │     ║
║  │              │      count_tokens()      │  production_modules/   │     ║
║  │  writes →    │      calculate_cost()    │   fallback_retry.py    │     ║
║  │  cost_info   │                          │  ▶ classify_with_      │     ║
║  └──────┬───────┘                          │    fallback() [RETRY]  │     ║
║         │                                  │  writes → classification│    ║
║         │                                  └───────────┬────────────┘     ║
║         │                                              │                  ║
║         ▼                                              │                  ║
║        END ◀───────────────────────────────────────────┘                  ║
╚═══════════════════════════════╤══════════════════════════════════════════╝
                                │ ChatGroq(model=DEFAULT_MODEL, temperature=0)
                                │   • structured_output.py  (classify + guard)
                                │   • prompt_injection.py   (guard judge)
                                ▼
                   ┌────────────────────────────┐
                   │  GROQ API  (LLM backend)   │
                   │  DEFAULT_MODEL env var     │
                   │  openai/gpt-oss-120b       │
                   └────────────────────────────┘
```

**Key edges** (`graph.py:176-185`):

```python
builder.add_edge(START, "pii_redact")
builder.add_edge("pii_redact", "injection_check")
builder.add_edge("injection_check", "classify")
builder.add_edge("classify", "validate")
builder.add_conditional_edges("validate", route_after_validate, {
    "cost_log": "cost_log",   # pass or injection-blocked
    "fallback": "fallback",   # validation failed
})
builder.add_edge("fallback", "cost_log")
builder.add_edge("cost_log", END)
```

---

## LangGraph Pipeline — Node by Node

The shared **state** is a plain `dict` (initialized in `run_pipeline`, `graph.py:192-205`) with these keys: `raw_ticket`, `channel`, `redacted_ticket`, `classification`, `validation_status`, `cost_info`, `error`, `pii_detected`, `prompt_version`, `injection_blocked`. Every node returns `{**state, ...changed_keys}`.

### 1. `pii_redact_node` (`graph.py:24`)

- **What it does:** Scans the raw ticket with regexes and replaces every email, credit-card number, and phone number with a placeholder token.
- **Module used:** `production_modules/pii_redaction.py` → `redact_pii()`
- **Reads:** `raw_ticket`
- **Writes:** `redacted_ticket` (cleaned text), `pii_detected` (`True`/`False`)

### 2. `injection_check_node` (`graph.py:34`)

- **What it does:** Asks a **guard LLM** to judge whether the raw ticket is a genuine support request or a prompt-injection attack (instruction override, role reassignment, system-prompt leaking, jailbreak framing). On a hit, it short-circuits the pipeline by planting the safe default classification.
- **Module used:** `production_modules/prompt_injection.py` → `check_injection()`
- **Reads:** `raw_ticket` (the *original*, not the redacted text — the guard must see what the attacker actually wrote)
- **Writes:**
  - safe path: `injection_blocked = False`
  - blocked path: `injection_blocked = True`, `classification = SAFE_CLASSIFICATION`, `validation_status = "blocked"`, `error = "Injection Detected:<pattern>"`
- **Fail-safe:** if the guard call itself throws, `check_injection()` returns `is_safe=False, detected_pattern="guard_error"` — unvetted input never reaches the classifier.

### 3. `classify_node` (`graph.py:55`)

- **What it does:** Loads the active versioned prompt, sends the **redacted** ticket to the LLM in JSON mode with the `TicketClassification` JSON schema embedded in the system prompt, and parses the result into a Pydantic model. Skips immediately when `injection_blocked` is set.
- **Modules used:** `production_modules/prompt_versioning.py` (`get_active_prompt()`, `get_active_version()`) and `production_modules/structured_output.py` (`classify_with_json_mode()`)
- **Reads:** `injection_blocked`, `redacted_ticket` (falls back to `raw_ticket` if redaction didn't run)
- **Writes:** `classification` (a `TicketClassification` or `None` on error), `prompt_version`, and `error` if the LLM call failed

### 4. `validate_node` (`graph.py:87`)

- **What it does:** Re-validates the model's output: Pydantic schema check (enum membership, `confidence_score` ∈ [0, 1], field types) plus business rules (`confidence_score < 0.5` ⇒ `requires_human_review` must be `True`). Skips when `injection_blocked`.
- **Module used:** `production_modules/validate_response.py` → `validate_classification()`
- **Reads:** `classification`, `injection_blocked`
- **Writes:** `validation_status` (`"pass"` / `"fail"`), `error` (`None` on pass, `"; "`-joined details on fail), `classification` (replaced with the validated copy on pass)

### 5. `fallback_node` (`graph.py:108`) — *conditional, only on validation failure*

- **What it does:** Re-classifies with **tenacity** retries (3 attempts, exponential backoff 1–10 s, retrying only on `groq.RateLimitError` and `pydantic.ValidationError`). Attempt ≥ 2 swaps in the simpler `SIMPLE_SYSTEM_PROMPT`. If every attempt fails, returns `SAFE_CLASSIFICATION` instead of crashing.
- **Module used:** `production_modules/fallback_retry.py` → `classify_with_fallback()`
- **Reads:** `redacted_ticket` (or `raw_ticket`)
- **Writes:** `classification`, `validation_status` (`"pass"` if a real classification came back, otherwise `"fallback_safe"`)

### 6. `cost_log_node` (`graph.py:123`)

- **What it does:** Counts input/output tokens with `tiktoken`, prices them against a per-model rate table, records them in a process-wide session tracker, and logs the cost when `LOG_COSTS=true`.
- **Module used:** `production_modules/cost_calculator.py` → `count_tokens()`, `calculate_cost()`
- **Reads:** `redacted_ticket` (or `raw_ticket`), `classification`
- **Writes:** `cost_info` = `{model, input_tokens, output_tokens, total_cost_usd}`

### Conditional edge logic (`graph.py:157-162`)

```python
def route_after_validate(state: dict) -> str:
    if state.get("injection_blocked"):
        return "cost_log"        # blocked tickets skip retry — already have a safe answer
    if state.get("validation_status") == "pass":
        return "cost_log"        # happy path
    return "fallback"            # schema/business-rule failure → retry, then safe default
```

Both branches converge on `cost_log`, so **every request is cost-accounted**, including blocked and fallback ones.

---

## Production Modules

All modules live in `production_modules/` and every one has a `if __name__ == "__main__"` self-test block.

### `pii_redaction.py`

- **Purpose:** Strips PII from ticket text with regexes before it reaches the LLM.
- **How it works:** Compiles three regexes — `_EMAIL_RE`, `_PHONE_RE`, `_CC_RAW_RE` (13–19 digit runs for card numbers). All matches are collected as `(start, end, label)` spans, phone matches overlapping an existing span are skipped, spans are sorted right-to-left and replaced so earlier offsets stay valid. Phone candidates with > 12 digits are discarded as card false-positives. Returns a `RedactionResult` dataclass and logs every replacement at `WARNING` level (original value included for audit).
- **Signature:** `redact_pii(text: str) -> RedactionResult` where `RedactionResult(redacted_text: str, detected_entity_types: list[str], pii_detected: bool)`
- **Standalone:** **Yes** — `python production_modules/pii_redaction.py` (fully offline, no API key)

### `prompt_injection.py`

- **Purpose:** Decides whether a ticket is a prompt-injection attack before the main classifier sees it.
- **How it works:** A second, separate **guard LLM** call — `ChatGroq(model=GUARD_MODEL, temperature=0)` piped through `GUARD_PROMPT | llm.with_structured_output(InjectionJudgement)`. The judge returns `is_injection`, `confidence`, `reasoning`, `detected_pattern` via a Pydantic schema. Any exception during the call is treated as **unsafe** (`detected_pattern="guard_error"`), so a broken guard blocks traffic instead of passing it through.
- **Signature:** `check_injection(text: str) -> InjectionCheckResult` where `InjectionCheckResult(is_safe: bool, detected_pattern: Optional[str])`
- **Standalone:** **Yes** — `python production_modules/prompt_injection.py` (runs 6 built-in samples; requires `GROQ_API_KEY`)

### `prompt_versioning.py`

- **Purpose:** Keeps every prompt revision in a registry so outputs are traceable and prompts can be swapped without a deploy.
- **How it works:** Module-level `PROMPT_REGISTRY: dict[str, dict]` holds `v1` (basic) and `v2` (chain-of-thought) entries with `version_id`, `model`, `created_at`, `description`, `template`. The active version is selected by the `PROMPT_VERSION` env var (default `"v2"`); `list_versions()` projects the registry (without templates) for the `/prompts` endpoint.
- **Signatures:** `get_prompt(version: str) -> dict`, `get_latest() -> dict`, `get_active_version() -> str`, `get_active_prompt() -> dict`, `list_versions() -> list[dict]`
- **Standalone:** **Yes** — `python production_modules/prompt_versioning.py` (offline)

### `cost_calculator.py`

- **Purpose:** Prices every LLM call and accumulates session-wide spend.
- **How it works:** `count_tokens()` uses `tiktoken.encoding_for_model(model)` with a `cl100k_base` fallback for unknown models. `calculate_cost()` looks up `PRICING[model]` (USD per 1,000 tokens; defaults to `llama-3.3-70b-versatile` rates for unknown models), computes input/output/total cost, and records into a module-level `session_tracker` (`SessionCostTracker`) unless `record_to_session=False`. The FastAPI lifespan hook prints `session_tracker.summary` on shutdown.
- **Signatures:** `count_tokens(text: str, model: str = "llama-3.3-70b-versatile") -> int`, `calculate_cost(model: str, input_tokens: int, output_tokens: int, record_to_session: bool = True) -> CostInfo`
- **Standalone:** **Yes** — `python production_modules/cost_calculator.py` (offline after tiktoken's encoding download)

### `validate_response.py`

- **Purpose:** Guarantees no unvalidated or business-invalid classification ever leaves the pipeline.
- **How it works:** Accepts `TicketClassification | dict | anything`. Wrong types are rejected outright. Dicts/models go through `TicketClassification.model_validate(data)` (enum membership, types, `confidence_score` bounds), collecting every `ValidationError` entry as `"<field.path>: <message>"`. Then two **business rules** run: `confidence_score` must be in `[0.0, 1.0]`, and a score `< 0.5` with `requires_human_review=False` is a failure. Returns a `ValidationResult`; any error routes the graph to the fallback node.
- **Signature:** `validate_classification(raw: Any) -> ValidationResult` where `ValidationResult(is_valid: bool, validated_classification: Optional[TicketClassification], error_details: list[str])`
- **Standalone:** **Yes** — `python production_modules/validate_response.py` (offline; prints one valid and one invalid fixture)

### `fallback_retry.py`

- **Purpose:** Turns transient LLM failures into bounded retries and total failures into a safe answer instead of a 500.
- **How it works:** `classify_with_retry` is wrapped in `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception_type((RateLimitError, ValidationError)))`. Attempt ≥ 2 reads `classify_with_retry.statistics["attempt_number"]` and swaps `get_active_prompt()["template"]` for the shorter `SIMPLE_SYSTEM_PROMPT`. Each attempt re-validates via `validate_classification()` and raises `ValidationError` on a bad result to trigger the next attempt. `classify_with_fallback` wraps all of it and returns `SAFE_CLASSIFICATION` (`issue_category=other`, `assigned_team=customer_support`, `priority=medium`, `confidence_score=0.0`, `requires_human_review=True`) when retries are exhausted.
- **Signatures:** `classify_with_retry(ticket_text: str, model: str = _DEFAULT_MODEL) -> TicketClassification`, `classify_with_fallback(ticket_text: str, model: str = _DEFAULT_MODEL) -> TicketClassification`
- **Standalone:** **Yes** — `python production_modules/fallback_retry.py` (requires `GROQ_API_KEY`)

### `structured_output.py`

- **Purpose:** Forces the LLM to return machine-parseable, schema-conformant JSON.
- **How it works:** Two strategies. `classify_with_json_mode` (used in production) serializes `TicketClassification.model_json_schema()` into the system prompt — escaping `{`/`}` as `{{`/`}}` so LangChain doesn't treat the schema as template variables — and calls `ChatGroq(..., model_kwargs={"response_format": {"type": "json_object"}})` at `temperature=0`, then `TicketClassification.model_validate(json.loads(response.content))`. `classify_with_function_calling` uses `llm.with_structured_output(TicketClassification)` instead. Also exports `SIMPLE_SYSTEM_PROMPT` (used by the retry path) listing all seven categories and instructing low confidence + human review when unsure.
- **Signatures:** `classify_with_json_mode(ticket_text: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT, model: str = _DEFAULT_MODEL) -> TicketClassification`, `classify_with_function_calling(ticket_text: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT, model: str = _DEFAULT_MODEL) -> TicketClassification`
- **Standalone:** **Yes** — `python production_modules/structured_output.py` (runs both strategies; requires `GROQ_API_KEY`)

### `non_determinism.py`

- **Purpose:** Measures how reproducible classifications are at `temperature=0` — a determinism experiment, **not wired into the graph**.
- **How it works:** Builds deterministic (`temperature=0`) or creative (`temperature=0.7`) `ChatGroq` clients, classifies the same ticket `runs` times through `llm.with_structured_output(TicketClassification)`, and reports whether every run produced the same `issue_category`.
- **Signatures:** `build_deterministic_llm(model: str = "openai/gpt-oss-120b") -> ChatGroq`, `build_creative_llm(model: str = "openai/gpt-oss-120b", temperature: float = 0.7) -> ChatGroq`, `classify_ticket(ticket_text: str, llm: ChatGroq) -> TicketClassification`, `run_consistency_test(ticket_text: str, runs: int = 5) -> dict`
- **Standalone:** **Yes** — `python production_modules/non_determinism.py` (5 live LLM calls; requires `GROQ_API_KEY`)

---

## Tech Stack

| Technology | Version | Role |
|---|---|---|
| Python | 3.11+ | Runtime (code uses `str \| None` unions and modern typing) |
| FastAPI | >=0.111.0 | HTTP layer, request/response validation, OpenAPI docs |
| Uvicorn | >=0.29.0 | ASGI server (`uvicorn[standard]` with reload/websockets) |
| LangGraph | >=0.2.0 | `StateGraph` pipeline: nodes, edges, conditional routing |
| LangChain | >=0.2.0 | `ChatPromptTemplate`, chain composition (`prompt \| llm`) |
| langchain-groq | >=0.2.0 | `ChatGroq` LLM client (Groq API) |
| Groq (`groq`) | transitively via langchain-groq | `RateLimitError` used by the retry policy |
| Pydantic | >=2.7.0 | Output schema (`TicketClassification`), validation, API models |
| python-dotenv | >=1.0.0 | Loads `.env` (`GROQ_API_KEY`, `PROMPT_VERSION`, `DEFAULT_MODEL`, `LOG_COSTS`) |
| tiktoken | >=0.7.0 | Token counting for cost calculation |
| tenacity | >=8.3.0 | Retry with exponential backoff in `fallback_retry.py` |
| httpx | >=0.27.0 | HTTP client used by the Groq/LangChain stack |
| pytest | >=8.2.0 | Test runner |
| pytest-asyncio | >=0.23.0 | Async test support for FastAPI endpoints |

---

## Project Structure

```
Project1_support-ticket-classifier/
├── main.py                        # FastAPI app: /health, /prompts, /classify + lifespan cost summary
├── graph.py                       # LangGraph StateGraph: 6 nodes, 1 conditional edge, run_pipeline()
├── schema.py                      # Core data contract: TicketClassification + 4 enums + TicketState
├── requirements.txt               # Dependency minimum versions
├── .env                           # Local secrets/config (git-ignored): GROQ_API_KEY etc.
├── .gitignore                     # Ignores .env and __pycache__/
├── README.md                      # This file
│
├── production_modules/
│   ├── pii_redaction.py           # Regex PII scrubber: email / phone / credit card → placeholders
│   ├── prompt_injection.py        # Guard-LLM judge that blocks prompt-injection tickets (fails safe)
│   ├── prompt_versioning.py       # PROMPT_REGISTRY (v1, v2) + active-version selection via env var
│   ├── structured_output.py       # JSON-mode + function-calling LLM classification, SIMPLE_SYSTEM_PROMPT
│   ├── validate_response.py       # Pydantic schema check + business rules → ValidationResult
│   ├── fallback_retry.py          # tenacity retry (3 attempts) + SAFE_CLASSIFICATION last resort
│   ├── cost_calculator.py         # tiktoken counting, per-model pricing, SessionCostTracker
│   └── non_determinism.py         # temperature=0 consistency experiment (standalone, not in graph)
│
├── demo-ui/
│   ├── index.html                 # Single-file dark triage console; calls http://localhost:8000
│   └── screenshot.png             # Demo screenshot shown in this README
│
└── tests/                         # (planned) pytest suite — none committed yet
```

> A local virtual environment named `langgraph/` may exist in the working directory; it is **not** part of the source tree and is not referenced anywhere below.

---

## Quick Start

### Prerequisites

- **Python 3.11+** (`python --version`)
- A free **Groq API key** from [console.groq.com](https://console.groq.com) — the pipeline uses `ChatGroq`, so a Groq key is required (an OpenAI key alone will not work without the provider change described in [How to Extend](#switch-to-a-different-llm-provider))

### Step 1 — Clone the repo

```bash
git clone <your-repo-url>
cd Project1_support-ticket-classifier
```

### Step 2 — Create a virtual environment

```bash
# macOS / Linux
python -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Create the `.env` file

Create a file named `.env` in the project root (it is git-ignored):

```bash
# Required — authenticates every ChatGroq call (classification + guard LLM)
GROQ_API_KEY=gsk_your_key_here

# Optional — which prompt from PROMPT_REGISTRY to use. Default: v2
PROMPT_VERSION=v2

# Optional — model served by Groq for classify + injection guard.
# Default: openai/gpt-oss-120b
DEFAULT_MODEL=openai/gpt-oss-120b

# Optional — "true" logs per-request cost and enables the session cost
# summary printed on shutdown. Default: true
LOG_COSTS=true
```

| Variable | What it does |
|---|---|
| `GROQ_API_KEY` | Read implicitly by `langchain_groq.ChatGroq`; without it every LLM call fails |
| `PROMPT_VERSION` | Selects the active entry in `PROMPT_REGISTRY` (`v1` or `v2`) |
| `DEFAULT_MODEL` | Model ID used by `graph.py`, `structured_output.py`, `prompt_injection.py`, `fallback_retry.py` |
| `LOG_COSTS` | Toggles the `cost_log` node's log line (`"true"` = on) |

### Step 5 — Run the server

```bash
uvicorn main:app --reload
# or equivalently
python main.py
```

You'll see the startup banner:

```
+============================================================+
|       AI-Powered Support Ticket Classifier                 |
+------------------------------------------------------------+
|  Model          : openai/gpt-oss-120b                      |
|  Prompt Version : v2                                       |
|  PII Redaction  : enabled                                  |
|  Cost Tracking  : enabled                                  |
+============================================================+
```

API docs are at `http://localhost:8000/docs`.

### Step 6 — Open the demo UI

Open `demo-ui/index.html` in your browser. The header dot turns green when `/health` responds; pick one of the 10 sample tickets (late package, double charged, PII test, injection attack, …) and click **Classify ticket**.

### Step 7 — Try the API with curl

```bash
curl -X POST http://localhost:8000/classify \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_text": "My package was supposed to arrive 3 days ago and it still has not shown up. Order #45231. I want to know where it is!",
    "channel": "web_form"
  }'
```

---

## API Reference

### `GET /health`

Liveness probe used by the demo UI.

**Response `200`:**

```json
{ "status": "ok" }
```

### `GET /prompts`

Lists every registered prompt version and which one is active.

**Response `200`:**

```json
{
  "versions": [
    {
      "version_id": "v1",
      "description": "Basic classification prompt",
      "model": "llama-3.3-70b-versatile",
      "created_at": "2024-01-01"
    },
    {
      "version_id": "v2",
      "description": "Adds chain-of-thought reasoning instruction",
      "model": "llama-3.3-70b-versatile",
      "created_at": "2024-03-01"
    }
  ],
  "active": "v2"
}
```

### `POST /classify`

Runs the full LangGraph pipeline and returns the classification.

#### Request body

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `ticket_text` | `string` | **Yes** | 5–4000 characters | Raw customer support ticket text |
| `channel` | `string` | No (default `"web_form"`) | `web_form` or `email` | Where the ticket came from |

```json
{
  "ticket_text": "I cannot log into my account. I tried resetting my password but never received the reset email. Please help.",
  "channel": "web_form"
}
```

#### Response body (`ClassifyResponse`)

| Field | Type | Description |
|---|---|---|
| `issue_category` | `string` enum | One of `order_issue`, `payment_issue`, `delivery_issue`, `product_issue`, `account_issue`, `refund_request`, `other` |
| `assigned_team` | `string` enum | One of `fulfillment_team`, `payments_team`, `logistics_team`, `customer_support`, `tech_team` |
| `priority` | `string` enum | `low`, `medium`, `high`, `critical` |
| `user_sentiment` | `string` enum | `positive`, `neutral`, `negative`, `angry` |
| `confidence_score` | `float` | Model confidence, 0.0–1.0 |
| `reasoning` | `string` | One-line explanation of the classification |
| `requires_human_review` | `bool` | `true` when the ticket needs a human (low confidence, high stakes, or fallback) |
| `pii_detected` | `bool` | `true` if the redaction node scrubbed any email/phone/card from the text |
| `prompt_version` | `string \| null` | Prompt version used (`"v1"` / `"v2"`), `null` if the pipeline failed before classification |
| `cost_info` | `object \| null` | Token/cost breakdown, or `null` if the pipeline failed before `cost_log` |
| `injection_blocked` | `bool` | `true` when the guard LLM flagged the ticket — a safe default classification is returned |
| `cost_info.model` | `string` | Model ID that was priced |
| `cost_info.input_tokens` | `int` | Input tokens counted by tiktoken |
| `cost_info.output_tokens` | `int` | Output tokens counted by tiktoken |
| `cost_info.total_cost_usd` | `float` | Input + output cost in USD |

#### Example curl

```bash
curl -X POST http://localhost:8000/classify \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "I was charged twice for my order #9981. Please refund one of the payments immediately!", "channel": "email"}'
```

#### Example response

```json
{
  "issue_category": "payment_issue",
  "assigned_team": "payments_team",
  "priority": "high",
  "user_sentiment": "angry",
  "confidence_score": 0.95,
  "reasoning": "Customer reports a duplicate charge on order #9981 and requests an immediate refund.",
  "requires_human_review": false,
  "pii_detected": false,
  "prompt_version": "v2",
  "cost_info": {
    "model": "openai/gpt-oss-120b",
    "input_tokens": 298,
    "output_tokens": 88,
    "total_cost_usd": 0.000087
  },
  "injection_blocked": false
}
```

#### Errors

| Status | Cause | `detail` |
|---|---|---|
| `422` | FastAPI request validation (text < 5 or > 4000 chars, bad `channel`) | FastAPI field-error array |
| `422` | Pipeline produced no classification (`classification is None`) | The pipeline's `error` string, e.g. `"Injection Detected:instruction override"` or validation error details |
| `500` | Unhandled exception inside `run_pipeline()` | Exception message (full traceback logged server-side) |

Blocked-ticket example (`"injection_blocked": true`, `SAFE_CLASSIFICATION` returned):

```json
{
  "issue_category": "other",
  "assigned_team": "customer_support",
  "priority": "medium",
  "user_sentiment": "neutral",
  "confidence_score": 0.0,
  "reasoning": "Automatic fallback: classification failed after all retries",
  "requires_human_review": true,
  "pii_detected": false,
  "prompt_version": null,
  "cost_info": {
    "model": "openai/gpt-oss-120b",
    "input_tokens": 61,
    "output_tokens": 0,
    "total_cost_usd": 0.000036
  },
  "injection_blocked": true
}
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | **Yes** | — | Groq API key consumed by `ChatGroq` in `structured_output.py` and `prompt_injection.py` |
| `PROMPT_VERSION` | No | `v2` | Active key in `PROMPT_REGISTRY` (`prompt_versioning.py:53`) |
| `DEFAULT_MODEL` | No | `openai/gpt-oss-120b` | Model ID for classification and the guard LLM (`graph.py:20`, `structured_output.py:21`, `prompt_injection.py:19`, `fallback_retry.py:32`). Note: the startup banner in `main.py:54` falls back to `llama-3.3-70b-versatile` for display only if the variable is unset |
| `LOG_COSTS` | No | `true` | When `"true"`, `cost_log_node` logs per-request cost (`graph.py:137`) and the banner shows cost tracking as enabled (`main.py:57`) |

All variables are loaded with `load_dotenv(override=True)` — values already set in the shell take precedence over `.env`.

---

## Testing

### Run the whole suite

```bash
pytest
```

> There is no `tests/` directory committed yet — `pytest` + `pytest-asyncio` are pinned in `requirements.txt` and ready for the suite. The table below documents the **built-in self-tests** each module runs when executed directly.

### Module self-tests

Run any row with the command in the first column (from the project root, with the virtual environment activated):

| Command | What it tests | Mocks / external deps |
|---|---|---|
| `python production_modules/pii_redaction.py` | Redacts 4 samples: email+phone, card+phone, international phone+card, and a clean ticket; prints original/redacted/detected types | No mocks, fully offline, no API key |
| `python production_modules/validate_response.py` | One valid fixture (`payment_issue`, confidence 0.95) passes; one invalid fixture (bad enum, priority `urgent`, confidence `1.5`) fails with field-level errors | No mocks, offline |
| `python production_modules/prompt_versioning.py` | Lists `v1`/`v2`, prints the active version and its template | No mocks, offline (`.env` optional) |
| `python production_modules/cost_calculator.py` | Counts tokens for a sample prompt/response, prices a `llama-3.3-70b-versatile` call, prints session totals | No mocks; tiktoken downloads its encoding on first run |
| `python production_modules/structured_output.py` | Runs both strategies (function-calling vs JSON mode) on a duplicate-charge ticket and prints both JSON results | **Live Groq API**, needs `GROQ_API_KEY` |
| `python production_modules/prompt_injection.py` | Classifies 3 legitimate tickets as `SAFE` and 3 attacks (instruction override, role reassignment, jailbreak) as `BLOCKED` | **Live Groq API** (guard LLM call), needs `GROQ_API_KEY` |
| `python production_modules/fallback_retry.py` | End-to-end retry/fallback on an account-lockout ticket; prints the final `TicketClassification` JSON | **Live Groq API**; exercises `tenacity` retry on real `RateLimitError`/`ValidationError` |
| `python production_modules/non_determinism.py` | 5 runs at `temperature=0` must produce the same `issue_category`; asserts `all_match` | **Live Groq API** (5 calls), needs `GROQ_API_KEY` |

Offline-only smoke test (no key required):

```bash
python production_modules/pii_redaction.py
python production_modules/validate_response.py
python production_modules/prompt_versioning.py
python production_modules/cost_calculator.py
```

---

## Key Engineering Decisions

### Why LangGraph instead of sequential function calls

A straight-line `redact → check → classify → validate → log` function would work for the happy path, but this pipeline has a **real branch**: failed validation must route through retry/fallback, while blocked injections must skip classification entirely but still reach cost logging. With plain functions that logic degenerates into nested `if/else` spread across the call chain, and every new branch re-touches old code. LangGraph makes the **control flow data**: `route_after_validate` is a pure function over state, the conditional edge is declared once (`graph.py:180-183`), and both branches converge on `cost_log`. It also gives us a consistent state contract between nodes, free step-level observability, and room to add human-in-the-loop nodes later without restructuring — try doing that with a stack of `if` statements.

### Why Pydantic for output validation

LLM output is untrusted input. `TicketClassification` constrains the problem to **closed sets**: four enums mean the model can only emit 7 × 5 × 4 × 4 = 560 valid category/team/priority/sentiment combinations, `Field(ge=0.0, le=1.0)` bounds confidence, and unknown fields fail loudly. Pydantic also does double duty — the same model generates the JSON schema injected into the prompt (`structured_output.py:58-66`), validates the response (`model_validate`), powers the API contract (`ClassifyResponse`), and feeds `classify_with_function_calling`'s `with_structured_output`. One definition, four consumers: a typo in the schema breaks the test suite, not production.

### Why versioned prompts

Prompts are the **real source code** of an LLM feature — small wording changes swing accuracy more than any model swap. `PROMPT_REGISTRY` in `prompt_versioning.py` stamps every response with `prompt_version`, so when a ticket's classification is questioned weeks later, you can reproduce the exact prompt that produced it. Swapping `PROMPT_VERSION=v2` → `v1` in `.env` is a rollback that needs no deploy, `GET /prompts` makes the active version observable to operators, and it's the prerequisite for A/B-comparing prompt revisions against a labeled eval set.

### Why a separate injection guard LLM call

Prompt injection is a **different task** from classification: it needs adversarial security judgment, not routing. Folding it into the main prompt would (a) dilute the classifier's instructions with security boilerplate, (b) make the model both the target and the judge of the attack, and (c) fail unpredictably under load. A dedicated `temperature=0` guard with its own schema (`InjectionJudgement`) gives a clean auditable verdict (`is_injection`, `confidence`, `reasoning`, `detected_pattern`), and its **fail-safe** design — any guard exception blocks the input (`prompt_injection.py:105-109`) — encodes the right security default: when unsure, don't let unvetted text reach the model. The cost is one extra LLM call per ticket; the benefit is a security control that degrades closed, not open.

---

## How to Extend

### Add a new issue category

1. Add a member to `IssueCategory` in `schema.py`:

```python
class IssueCategory(str, Enum):
    ...
    BILLING = "billing_issue"
```

2. Mention the new category in the active template in `prompt_versioning.py` (and/or `SIMPLE_SYSTEM_PROMPT` in `structured_output.py:26-30`, which enumerates all categories for retries).
3. Everything else follows automatically: Pydantic validation accepts the value, `validate_response.py` needs no change, and the demo UI's `formatCategory()` renders it.

### Add a new prompt version

1. Copy the `v2` entry in `PROMPT_REGISTRY` (`prompt_versioning.py:9`) as `"v3"` with a new `created_at`, `description`, and `template`.
2. Set `PROMPT_VERSION=v3` in `.env`.
3. It appears in `GET /prompts` immediately; every new classification reports `"prompt_version": "v3"`. Revert by changing the env var back — no redeploy.

### Add a new PII entity type

1. Compile a regex near the others in `pii_redaction.py`:

```python
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
```

2. In `redact_pii()`, append matches with a label, following the existing span pattern:

```python
for m in _SSN_RE.finditer(result):
    spans.append((m.start(), m.end(), "[SSN REDACTED]"))
```

3. The right-to-left replacement loop and `detected_entity_types` reporting handle it automatically; add a sample to the `__main__` block.

### Add a new business validation rule

Add the check in `validate_response.py` after the schema validation (`validate_response.py:49-57`):

```python
if classification.priority == "critical" and not classification.requires_human_review:
    errors.append("Critical priority must set requires_human_review=True")
```

A failed rule sets `validation_status="fail"`, and `route_after_validate` sends the request to the fallback node automatically — no graph changes required.

### Switch to a different LLM provider

1. `pip install langchain-openai` and replace `ChatGroq` with `ChatOpenAI` in **`structured_output.py`** (both functions) and **`prompt_injection.py`** (`check_injection`) — these are the only two files that construct an LLM client for the pipeline.
2. Update `DEFAULT_MODEL` in `.env` to the new provider's model ID.
3. Add the new model's rates to `PRICING` in `cost_calculator.py` so cost accounting stays accurate.
4. If you use rate limits for retries, update the `RateLimitError` import in `fallback_retry.py:18` to the new SDK's exception. The retry/fallback/validation logic is provider-agnostic and needs no other changes.

---

## What I Learned

- **The schema is the product.** Defining `TicketClassification` first turned "make the LLM classify tickets" into a constrained data problem — the same Pydantic model drove prompt generation, response parsing, validation, and the API contract, which eliminated a whole class of integration bugs.
- **Guardrails must fail closed.** The guard LLM blocking on *its own* errors (`prompt_injection.py:105-109`) and the fallback returning a `confidence_score=0.0` answer with `requires_human_review=True` both encode the same lesson: in production, a wrong-but-flagged answer beats a crash or silent pass-through.
- **Retries need a story for attempt #2.** Naively retrying the identical prompt just fails identically three times; switching to `SIMPLE_SYSTEM_PROMPT` after the first failure (via tenacity's `attempt_number`) is what actually made retries useful.
- **Conditional edges beat nested branches.** Expressing "validate → fallback or cost_log" as a pure `route_after_validate` function kept the node code branch-free and made the control flow inspectable in one place.
- **Observability is not optional for LLM calls.** Logging `prompt_version`, PII detections, injection verdicts, and per-request token cost on every call is what turns an opaque black box into something you can debug, audit, and hand a finance bill.

---