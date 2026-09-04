"""
Experiment Registry & Metrics Module

This module manages experiment definitions and computes group performance metrics.

Responsibilities:
1. Registry Management: Creates or fetches experiment records in the `experiments` database table.
2. Performance Metrics Aggregation: Aggregates recovery rates and gross revenue across TREATMENT, CONTROL, and NO_INTERVENTION groups.
"""

import logging
from typing import Dict, Any
from sqlalchemy.orm import Session

from backend.app.models.models import Experiment, ExperimentAssignment, RecoveryCase, Outcome

logger = logging.getLogger(__name__)


def get_or_create_experiment(db: Session, name: str = "default_recovery_ab", seed: int = 42) -> Experiment:
    """
    Fetches an existing Experiment record by name, or creates a new one.

    Args:
        db (Session): Database session.
        name (str): Experiment identifier name. Default "default_recovery_ab".
        seed (int): Random seed. Default 42.

    Returns:
        Experiment: Database model instance.
    """
    exp = db.query(Experiment).filter(Experiment.name == name).first()
    if not exp:
        exp = Experiment(
            name=name,
            dataset_version="v1.0",
            random_seed=seed,
            configuration={"split": {"TREATMENT": 0.50, "CONTROL": 0.45, "NO_INTERVENTION": 0.05}}
        )
        db.add(exp)
        db.commit()
        db.refresh(exp)
    return exp


def get_experiment_metrics(db: Session, experiment_id: int) -> Dict[str, Any]:
    """
    Computes performance metrics and recovery rates across experiment groups.

    Args:
        db (Session): Database session.
        experiment_id (int): Primary key ID of Experiment.

    Returns:
        dict: Group-wise performance metrics.
    """
    assignments = db.query(ExperimentAssignment).filter(ExperimentAssignment.experiment_id == experiment_id).all()

    group_counts: Dict[str, int] = {"TREATMENT": 0, "CONTROL": 0, "NO_INTERVENTION": 0}
    group_recovered: Dict[str, int] = {"TREATMENT": 0, "CONTROL": 0, "NO_INTERVENTION": 0}
    group_revenue: Dict[str, float] = {"TREATMENT": 0.0, "CONTROL": 0.0, "NO_INTERVENTION": 0.0}

    for assign in assignments:
        group_counts[assign.group] = group_counts.get(assign.group, 0) + 1

        case = db.query(RecoveryCase).filter(RecoveryCase.id == assign.case_id).first()
        if case and case.outcome and case.outcome.payment_success:
            group_recovered[assign.group] = group_recovered.get(assign.group, 0) + 1
            group_revenue[assign.group] = group_revenue.get(assign.group, 0.0) + case.outcome.gross_recovered

    group_metrics = {}
    for grp in ("TREATMENT", "CONTROL", "NO_INTERVENTION"):
        total = group_counts.get(grp, 0)
        rec = group_recovered.get(grp, 0)
        rev = group_revenue.get(grp, 0.0)
        rate = (rec / total * 100.0) if total > 0 else 0.0

        group_metrics[grp] = {
            "total_cases": total,
            "recovered_cases": rec,
            "recovery_rate_pct": round(rate, 2),
            "total_gross_recovered": round(rev, 2)
        }

    return {
        "experiment_id": experiment_id,
        "total_assignments": len(assignments),
        "group_metrics": group_metrics
    }
