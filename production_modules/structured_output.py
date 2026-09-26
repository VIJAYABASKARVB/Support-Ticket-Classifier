# 1. Send ticket to the LLM
#         ↓
# 2. Tell the LLM what structure to return
#         ↓
# 3. Give that structured result back to the rest of the app

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError
from schema import TicketClassification

load_dotenv(override=True)

_DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "openai/gpt-oss-120b")

DEFAULT_SYSTEM_PROMPT = "You are an expert customer support ticket classifier."

# Used by fallback_retry on retry attempts — simpler, more conservative
SIMPLE_SYSTEM_PROMPT = (
    "You are a support ticket classifier. Classify into one of: "
    "order_issue, payment_issue, delivery_issue, product_issue, account_issue, refund_request, other. "
    "Keep confidence low and set requires_human_review=True if unsure."
)

def classify_with_function_calling(
    ticket_text: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    model: str = _DEFAULT_MODEL,
) -> TicketClassification:
    llm = ChatGroq(model=model, temperature=0)

    # give me the result in the exact structure of TicketClassification.
    structured_llm = llm.with_structured_output(TicketClassification)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Classify this support ticket:\n\n{ticket_text}"),
    ])

    chain = prompt | structured_llm
    return chain.invoke({"ticket_text": ticket_text})


def classify_with_json_mode(
    ticket_text: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    model: str = _DEFAULT_MODEL,
) -> TicketClassification:

    # It looks at your TicketClassification class and creates a description of what the JSON response must look like.
    schema_json = json.dumps(
      TicketClassification.model_json_schema(), 
      indent=2
    )

    # LangChain uses {} for variables in prompts so replace with {{,}}
    schema_escaped = schema_json.replace("{", "{{").replace("}", "}}")
    
    full_system = f"{system_prompt}\n\nReturn ONLY valid JSON matching this schema:\n{schema_escaped}"

    llm = ChatGroq(
        model=model,
        temperature=0,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", full_system),
        ("human", "Classify this support ticket:\n\n{ticket_text}"),
    ])

    chain = prompt | llm
    response = chain.invoke({"ticket_text": ticket_text})
    raw = json.loads(response.content)
    print(json.dumps(raw, indent=4))
    return TicketClassification.model_validate(raw)


# TESTING
if __name__ == "__main__":
    ticket = "I was charged twice for order #9981. Please refund immediately!"

    print("=== Approach 1: Function-calling ===")
    result1 = classify_with_function_calling(ticket)
    print(result1.model_dump_json(indent=2))

    print("\n=== Approach 2: JSON mode ===")
    result2 = classify_with_json_mode(ticket)
    print(result2.model_dump_json(indent=2))