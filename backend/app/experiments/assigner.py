"""
Deterministic A/B Experiment Assigner Module

This module assigns incoming recovery cases to experiment groups (TREATMENT, CONTROL, NO_INTERVENTION).

Allocation Ratios:
- TREATMENT (50%): Uses RecoverAI's ML predictions + Gemini AI reasoning.
- CONTROL (45%): Uses static baseline strategy (e.g. static 24-hour retry).
- NO_INTERVENTION (5%): Zero recovery actions taken (used to measure natural recovery rates).

Determinism & Consistency:
Uses SHA-256 cryptographic hashing on `case_id` + `seed` to guarantee 100% assignment consistency.
Evaluating the same case multiple times will ALWAYS return the exact same assigned group.
"""

import hashlib
import logging
from dataclasses import dataclass
from sqlalchemy.orm import Session

from backend.app.models.models import Experiment, ExperimentAssignment, AuditLog
from backend.app.experiments.registry import get_or_create_experiment

logger = logging.getLogger(__name__)


@dataclass
class AssignmentResult:
    """Dataclass holding A/B experiment assignment output."""
    group: str  # TREATMENT, CONTROL, NO_INTERVENTION
    experiment_id: int
    case_id: int
    is_new_assignment: bool


def assign_case_to_experiment(
    db: Session,
    case_id: int,
    experiment_name: str = "default_recovery_ab",
    seed: int = 42,
    forced_group: Optional[str] = None,
) -> AssignmentResult:
    """
    Assigns a RecoveryCase to an A/B experiment group.
    """
    experiment = get_or_create_experiment(db, name=experiment_name, seed=seed)

    # Check if assignment already exists for this case & experiment
    existing = db.query(ExperimentAssignment).filter(
        ExperimentAssignment.experiment_id == experiment.id,
        ExperimentAssignment.case_id == case_id
    ).first()

    if existing:
        if forced_group and existing.group != forced_group:
            existing.group = forced_group
            db.commit()
        return AssignmentResult(
            group=existing.group,
            experiment_id=experiment.id,
            case_id=case_id,
            is_new_assignment=False
        )

    if forced_group:
        assigned_group = forced_group
    else:
        # Compute deterministic float [0.0 - 1.0) using SHA-256
        hash_input = f"{case_id}_{seed}_{experiment_name}".encode("utf-8")
        hash_hex = hashlib.sha256(hash_input).hexdigest()
        hash_val = int(hash_hex[:8], 16) / 0xFFFFFFFF  # Normalized float in [0.0, 1.0)

        # Determine Group Split: Treatment (50%), Control (45%), No-Intervention (5%)
        if hash_val < 0.50:
            assigned_group = "TREATMENT"
        elif hash_val < 0.95:
            assigned_group = "CONTROL"
        else:
            assigned_group = "NO_INTERVENTION"

    # Persist assignment in PostgreSQL
    assignment = ExperimentAssignment(
        experiment_id=experiment.id,
        case_id=case_id,
        group=assigned_group
    )
    db.add(assignment)

    # Audit Log
    audit = AuditLog(
        case_id=case_id,
        actor="experiment_assigner",
        event="EXPERIMENT_ASSIGNMENT",
        previous_state=None,
        new_state=assigned_group,
        reason=f"Assigned to experiment '{experiment_name}' group '{assigned_group}'"
    )
    db.add(audit)
    db.commit()

    return AssignmentResult(
        group=assigned_group,
        experiment_id=experiment.id,
        case_id=case_id,
        is_new_assignment=True
    )
