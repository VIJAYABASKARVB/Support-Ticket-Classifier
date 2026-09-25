from pydantic import BaseModel,Field
from enum import Enum
from typing import Optional

class IssueCategory(str,Enum):
  ORDER   = "order_issue"
  PAYMENT = "payment_issue"
  DELIVERY = "delivery_issue"
  PRODUCT = "product_issue"
  ACCOUNT = "account_issue"
  REFUND = "refund_request"
  OTHER = "other"

class TeamOwner(str, Enum):
    FULFILLMENT = "fulfillment_team"
    PAYMENTS = "payments_team"
    LOGISTICS = "logistics_team"
    CUSTOMER_SUPPORT = "customer_support"
    TECH = "tech_team"

class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    ANGRY = "angry"

class TicketClassification(BaseModel):
    issue_category: IssueCategory
    assigned_team: TeamOwner
    priority: Priority
    user_sentiment: Sentiment
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="One line explanation of classification")
    requires_human_review: bool