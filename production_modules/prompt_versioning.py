import os
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

# “If the variable already exists, let the .env file replace it.”
load_dotenv(override=True)

PROMPT_REGISTRY: dict[str, dict] = {
    "v1": {
        "version_id": "v1",
        "model": "llama-3.3-70b-versatile",
        "created_at": "2024-01-01",
        "description": "Basic classification prompt",
        "template": "You are a customer support ticket classifier.",
    },
    "v2": {
        "version_id": "v2",
        "model": "llama-3.3-70b-versatile",
        "created_at": "2024-03-01",
        "description": "Adds chain-of-thought reasoning instruction",
        "template": 
        """
          You are an expert customer support ticket classifier.

          Think step by step before classifying:
          1. Identify the core problem the customer is facing.
          2. Assess the emotional tone and urgency.
          3. Determine which team is best equipped to resolve this.
          4. Assign a priority based on business impact and customer sentiment.
          5. Flag for human review if ambiguous or high-stakes.
        """,
    },
}


# Get the version of prompt user tells
def get_prompt(version:str) -> dict:
  if version not in PROMPT_REGISTRY:
    raise ValueError(
      f"Unknown prompt version:{version}. Available:{list(PROMPT_REGISTRY)}"
    )
  return PROMPT_REGISTRY[version]


def get_latest() -> dict:
  latest_key = sorted(PROMPT_REGISTRY.keys())[-1] # get the last item
  return PROMPT_REGISTRY[latest_key]


def get_active_version() -> str:
  # sets the default version
  return os.getenv("PROMPT_VERSION","v2")


def get_active_prompt() -> dict:
  return get_prompt(get_active_version())


def list_versions() -> list[dict]:
    return [
        {
            "version_id": v["version_id"],
            "description": v["description"],
            "model": v["model"],
            "created_at": v["created_at"],
        }
        for v in PROMPT_REGISTRY.values()
    ]


# TESTING

if __name__ == "__main__":
    print("Available versions:")
    for v in list_versions():
        print(f"  {v['version_id']}: {v['description']}")
    print(f"\nActive version: {get_active_version()}")
    prompt = get_active_prompt()
    print(f"\nActive prompt template:\n{prompt['template']}")


