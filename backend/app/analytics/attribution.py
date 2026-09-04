"""
RecoverAI Milestone 12: Incremental Net Revenue Attribution & A/B Evaluation Engine

Provides scientific, statistically defensible attribution of RecoverAI's financial lift over active Control baselines.

Core Features:
1. Strict Non-Double-Counted Net Revenue Accounting Equation:
   Net Recovered = Gross Recovered - Refund Deductions - Gateway Fees - Communication Costs - Discount Costs
2. Randomized Treatment-Control Incremental Lift Formula (ΔNRR):
   Incremental Net Revenue = (NRR_treatment - NRR_control) * Treatment Revenue Base
3. 95% Two-Proportion Confidence Intervals & p-Value Significance Testing.
4. Covariate Balance & Sample Ratio Mismatch (SRM) Checks (Standardized Mean Difference SMD < 0.10).
5. Atomic DB Refund Webhook Idempotency (UNIQUE razorpay_refund_id) with 30-Day Observation Window.
"""

import math
import datetime
import logging
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.app.models.models import (
    Experiment,
    ExperimentAssignment,
    RecoveryCase,
    Outcome,
    Payment,
    Order,
    Customer,
    PaymentAttempt,
    RefundEvent,
    AuditLog,
)

logger = logging.getLogger(__name__)


def utc_now() -> datetime.datetime:
    """Returns timezone-aware UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function approximation using error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


class AttributionEngine:
    """
    Core engine for computing randomized treatment-control incremental net revenue lift,
    verifying covariate balance, and processing idempotent refund deductions.
    """

    @staticmethod
    def compute_cohort_metrics(db: Session, experiment_id: int) -> Dict[str, Dict[str, Any]]:
        """
        Computes financial and recovery performance metrics broken down by arm (CONTROL vs TREATMENT).
        """
        assignments = (
            db.query(ExperimentAssignment, RecoveryCase, Outcome)
            .join(RecoveryCase, ExperimentAssignment.case_id == RecoveryCase.id)
            .outerjoin(Outcome, Outcome.case_id == RecoveryCase.id)
            .filter(ExperimentAssignment.experiment_id == experiment_id)
            .all()
        )

        cohorts: Dict[str, Dict[str, Any]] = {
            "CONTROL": {
                "case_count": 0,
                "total_amount_at_risk": 0.0,
                "gross_recovered": 0.0,
                "cash_collected": 0.0,
                "refund_deductions": 0.0,
                "gateway_cost": 0.0,
                "communication_cost": 0.0,
                "discount_given": 0.0,
                "net_recovered": 0.0,
                "recovered_cases": 0,
                "case_net_yields": [],
            },
            "TREATMENT": {
                "case_count": 0,
                "total_amount_at_risk": 0.0,
                "gross_recovered": 0.0,
                "cash_collected": 0.0,
                "refund_deductions": 0.0,
                "gateway_cost": 0.0,
                "communication_cost": 0.0,
                "discount_given": 0.0,
                "net_recovered": 0.0,
                "recovered_cases": 0,
                "case_net_yields": [],
            },
        }

        for asgn, case, outcome in assignments:
            group = asgn.assignment_group
            if group not in cohorts:
                continue

            cohort = cohorts[group]
            cohort["case_count"] += 1
            amount_at_risk = float(case.amount_at_risk or 0.0)
            cohort["total_amount_at_risk"] += amount_at_risk

            net = 0.0
            if outcome:
                gross = float(outcome.gross_recovered or 0.0)
                refunds = float(outcome.refund_deductions or 0.0)
                gw_cost = float(outcome.gateway_cost or 0.0)
                comm_cost = float(outcome.communication_cost or 0.0)
                disc_cost = float(outcome.discount_given or 0.0)

                # Strict Accounting Equation: Net = Cash Collected - Refunds - Gateway - Comm - Discounts
                net = max(0.0, gross - refunds - gw_cost - comm_cost - disc_cost)

                cohort["gross_recovered"] += gross
                cohort["cash_collected"] += gross
                cohort["refund_deductions"] += refunds
                cohort["gateway_cost"] += gw_cost
                cohort["communication_cost"] += comm_cost
                cohort["discount_given"] += disc_cost
                cohort["net_recovered"] += net
                if outcome.is_recovered or outcome.payment_success:
                    cohort["recovered_cases"] += 1

            # Track case yield ratio for monetary bootstrap
            yield_ratio = net / amount_at_risk if amount_at_risk > 0 else 0.0
            cohort["case_net_yields"].append((amount_at_risk, net, yield_ratio))

        for group, c in cohorts.items():
            tot_risk = c["total_amount_at_risk"]
            n_cases = c["case_count"]
            c["binary_recovery_rate"] = (c["recovered_cases"] / n_cases) if n_cases > 0 else 0.0
            c["gross_recovery_rate"] = (c["gross_recovered"] / tot_risk) if tot_risk > 0 else 0.0
            c["net_recovery_rate"] = (c["net_recovered"] / tot_risk) if tot_risk > 0 else 0.0
            c["refund_rate"] = (c["refund_deductions"] / c["gross_recovered"]) if c["gross_recovered"] > 0 else 0.0

        return cohorts

    @staticmethod
    def compute_incremental_attribution(db: Session, experiment_id: int) -> Dict[str, Any]:
        """
        Computes randomized treatment-control incremental net revenue lift.
        Separates Binary Recovery Effect (Two-Proportion Z-Test) from Financial Revenue Effect (Monetary Bootstrap).
        """
        cohorts = AttributionEngine.compute_cohort_metrics(db, experiment_id)
        ctrl = cohorts.get("CONTROL", {})
        trt = cohorts.get("TREATMENT", {})

        # --- Metric A: Binary Recovery Rate Effect ---
        r_ctrl = ctrl.get("binary_recovery_rate", 0.0)
        r_trt = trt.get("binary_recovery_rate", 0.0)
        delta_rec_pp = (r_trt - r_ctrl) * 100.0

        n_trt = trt.get("case_count", 0)
        n_ctrl = ctrl.get("case_count", 0)

        if n_trt > 0 and n_ctrl > 0:
            se_diff_rec = math.sqrt(
                (r_trt * (1.0 - r_trt) / n_trt) +
                (r_ctrl * (1.0 - r_ctrl) / n_ctrl)
            )
            z_crit = 1.96
            ci_rec_lower_pp = (r_trt - r_ctrl - z_crit * se_diff_rec) * 100.0
            ci_rec_upper_pp = (r_trt - r_ctrl + z_crit * se_diff_rec) * 100.0

            c_cases = ctrl.get("recovered_cases", 0)
            t_cases = trt.get("recovered_cases", 0)
            p_pool_rec = (c_cases + t_cases) / (n_ctrl + n_trt) if (n_ctrl + n_trt) > 0 else 0.0
            se_pool_rec = math.sqrt(p_pool_rec * (1.0 - p_pool_rec) * (1.0 / n_ctrl + 1.0 / n_trt)) if p_pool_rec > 0 else 0.0

            if se_pool_rec > 0:
                z_stat_rec = (r_trt - r_ctrl) / se_pool_rec
                p_value_rec = 2.0 * (1.0 - normal_cdf(abs(z_stat_rec)))
            else:
                z_stat_rec = 0.0
                p_value_rec = 1.0
        else:
            se_diff_rec = 0.0
            ci_rec_lower_pp = 0.0
            ci_rec_upper_pp = 0.0
            z_stat_rec = 0.0
            p_value_rec = 1.0

        is_rec_significant = bool(p_value_rec < 0.05 and delta_rec_pp > 0)

        # --- Metric B: Financial Net Revenue Rate Effect & Bootstrap CI ---
        ctrl_nrr = ctrl.get("net_recovery_rate", 0.0)
        trt_nrr = trt.get("net_recovery_rate", 0.0)
        trt_risk = trt.get("total_amount_at_risk", 0.0)

        delta_nrr = trt_nrr - ctrl_nrr
        delta_nrr_pp = delta_nrr * 100.0
        relative_lift_pct = (delta_nrr / ctrl_nrr * 100.0) if ctrl_nrr > 0 else 0.0
        incremental_net_revenue = delta_nrr * trt_risk

        # Monetary Standard Error & Financial Confidence Interval via continuous sample variance estimator
        # Calculates s_T^2 / N_T + s_C^2 / N_C on case net yield ratios (net / amount_at_risk)
        ctrl_yields = [item[2] for item in ctrl.get("case_net_yields", [])]
        trt_yields = [item[2] for item in trt.get("case_net_yields", [])]

        def calc_sample_var(vals: List[float], mean_val: float) -> float:
            if len(vals) <= 1:
                return 0.0
            return sum((x - mean_val) ** 2 for x in vals) / (len(vals) - 1)

        if n_trt > 1 and n_ctrl > 1:
            mean_ctrl_yield = sum(ctrl_yields) / len(ctrl_yields) if ctrl_yields else 0.0
            mean_trt_yield = sum(trt_yields) / len(trt_yields) if trt_yields else 0.0

            var_ctrl = calc_sample_var(ctrl_yields, mean_ctrl_yield)
            var_trt = calc_sample_var(trt_yields, mean_trt_yield)

            se_nrr = math.sqrt((var_trt / n_trt) + (var_ctrl / n_ctrl)) if (var_trt or var_ctrl) else 0.0
            ci_fin_lower_pp = (delta_nrr - 1.96 * se_nrr) * 100.0
            ci_fin_upper_pp = (delta_nrr + 1.96 * se_nrr) * 100.0
            ci_fin_lower_rev = (ci_fin_lower_pp / 100.0) * trt_risk
            ci_fin_upper_rev = (ci_fin_upper_pp / 100.0) * trt_risk
        else:
            se_nrr = 0.0
            ci_fin_lower_pp = 0.0
            ci_fin_upper_pp = 0.0
            ci_fin_lower_rev = 0.0
            ci_fin_upper_rev = 0.0

        return {
            "experiment_id": experiment_id,
            "control": ctrl,
            "treatment": trt,
            "recovery_effect": {
                "control_recovery_rate_pct": r_ctrl * 100.0,
                "treatment_recovery_rate_pct": r_trt * 100.0,
                "incremental_recovery_rate_pp": delta_rec_pp,
                "confidence_interval_95_pp": [ci_rec_lower_pp, ci_rec_upper_pp],
                "z_statistic": z_stat_rec,
                "p_value": p_value_rec,
                "statistically_significant": is_rec_significant,
            },
            "financial_effect": {
                "control_net_recovery_rate_pct": ctrl_nrr * 100.0,
                "treatment_net_recovery_rate_pct": trt_nrr * 100.0,
                "incremental_nrr_pp": delta_nrr_pp,
                "relative_lift_pct": relative_lift_pct,
                "incremental_net_revenue": incremental_net_revenue,
                "confidence_interval_95_pp": [ci_fin_lower_pp, ci_fin_upper_pp],
                "confidence_interval_95_revenue": [ci_fin_lower_rev, ci_fin_upper_rev],
            },
            # Backwards compatibility alias
            "incremental_metrics": {
                "control_net_recovery_rate_pct": ctrl_nrr * 100.0,
                "treatment_net_recovery_rate_pct": trt_nrr * 100.0,
                "incremental_recovery_rate_pp": delta_nrr_pp,
                "relative_lift_pct": relative_lift_pct,
                "incremental_net_revenue": incremental_net_revenue,
                "confidence_interval_95_pp": [ci_fin_lower_pp, ci_fin_upper_pp],
                "confidence_interval_95_revenue": [ci_fin_lower_rev, ci_fin_upper_rev],
                "z_statistic": z_stat_rec,
                "p_value": p_value_rec,
                "statistically_significant": is_rec_significant,
            },
        }

    @staticmethod
    def verify_experiment_balance(db: Session, experiment_id: int) -> Dict[str, Any]:
        """
        Verifies pre-intervention covariate balance across CONTROL and TREATMENT arms.
        Checks Sample Ratio Mismatch (SRM) and Standardized Mean Differences (SMD < 0.10).
        """
        rows = (
            db.query(ExperimentAssignment, RecoveryCase, Customer, Order, PaymentAttempt)
            .join(RecoveryCase, ExperimentAssignment.case_id == RecoveryCase.id)
            .outerjoin(Customer, RecoveryCase.customer_id == Customer.id)
            .outerjoin(Order, RecoveryCase.order_id == Order.id)
            .outerjoin(PaymentAttempt, RecoveryCase.payment_id == PaymentAttempt.payment_id)
            .filter(ExperimentAssignment.experiment_id == experiment_id)
            .all()
        )

        data = {"CONTROL": [], "TREATMENT": []}
        for asgn, case, cust, order, att in rows:
            group = asgn.assignment_group
            if group in data:
                data[group].append({
                    "amount": float(case.amount_at_risk or 0.0),
                    "ltv": float(cust.lifetime_value or 0.0) if cust else 0.0,
                    "payment_method": getattr(att, "payment_method", "CARD") if att else "CARD",
                    "failure_reason": getattr(att, "failure_reason", "UNKNOWN") if att else "UNKNOWN",
                })

        n_ctrl = len(data["CONTROL"])
        n_trt = len(data["TREATMENT"])

        # 1. Sample Ratio Mismatch (SRM) Check (Target 50/50 split)
        n_tot = n_ctrl + n_trt
        srm_pass = True
        srm_p_value = 1.0
        chi_sq = 0.0
        if n_tot > 0:
            exp_count = n_tot / 2.0
            chi_sq = ((n_ctrl - exp_count) ** 2 / exp_count) + ((n_trt - exp_count) ** 2 / exp_count)
            if chi_sq == 0.0:
                srm_p_value = 1.0000
            else:
                srm_p_value = 2.0 * (1.0 - normal_cdf(math.sqrt(chi_sq)))
            srm_pass = bool(srm_p_value > 0.01)

        # Helper function for mean & std
        def calc_stats(vals: List[float]) -> Tuple[float, float]:
            if not vals:
                return 0.0, 0.0
            mean = sum(vals) / len(vals)
            var = sum((x - mean) ** 2 for x in vals) / len(vals) if len(vals) > 1 else 0.0
            return mean, math.sqrt(var)

        # 2. Continuous Covariate Balance (SMD)
        ctrl_amounts = [d["amount"] for d in data["CONTROL"]]
        trt_amounts = [d["amount"] for d in data["TREATMENT"]]
        mean_amt_c, std_amt_c = calc_stats(ctrl_amounts)
        mean_amt_t, std_amt_t = calc_stats(trt_amounts)

        pooled_std_amt = math.sqrt((std_amt_c ** 2 + std_amt_t ** 2) / 2.0) if (std_amt_c or std_amt_t) else 1.0
        amt_smd = abs(mean_amt_t - mean_amt_c) / pooled_std_amt if pooled_std_amt > 0 else 0.0
        amt_pass = bool(amt_smd < 0.10)

        ctrl_ltvs = [d["ltv"] for d in data["CONTROL"]]
        trt_ltvs = [d["ltv"] for d in data["TREATMENT"]]
        mean_ltv_c, std_ltv_c = calc_stats(ctrl_ltvs)
        mean_ltv_t, std_ltv_t = calc_stats(trt_ltvs)

        pooled_std_ltv = math.sqrt((std_ltv_c ** 2 + std_ltv_t ** 2) / 2.0) if (std_ltv_c or std_ltv_t) else 1.0
        ltv_smd = abs(mean_ltv_t - mean_ltv_c) / pooled_std_ltv if pooled_std_ltv > 0 else 0.0
        ltv_pass = bool(ltv_smd < 0.10)

        # 3. Categorical Breakdown (Payment Methods)
        def calc_pm_dist(d_list: List[Dict[str, Any]]) -> Dict[str, float]:
            if not d_list:
                return {}
            counts: Dict[str, int] = {}
            for item in d_list:
                pm = item["payment_method"]
                counts[pm] = counts.get(pm, 0) + 1
            return {k: round(v / len(d_list) * 100.0, 1) for k, v in counts.items()}

        pm_ctrl = calc_pm_dist(data["CONTROL"])
        pm_trt = calc_pm_dist(data["TREATMENT"])

        overall_balance_pass = bool(srm_pass and amt_pass and ltv_pass)

        return {
            "experiment_id": experiment_id,
            "sample_counts": {"control": n_ctrl, "treatment": n_trt, "total": n_tot},
            "srm_check": {
                "chi_square": round(chi_sq, 4),
                "p_value": round(srm_p_value, 4),
                "pass": srm_pass,
            },
            "continuous_balance": {
                "amount_at_risk": {
                    "control_mean": round(mean_amt_c, 2),
                    "treatment_mean": round(mean_amt_t, 2),
                    "smd": round(amt_smd, 4),
                    "pass": amt_pass,
                },
                "customer_ltv": {
                    "control_mean": round(mean_ltv_c, 2),
                    "treatment_mean": round(mean_ltv_t, 2),
                    "smd": round(ltv_smd, 4),
                    "pass": ltv_pass,
                },
            },
            "categorical_balance": {
                "payment_method_control": pm_ctrl,
                "payment_method_treatment": pm_trt,
            },
            "overall_balance_pass": overall_balance_pass,
        }

    @staticmethod
    def process_refund_deduction(
        db: Session,
        razorpay_refund_id: str,
        payment_id: int,
        refund_amount: float,
        observation_window_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Atomically processes a refund webhook event with UNIQUE(razorpay_refund_id) idempotency.
        Enforces 30-day observation window before updating Outcome financial metrics.
        """
        # 1. Atomic Idempotency Check on RefundEvent
        existing_event = (
            db.query(RefundEvent)
            .filter(RefundEvent.razorpay_refund_id == razorpay_refund_id)
            .first()
        )

        if existing_event:
            logger.info(f"Duplicate refund webhook ignored: {razorpay_refund_id}")
            return {
                "status": "duplicate_refund_ignored",
                "processed": False,
                "razorpay_refund_id": razorpay_refund_id,
                "message": f"Refund ID '{razorpay_refund_id}' has already been processed.",
            }

        # 2. Fetch Payment, RecoveryCase, & Outcome
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        case = (
            db.query(RecoveryCase)
            .filter(RecoveryCase.payment_id == payment_id)
            .first()
        ) if payment else None

        case_id = case.id if case else None

        # Create RefundEvent record atomically
        new_refund = RefundEvent(
            razorpay_refund_id=razorpay_refund_id,
            payment_id=payment_id,
            recovery_case_id=case_id,
            amount=refund_amount,
            processed_at=utc_now(),
        )
        db.add(new_refund)
        db.flush()

        # 3. Check 30-Day Attribution Window & Update Outcome
        window_applied = False
        outcome_updated = False

        if case:
            now = utc_now()
            case_created = case.created_at
            if case_created:
                c_time = case_created.replace(tzinfo=datetime.timezone.utc) if case_created.tzinfo is None else case_created
                elapsed_days = (now - c_time).total_seconds() / 86400.0
            else:
                elapsed_days = 0.0

            if elapsed_days <= observation_window_days:
                window_applied = True
                outcome = db.query(Outcome).filter(Outcome.case_id == case.id).first()
                if outcome:
                    # Update Refund Deductions
                    outcome.refund_deductions = float(outcome.refund_deductions or 0.0) + refund_amount

                    # Recompute Net Recovered Revenue: Net = Gross - Refunds - Gateway - Comm - Discounts
                    gross = float(outcome.gross_recovered or 0.0)
                    gw_cost = float(outcome.gateway_cost or 0.0)
                    comm_cost = float(outcome.communication_cost or 0.0)
                    disc_cost = float(outcome.discount_given or 0.0)

                    outcome.net_recovered = max(0.0, gross - outcome.refund_deductions - gw_cost - comm_cost - disc_cost)
                    outcome_updated = True

                    # Log transition in AuditLog
                    audit = AuditLog(
                        case_id=case.id,
                        actor="SYSTEM_ATTRIBUTION",
                        event="REFUND_DEDUCTED",
                        previous_state=case.status,
                        new_state=case.status,
                        reason=f"Deducted refund {razorpay_refund_id} ({refund_amount} INR)",
                    )
                    db.add(audit)

        db.commit()

        return {
            "status": "success",
            "processed": True,
            "razorpay_refund_id": razorpay_refund_id,
            "refund_amount": refund_amount,
            "window_applied": window_applied,
            "outcome_updated": outcome_updated,
        }
