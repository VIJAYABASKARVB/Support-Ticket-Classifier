import logging
import re
from dataclasses import dataclass,field

logger = logging.getLogger(__name__)

#Regex Patterns
# Email: re-pattern
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# Phone number : re-pattern
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)?\d{3}[\s.\-]?\d{4}(?!\d)",
)

_CC_RAW_RE = re.compile(
    r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)",
)


def _find_credit_cards(text: str) -> list[re.Match]:
  return list(_CC_RAW_RE.finditer(text))

@dataclass  # Create a class mainly for storing data.
# Stores the PII-redacted text, the types of PII found, and whether any PII was detected.
class RedactionResult:
  redacted_text : str
  # Creates a new empty list for each RedactionResult object.
  detected_entity_types: list[str] = field(default_factory=list)
  pii_detected: bool = False

def redact_pii(text: str) -> RedactionResult:
  # detected → stores detected types like ["EMAIL", "PHONE"]
  detected: list[str] = []

  # result → working copy of the text that will be modified
  result = text

  # spans → stores where the PII is located
  spans: list[tuple[int, int, str]] = []

  # find the  emails
  for m in _EMAIL_RE.finditer(result):
    spans.append((m.start(), m.end(), "[EMAIL REDACTED]"))

  # find the Credit card details
  for m in _find_credit_cards(result):
    spans.append((m.start(), m.end(), "[CREDIT CARD REDACTED]"))

  # find the phone numbers
  for m in _PHONE_RE.finditer(result):
    digit_count = sum(c.isdigit() for c in m.group())
    if digit_count > 12:
        continue
    if not any(s <= m.start() and m.end() <= e for s, e, _ in spans):
        spans.append((m.start(), m.end(), "[PHONE REDACTED]"))

  # !If nothing found!
  if not spans:
    logger.info("PII scan complete — no PII detected.")
    return RedactionResult(
        redacted_text=text,
        pii_detected=False
    )

  # sort matches RIGHT->LEFT
  spans.sort(key=lambda x: x[0], reverse=True)

  # Replace each PII match
  # Before:
  # My email is john@gmail.com

  # After:
  # My email is [EMAIL REDACTED]

  for start, end, label in spans:
    entity = label.replace("[", "").replace(" REDACTED]", "").replace(" ", "_")
    original_value = text[start:end]
    logger.warning(
        "PII detected — type: %-20s | original: %-30r | replaced with: %s",
        entity,
        original_value,
        label,
    )

    if entity not in detected:
      detected.append(entity)
    result = result[:start] + label + result[end:]

  logger.info(
    "PII redaction complete — %d item(s) redacted, types: %s",
    len(spans),
    ", ".join(detected),
  )

  return RedactionResult(
    redacted_text=result,
    detected_entity_types=detected,
    pii_detected=True,
  )


# Test the reduction working
if __name__ == "__main__":
    samples = [
        "Hi, my email is john.smith@example.com and phone is 555-867-5309.",
        "I was charged twice. Card: 4111 1111 1111 1111. Call me at (800) 555-0199.",
        "My number is +1 415 555 2671 and my card 4539 1488 0343 6467 was billed.",
        "No personal data here, just a regular support question about my order.",
    ]

    for sample in samples:
        r = redact_pii(sample)
        print(f"Original : {sample}")
        print(f"Redacted : {r.redacted_text}")
        print(f"Detected : {r.detected_entity_types}")
        print()


