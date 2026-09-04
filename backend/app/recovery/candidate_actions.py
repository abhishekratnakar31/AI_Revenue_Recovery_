"""Candidate action space definitions and cost metadata for RecoverAI ENV engine.

Defines the 6 discrete candidate actions, financial execution costs,
and priority rankings for deterministic tie-breaking.
"""

from enum import Enum
from dataclasses import dataclass
from typing import List


class ActionType(str, Enum):
    NO_ACTION = "NO_ACTION"
    RETRY = "RETRY"
    INSTANT_PAYMENT_LINK = "INSTANT_PAYMENT_LINK"
    DISCOUNTED_PAYMENT_LINK_5 = "DISCOUNTED_PAYMENT_LINK_5"
    DISCOUNTED_PAYMENT_LINK_10 = "DISCOUNTED_PAYMENT_LINK_10"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass
class CandidateAction:
    action_type: ActionType
    channel: str
    base_gateway_cost: float
    base_comm_cost: float
    discount_pct: float
    fatigue_weight: float  # INR penalty per trailing 30d failure
    priority_rank: int     # Lower numeric rank = stronger tie-break preference


def get_all_candidate_actions() -> List[CandidateAction]:
    """Return complete static space of candidate actions."""
    return [
        CandidateAction(ActionType.NO_ACTION, "none", 0.00, 0.00, 0.00, 0.00, priority_rank=1),
        CandidateAction(ActionType.RETRY, "gateway", 2.00, 0.00, 0.00, 0.10, priority_rank=2),
        CandidateAction(ActionType.INSTANT_PAYMENT_LINK, "whatsapp", 1.50, 0.50, 0.00, 1.00, priority_rank=3),
        CandidateAction(ActionType.DISCOUNTED_PAYMENT_LINK_5, "whatsapp", 1.50, 0.50, 0.05, 1.20, priority_rank=4),
        CandidateAction(ActionType.DISCOUNTED_PAYMENT_LINK_10, "whatsapp", 1.50, 0.50, 0.10, 1.50, priority_rank=5),
        CandidateAction(ActionType.MANUAL_REVIEW, "manual", 0.00, 15.00, 0.00, 0.00, priority_rank=6),
    ]
