"""Action-conditioned recovery probability estimator P(recovery | action, context).

Uses context-aware efficacy multipliers as heuristic simulator priors.
Bounded strictly in [0.0, 0.98] to enforce operational probability ceiling.
"""

from backend.app.ml.schemas import MLFeatureVector
from backend.app.recovery.candidate_actions import CandidateAction, ActionType

ACTION_EFFICACY_MULTIPLIERS = {
    "RETRY": {
        "BANK_TIMEOUT": 1.35,
        "INSUFFICIENT_FUNDS": 0.50,
        "AUTH_FAILURE": 0.30,
        "EXPIRED_CARD": 0.05,
        "DEFAULT": 0.70,
    },
    "INSTANT_PAYMENT_LINK": {
        "BANK_TIMEOUT": 1.10,
        "INSUFFICIENT_FUNDS": 1.30,
        "AUTH_FAILURE": 1.45,
        "EXPIRED_CARD": 1.60,
        "DEFAULT": 1.20,
    },
    "DISCOUNTED_PAYMENT_LINK_5": 1.15,
    "DISCOUNTED_PAYMENT_LINK_10": 1.25,
    "MANUAL_REVIEW": 1.20,
}


def estimate_action_recovery_probability(
    base_p: float,
    vector: MLFeatureVector,
    action: CandidateAction
) -> float:
    """Calculate P(recovery | action, context) bounded in [0.0, 0.98].
    
    Args:
        base_p: Calibrated baseline P(recovery | context) from M7.
        vector: MLFeatureVector for the case.
        action: CandidateAction under evaluation.
        
    Returns:
        Action-conditioned probability P(recovery | action) in [0.0, 0.98].
    """
    if action.action_type == ActionType.NO_ACTION:
        return round(base_p, 4)

    reason = vector.failure_reason.upper()
    attempt = vector.attempt_number

    if action.action_type == ActionType.RETRY:
        retry_dict = ACTION_EFFICACY_MULTIPLIERS["RETRY"]
        m = retry_dict.get(reason, retry_dict["DEFAULT"])
        m *= (0.85 ** (attempt - 1))
        p = base_p * m

    elif action.action_type == ActionType.INSTANT_PAYMENT_LINK:
        link_dict = ACTION_EFFICACY_MULTIPLIERS["INSTANT_PAYMENT_LINK"]
        m = link_dict.get(reason, link_dict["DEFAULT"])
        p = base_p * m

    elif action.action_type == ActionType.DISCOUNTED_PAYMENT_LINK_5:
        p_link = estimate_action_recovery_probability(
            base_p, vector, CandidateAction(ActionType.INSTANT_PAYMENT_LINK, "whatsapp", 1.5, 0.5, 0.0, 1.0, 3)
        )
        p = p_link * ACTION_EFFICACY_MULTIPLIERS["DISCOUNTED_PAYMENT_LINK_5"]

    elif action.action_type == ActionType.DISCOUNTED_PAYMENT_LINK_10:
        p_link = estimate_action_recovery_probability(
            base_p, vector, CandidateAction(ActionType.INSTANT_PAYMENT_LINK, "whatsapp", 1.5, 0.5, 0.0, 1.0, 3)
        )
        p = p_link * ACTION_EFFICACY_MULTIPLIERS["DISCOUNTED_PAYMENT_LINK_10"]

    elif action.action_type == ActionType.MANUAL_REVIEW:
        p = base_p * ACTION_EFFICACY_MULTIPLIERS["MANUAL_REVIEW"]
    else:
        p = base_p

    return max(0.0, min(0.98, round(p, 4)))
