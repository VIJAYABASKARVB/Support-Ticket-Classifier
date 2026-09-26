import tiktoken
from dataclasses import dataclass, field
from typing import Optional


# LLM pricing per 1,000 input and output tokens.
PRICING: dict[str, dict[str, float]] = {
    "llama-3.3-70b-versatile": {
        "input": 0.00059,
        "output": 0.00079,
    },
    "llama-3.1-8b-instant": {
        "input": 0.00005,
        "output": 0.00008,
    },
}


# Stores the token usage and cost details for a single LLM call.
@dataclass
class CostInfo:
    model: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float


# Tracks the total token usage and cost for the current application session.
class SessionCostTracker:

    # Initialize all session totals to zero.
    def __init__(self):
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cost_usd: float = 0.0
        self._call_count: int = 0

    # Add the cost information from one LLM call to the session totals.
    def record(self, cost_info: CostInfo) -> None:
        self._total_input_tokens += cost_info.input_tokens
        self._total_output_tokens += cost_info.output_tokens
        self._total_cost_usd += cost_info.total_cost_usd
        self._call_count += 1

    # Return a summary of all LLM calls made during the current session.
    @property
    def summary(self) -> dict:
        return {
            "calls": self._call_count,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_cost_usd": round(self._total_cost_usd, 6),
        }


# Create one tracker that keeps cost totals for the current process.
session_tracker = SessionCostTracker()


# Count how many tokens are present in the given text.
def count_tokens(
    text: str,
    model: str = "llama-3.3-70b-versatile",
) -> int:
    try:
        # Use the tokenizer associated with the selected model.
        encoding = tiktoken.encoding_for_model(model)

    except KeyError:
        # Fall back to a general tokenizer if the model is not recognized.
        encoding = tiktoken.get_encoding("cl100k_base")

    # Encode the text and return the number of generated tokens.
    return len(encoding.encode(text))


# Calculate the cost of an LLM call and optionally add it to the session total.
def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    record_to_session: bool = True,
) -> CostInfo:

    # Get the model's pricing, or use the default model's pricing if unavailable.
    pricing = PRICING.get(
        model,
        PRICING["llama-3.3-70b-versatile"],
    )

    # Calculate the cost of the input tokens.
    input_cost = (input_tokens / 1000) * pricing["input"]

    # Calculate the cost of the output tokens.
    output_cost = (output_tokens / 1000) * pricing["output"]

    # Add input and output costs to get the total call cost.
    total = input_cost + output_cost

    # Store all cost and token information in a CostInfo object.
    info = CostInfo(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost_usd=round(input_cost, 6),
        output_cost_usd=round(output_cost, 6),
        total_cost_usd=round(total, 6),
    )

    # Record this call in the session tracker when enabled.
    if record_to_session:
        session_tracker.record(info)

    return info


# Run this section only when the file is executed directly.
if __name__ == "__main__":

    # Example input sent to the LLM.
    prompt = "Classify this ticket: My order hasn't arrived after 2 weeks!"

    # Example response returned by the LLM.
    response = '{"issue_category": "delivery_issue", "priority": "high"}'

    # Count tokens in the input and output.
    in_tokens = count_tokens(prompt)
    out_tokens = count_tokens(response)

    # Calculate the cost of the example LLM call.
    cost = calculate_cost(
        "llama-3.3-70b-versatile",
        in_tokens,
        out_tokens,
    )

    # Display the calculated cost information.
    print(f"Input tokens : {cost.input_tokens}")
    print(f"Output tokens: {cost.output_tokens}")
    print(f"Input cost   : ${cost.input_cost_usd:.6f}")
    print(f"Output cost  : ${cost.output_cost_usd:.6f}")
    print(f"Total cost   : ${cost.total_cost_usd:.6f}")

    # Display the total cost accumulated during the session.
    print(f"Session total: {session_tracker.summary}")