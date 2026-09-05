"""
Payment State Machine & Transition Validator Module

This module defines the explicit payment states and transition rules for RecoverAI.

State Machine Workflow:
  UNKNOWN -> FAILED -> PENDING_VERIFICATION -> RECOVERY_ELIGIBLE -> RECOVERY_ACTIVE -> RECOVERED

Terminal States:
  - AUTO_RESOLVED (Late capture arrived during verification window before recovery action)
  - RECOVERED (Captured following an active recovery intervention)
  - NOT_RECOVERABLE, POLICY_BLOCKED, CUSTOMER_OPTED_OUT, MAX_RETRIES_REACHED, EXPIRED, FAILED_PERMANENTLY

Resilience Feature:
Attempts to perform illegal transitions (e.g. moving a case from RECOVERED back to FAILED)
will raise `InvalidStateTransitionError` to prevent corrupting financial state.
"""

from enum import Enum
from typing import Set, Dict


class PaymentStatus(str, Enum):
    """
    Enum representing all valid states for a recovery case throughout its lifecycle.
    """
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    RECOVERY_ELIGIBLE = "RECOVERY_ELIGIBLE"
    RECOVERY_ACTIVE = "RECOVERY_ACTIVE"
    RECOVERED = "RECOVERED"
    AUTO_RESOLVED = "AUTO_RESOLVED"
    NOT_RECOVERABLE = "NOT_RECOVERABLE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    CUSTOMER_OPTED_OUT = "CUSTOMER_OPTED_OUT"
    MAX_RETRIES_REACHED = "MAX_RETRIES_REACHED"
    EXPIRED = "EXPIRED"
    FAILED_PERMANENTLY = "FAILED_PERMANENTLY"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal or impossible payment state transition is attempted."""
    pass


# Mapping of allowable target states for each current state
ALLOWABLE_TRANSITIONS: Dict[PaymentStatus, Set[PaymentStatus]] = {
    PaymentStatus.UNKNOWN: {
        PaymentStatus.FAILED,
        PaymentStatus.PENDING_VERIFICATION,
        PaymentStatus.RECOVERY_ELIGIBLE,
        PaymentStatus.AUTO_RESOLVED,
        PaymentStatus.RECOVERED,
        PaymentStatus.MANUAL_REVIEW
    },
    PaymentStatus.FAILED: {
        PaymentStatus.PENDING_VERIFICATION,
        PaymentStatus.RECOVERY_ELIGIBLE,
        PaymentStatus.AUTO_RESOLVED,
        PaymentStatus.FAILED_PERMANENTLY
    },
    PaymentStatus.PENDING_VERIFICATION: {
        PaymentStatus.AUTO_RESOLVED,
        PaymentStatus.RECOVERY_ELIGIBLE,
        PaymentStatus.POLICY_BLOCKED,
        PaymentStatus.CUSTOMER_OPTED_OUT,
        PaymentStatus.FAILED_PERMANENTLY,
        PaymentStatus.MANUAL_REVIEW
    },
    PaymentStatus.RECOVERY_ELIGIBLE: {
        PaymentStatus.RECOVERY_ACTIVE,
        PaymentStatus.RECOVERED,
        PaymentStatus.AUTO_RESOLVED,
        PaymentStatus.POLICY_BLOCKED,
        PaymentStatus.CUSTOMER_OPTED_OUT,
        PaymentStatus.EXPIRED,
        PaymentStatus.MAX_RETRIES_REACHED,
        PaymentStatus.MANUAL_REVIEW
    },
    PaymentStatus.RECOVERY_ACTIVE: {
        PaymentStatus.RECOVERED,
        PaymentStatus.AUTO_RESOLVED,
        PaymentStatus.MAX_RETRIES_REACHED,
        PaymentStatus.EXPIRED,
        PaymentStatus.FAILED_PERMANENTLY,
        PaymentStatus.POLICY_BLOCKED,
        PaymentStatus.MANUAL_REVIEW
    },
    # Terminal states (No outward transitions allowed)
    PaymentStatus.RECOVERED: set(),
    PaymentStatus.AUTO_RESOLVED: set(),
    PaymentStatus.NOT_RECOVERABLE: set(),
    PaymentStatus.POLICY_BLOCKED: set(),
    PaymentStatus.CUSTOMER_OPTED_OUT: set(),
    PaymentStatus.MAX_RETRIES_REACHED: set(),
    PaymentStatus.EXPIRED: set(),
    PaymentStatus.FAILED_PERMANENTLY: set(),
    PaymentStatus.MANUAL_REVIEW: set(),
}


class PaymentStateMachine:
    """
    Deterministic transition validator enforcing the Payment State Machine logic.
    """

    @staticmethod
    def can_transition(current_state: str, target_state: str) -> bool:
        """
        Determines if transitioning from `current_state` to `target_state` is legal.

        Args:
            current_state (str): The case's existing status string.
            target_state (str): The desired new status string.

        Returns:
            bool: True if allowed; False otherwise.
        """
        try:
            curr_enum = PaymentStatus(current_state)
            target_enum = PaymentStatus(target_state)
        except ValueError:
            return False

        allowed = ALLOWABLE_TRANSITIONS.get(curr_enum, set())
        return target_enum in allowed

    @staticmethod
    def transition(current_state: str, target_state: str) -> str:
        """
        Executes a state transition after validating it.

        Args:
            current_state (str): Existing status.
            target_state (str): New status.

        Returns:
            str: The target_state string if successful.

        Raises:
            InvalidStateTransitionError: If the proposed transition is prohibited.
        """
        if current_state == target_state:
            return target_state

        if not PaymentStateMachine.can_transition(current_state, target_state):
            raise InvalidStateTransitionError(
                f"Invalid payment state transition from '{current_state}' to '{target_state}'."
            )
        return target_state
