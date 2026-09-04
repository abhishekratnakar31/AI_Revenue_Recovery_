"""Comprehensive unit and integration test suite for RecoverAI ML Pipeline."""

import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models.models import Customer, Order, Payment, PaymentAttempt, RecoveryCase, ModelPrediction
from backend.app.ml.schemas import MLFeatureVector, PredictionOutput
from backend.app.ml.features import extract_features_from_case
from backend.app.ml.dataset import generate_historical_dataset, temporal_split
from backend.app.ml.preprocessing import feature_vector_to_dict, feature_vectors_to_dataframe, build_preprocessor
from backend.app.ml.model import RecoveryModel
from backend.app.ml.calibration import evaluate_calibration, evaluate_raw_vs_calibrated, evaluate_segment_metrics
from backend.app.ml.predict import predict_recovery_probability, clear_model_cache, get_cached_model


# Database setup for testing
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture
def db():
    engine = create_engine(
        SQLALCHEMY_TEST_DATABASE_URL, connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    clear_model_cache()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def sample_case_fixture(db):
    """Fixture creating a test RecoveryCase and linked entities."""
    now = datetime.now(timezone.utc)
    cust = Customer(
        external_customer_id="cust_ml_101",
        lifetime_value=15000.0,
        successful_payment_count=5,
        failed_payment_count=1,
    )
    db.add(cust)
    db.commit()

    order = Order(
        razorpay_order_id="ord_ml_101",
        customer_id=cust.id,
        amount=2999.0,
        currency="INR",
        status="created",
    )
    db.add(order)
    db.commit()

    pay = Payment(
        razorpay_payment_id="pay_ml_101",
        order_id=order.id,
        amount=2999.0,
        currency="INR",
        status="failed",
    )
    db.add(pay)
    db.commit()

    attempt = PaymentAttempt(
        payment_id=pay.id,
        attempt_number=1,
        status="FAILED",
        failure_reason="BANK_TIMEOUT",
        payment_method="UPI",
        timestamp=now - timedelta(minutes=5),
    )
    db.add(attempt)
    db.commit()

    case = RecoveryCase(
        case_type="ONE_TIME",
        customer_id=cust.id,
        order_id=order.id,
        payment_id=pay.id,
        amount_at_risk=2999.0,
        status="RECOVERY_ELIGIBLE",
        created_at=now,
    )
    db.add(case)
    db.commit()

    return case.id


def test_1_feature_leakage_safety():
    """Test 1: Verify MLFeatureVector schema contains zero target or post-failure fields."""
    now = datetime.now(timezone.utc)
    vector = MLFeatureVector(
        feature_timestamp=now,
        amount=1999.0,
        customer_ltv=5000.0,
        customer_failure_count_30d=1,
        customer_success_count_90d=3,
        attempt_number=1,
        hour=12,
        day_of_week=2,
        payment_method="UPI",
        failure_reason="BANK_TIMEOUT",
        subscription=False,
    )
    fields = set(vector.model_dump().keys())

    # Assert forbidden leakage fields do NOT exist
    forbidden_fields = {"target", "recovered", "recovery_time", "selected_action", "refund_amount", "future_attempts"}
    assert fields.intersection(forbidden_fields) == set()


def test_2_feature_timestamp_boundary(db, sample_case_fixture):
    """Test 2: Verify events occurring after feature_timestamp do not alter feature values."""
    case_id = sample_case_fixture
    v1 = extract_features_from_case(db, case_id)

    # Insert a future attempt occurring AFTER feature_timestamp
    future_time = v1.feature_timestamp + timedelta(hours=2)
    pay = db.query(Payment).first()
    future_attempt = PaymentAttempt(
        payment_id=pay.id,
        attempt_number=2,
        status="FAILED",
        failure_reason="EXPIRED_CARD",
        payment_method="CARD",
        timestamp=future_time,
    )
    db.add(future_attempt)
    db.commit()

    v2 = extract_features_from_case(db, case_id)

    # Features at feature_timestamp must remain unchanged!
    assert v2.attempt_number == v1.attempt_number
    assert v2.payment_method == v1.payment_method
    assert v2.failure_reason == v1.failure_reason


def test_3_unknown_category_handling():
    """Test 3: Verify preprocessor and model handle unknown categorical features without crashing."""
    df = generate_historical_dataset(num_samples=100, random_seed=42)
    train_df, val_df, test_df = temporal_split(df)

    model = RecoveryModel(calibration_method="isotonic")
    model.fit(train_df, val_df)

    # Inject unknown categorical value
    unseen_df = test_df.copy()
    unseen_df["payment_method"] = "WALLET"  # Unseen category
    unseen_df["failure_reason"] = "UNKNOWN_CODE"  # Unseen category

    probas = model.predict_proba(unseen_df)
    assert len(probas) == len(unseen_df)
    assert all(0.0 <= p <= 1.0 for p in probas)


def test_4_probability_range():
    """Test 4: Verify output probabilities are strictly in [0.0, 1.0]."""
    df = generate_historical_dataset(num_samples=150, random_seed=42)
    train_df, val_df, test_df = temporal_split(df)

    model = RecoveryModel(calibration_method="isotonic")
    model.fit(train_df, val_df)

    probs = model.predict_proba(test_df)
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_5_calibration_and_metrics():
    """Test 5: Verify model evaluation yields Brier score <= 0.25 and ROC-AUC > 0.65."""
    df = generate_historical_dataset(num_samples=500, random_seed=42)
    train_df, val_df, test_df = temporal_split(df)

    model = RecoveryModel(calibration_method="isotonic")
    model.fit(train_df, val_df)

    probs = model.predict_proba(test_df)
    metrics = evaluate_calibration(test_df["target"].values, probs)

    assert metrics["brier_score"] <= 0.25
    assert metrics["roc_auc"] >= 0.65


def test_6_temporal_split_ordering():
    """Test 6: Verify temporal split enforces strict chronological partitioning."""
    df = generate_historical_dataset(num_samples=500, random_seed=42)
    train_df, val_df, test_df = temporal_split(df, train_ratio=0.70, val_ratio=0.15, test_ratio=0.15)

    assert train_df["feature_timestamp"].max() < val_df["feature_timestamp"].min()
    assert val_df["feature_timestamp"].max() < test_df["feature_timestamp"].min()


def test_7_prediction_persistence_and_audit(db, sample_case_fixture):
    """Test 7: Verify predict_recovery_probability writes to model_predictions PostgreSQL table."""
    case_id = sample_case_fixture
    out = predict_recovery_probability(db, case_id, model_path="non_existent_path.pkl")

    assert out.prediction_source == "FALLBACK"
    assert 0.0 <= out.probability <= 1.0

    # Query DB record
    pred = db.query(ModelPrediction).filter(ModelPrediction.recovery_case_id == case_id).first()
    assert pred is not None
    assert pred.prediction == out.probability
    assert pred.model_name == out.model_type


def test_8_model_version_and_metadata_artifact():
    """Test 8: Verify saving RecoveryModel creates feature_metadata.json artifact."""
    temp_dir = tempfile.mkdtemp()
    try:
        model_path = os.path.join(temp_dir, "test_model.pkl")
        metadata_path = os.path.join(temp_dir, "feature_metadata.json")

        df = generate_historical_dataset(num_samples=100, random_seed=42)
        train_df, val_df, test_df = temporal_split(df)

        model = RecoveryModel()
        model.fit(train_df, val_df)
        model.save(model_path)

        assert os.path.exists(model_path)
        assert os.path.exists(metadata_path)

        loaded = RecoveryModel.load(model_path)
        assert loaded.model_version == model.model_version
    finally:
        shutil.rmtree(temp_dir)


def test_9_model_missing_empirical_fallback(db, sample_case_fixture):
    """Test 9: Verify missing model artifact triggers empirical failure-reason fallbacks."""
    case_id = sample_case_fixture
    out = predict_recovery_probability(db, case_id, model_path="invalid_file.pkl")

    assert out.prediction_source == "FALLBACK"
    assert out.model_version == "fallback-v1"
    assert out.model_type == "FallbackBaseline"
    # BANK_TIMEOUT fallback is 0.41
    assert out.probability == 0.41


def test_10_model_caching_and_determinism():
    """Test 10: Verify in-memory model caching singleton returns identical probability."""
    temp_dir = tempfile.mkdtemp()
    try:
        model_path = os.path.join(temp_dir, "cached_model.pkl")
        df = generate_historical_dataset(num_samples=100, random_seed=42)
        train_df, val_df, test_df = temporal_split(df)

        model = RecoveryModel()
        model.fit(train_df, val_df)
        model.save(model_path)

        clear_model_cache()
        m1 = get_cached_model(model_path)
        m2 = get_cached_model(model_path)

        assert m1 is m2  # Singleton memory instance
    finally:
        shutil.rmtree(temp_dir)
        clear_model_cache()


def test_11_segment_metrics_evaluation():
    """Test 11: Verify segment-level metrics breakdown across payment methods."""
    df = generate_historical_dataset(num_samples=500, random_seed=42)
    train_df, val_df, test_df = temporal_split(df)

    model = RecoveryModel()
    model.fit(train_df, val_df)
    probs = model.predict_proba(test_df)

    segment_res = evaluate_segment_metrics(test_df, test_df["target"].values, probs, "payment_method")
    assert "UPI" in segment_res or "CARD" in segment_res
    for method, metrics in segment_res.items():
        assert "brier_score" in metrics
        assert "roc_auc" in metrics


def test_12_current_failure_exclusion(db, sample_case_fixture):
    """Test 12: Verify that current failed attempt is EXCLUDED from customer_failure_count_30d (< feature_ts)."""
    case_id = sample_case_fixture
    vector = extract_features_from_case(db, case_id)

    # Customer has 1 attempt linked to current case, but prior failure count must be 0!
    assert vector.customer_failure_count_30d == 0


def test_13_unknown_category_preservation(db, sample_case_fixture):
    """Test 13: Verify unrecognized payment method maps to UNKNOWN instead of CARD."""
    case_id = sample_case_fixture
    case = db.query(RecoveryCase).filter(RecoveryCase.id == case_id).first()
    pay = db.query(Payment).filter(Payment.id == case.payment_id).first()

    # Create attempt with unseen payment method as the initial attempt
    custom_attempt = PaymentAttempt(
        payment_id=pay.id,
        attempt_number=1,
        status="FAILED",
        failure_reason="SOME_NEW_REASON",
        payment_method="CRYPTO_WALLET",
        timestamp=case.created_at - timedelta(minutes=10),
    )
    db.add(custom_attempt)
    db.commit()

    vector = extract_features_from_case(db, case_id)
    assert vector.payment_method == "UNKNOWN"
    assert vector.failure_reason == "UNKNOWN"


def test_14_baseline_versus_ml_performance():
    """Test 14: Verify calibrated ML model achieves lower Brier Score error than naive mean baseline."""
    import numpy as np
    df = generate_historical_dataset(num_samples=1000, random_seed=42)
    train_df, val_df, test_df = temporal_split(df)

    model = RecoveryModel()
    model.fit(train_df, val_df)

    ml_probs = model.predict_proba(test_df)
    y_test = test_df["target"].values
    ml_eval = evaluate_calibration(y_test, ml_probs)

    base_p = float(train_df["target"].mean())
    base_probs = np.full_like(y_test, fill_value=base_p, dtype=float)
    base_eval = evaluate_calibration(y_test, base_probs)

    # ML model Brier score MUST be lower than naive mean baseline Brier score!
    assert ml_eval["brier_score"] < base_eval["brier_score"]

