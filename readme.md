# RecoverAI — Autonomous AI Revenue Recovery & Observability Platform

[![Backend CI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![Frontend CI](https://img.shields.io/badge/Next.js-14%2B-000000?style=flat-square&logo=next.js)](https://nextjs.org)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python)](https://python.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0%2B-3178C6?style=flat-square&logo=typescript)](https://typescriptlang.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-4169E1?style=flat-square&logo=postgresql)](https://postgresql.org)
[![Demo Video](https://img.shields.io/badge/Pitch_Video-Google_Drive-4285F4?style=flat-square&logo=googledrive)](https://drive.google.com/drive/folders/1eQ_v0HPAqTuvK785mvbHhTnwRBnxReGu?usp=drive_link)
[![License](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)

**RecoverAI** is a production-oriented, extensible revenue recovery platform engineered for high-volume e-commerce merchants. It converts failed checkout payment attempts into recovered net revenue using **calibrated machine learning models**, **Expected Net Value (ENV) optimization**, **real-time gateway route degradation monitoring**, **merchant policy safety guardrails**, and **randomized A/B trial evaluation**.

Unlike legacy recovery tools that rely on rigid retries or blanket discount campaigns, RecoverAI estimates the expected economic value of every potential intervention—recovering payments while enforcing merchant-defined economic and risk constraints with zero revenue overcounting.

> 🎥 **Pitch & Product Demo Video:** Access the full 5-minute video walkthrough and recording assets on [Google Drive](https://drive.google.com/drive/folders/1eQ_v0HPAqTuvK785mvbHhTnwRBnxReGu?usp=drive_link).

---

## 📋 Table of Contents

- [Executive Summary & Core Value Proposition](#-executive-summary--core-value-proposition)
- [What is Actually AI?](#-what-is-actually-ai)
- [The AI Decision Loop](#-the-ai-decision-loop)
- [Key Features & Capabilities](#-key-features--capabilities)
- [System Architecture](#-system-architecture)
- [Technical Architecture](#-technical-architecture)
  - [Webhook Ingestion & Idempotency Layer](#webhook-ingestion--idempotency-layer)
  - [Simplified Case Lifecycle State Machine](#simplified-case-lifecycle-state-machine)
  - [Calibrated ML Recovery Model](#calibrated-ml-recovery-model)
  - [Expected Net Value (ENV) Decision Engine](#expected-net-value-env-decision-engine)
  - [Gateway Route Degradation Protection](#gateway-route-degradation-protection)
  - [Merchant Safety & Policy Guardrails](#merchant-safety--policy-guardrails)
  - [LLM Customer Communication Agent](#llm-customer-communication-agent)
  - [Randomized A/B Evaluation & Revenue Attribution](#randomized-ab-evaluation--revenue-attribution)
  - [Deterministic Simulation Suite & Preset Lab](#deterministic-simulation-suite--preset-lab)
- [Database Schema & Data Model](#-database-schema--data-model)
- [REST API Reference](#-rest-api-reference)
- [Recommended Demo Flow](#-recommended-demo-flow)
- [Current Scope & Production Boundaries](#-current-scope--production-boundaries)
- [Getting Started & Installation](#-getting-started--installation)
- [Running the Application](#-running-the-application)
- [Testing & Quality Assurance](#-testing--quality-assurance)
- [Project Directory Structure](#-project-directory-structure)
- [License & Acknowledgments](#-license--acknowledgments)

---

## 💡 Executive Summary & Core Value Proposition

Failed payments represent a significant source of avoidable revenue loss for e-commerce merchants. Checkout failures stem from various root causes:
- **Authorization Timeouts:** Temporary issuing bank or gateway degradation (e.g. HDFC UPI authorization lag).
- **Insufficient Funds:** Customer lacks available balance at checkout.
- **Route Outages:** A payment gateway or bank combination experiences abnormal failure spikes.
- **Customer Friction:** Friction during multi-factor authentication or card re-entry.

### The Problem with Legacy Solutions
1. **Naive Retries:** Blindly retrying a failed card down a degraded bank route wastes customer attempts and worsens failure spikes.
2. **Margin Erosion:** Issuing 20% discount links to high-value customers who would have self-recovered organically destroys profit margins.
3. **Spam Notifications:** Blasting non-contextual SMS or WhatsApp messages increases customer churn and opt-outs.
4. **Revenue Overcounting:** Claiming 100% of organic customer self-recoveries as "AI revenue recovery".

### How RecoverAI Solves This
- **Adaptive Recovery:** Differentiates between organic self-recovery and true churn risk.
- **Economic Profit Optimization:** Selects actions that maximize Expected Net Value (ENV), factoring in recovery probability, discount costs, communication fees, and customer fatigue penalties.
- **Route Degradation Intelligence:** Monitors route failure rates in real time and automatically pauses direct retries on degraded bank routes while allowing safe payment links.
- **Randomized A/B Attribution:** Evaluates recovery performance against a randomized control baseline to measure **estimated incremental net revenue**.

---

## 🤖 What is Actually AI?

RecoverAI cleanly separates machine learning prediction, economic optimization, and language generation from deterministic financial execution:

| Component | AI/Statistical Role | Execution Nature |
| :--- | :--- | :--- |
| **XGBoost + Isotonic Calibration** | Predicts baseline recovery probability $P(\text{recovery})$ based on payment & customer features. | Probabilistic (ML) |
| **Expected Net Value (ENV) Engine** | Evaluates candidate interventions and optimizes net expected profit over baseline. | Algorithmic Optimization |
| **LLM Communication Agent** | Generates personalized customer messages and human-readable audit explanations (Gemini / OpenAI / Mock). | Generative AI (LLM) |
| **Route Health Monitor** | Statistical Z-score anomaly detection across `(gateway, payment_method, bank)` combinations. | Statistical Anomaly Detection |
| **Policy Guardrails Engine** | Enforces merchant discount caps, transaction thresholds, and privacy opt-outs. | **100% Deterministic** |
| **Idempotent Executor** | Executes payment links, retries, and manual review routing safely. | **100% Deterministic** |
| **Attribution Engine** | Calculates estimated incremental NRR lift and A/B trial statistics. | **Deterministic Math** |

> **Architectural Principle:** AI is used strictly where prediction, economic optimization, or language generation is valuable. Deterministic backend systems remain 100% responsible for money movement, safety guardrails, price limits, and idempotency.

---

## 🔄 The AI Decision Loop

```text
               RECOVERAI AI DECISION LOOP
               
                     Failed Payment
                           │
                           ▼
             ┌───────────────────────────┐
             │   ML Recovery Model       │
             │  "Will this recover?"     │
             └─────────────┬─────────────┘
                           │
                           ▼
             ┌───────────────────────────┐
             │   ENV Decision Engine     │
             │  "What should we do?"     │
             └─────────────┬─────────────┘
                           │
                           ▼
             ┌───────────────────────────┐
             │   Safety Guardrails       │
             │   "Is it allowed?"        │
             └─────────────┬─────────────┘
                           │
                           ▼
             ┌───────────────────────────┐
             │   Action Executor         │
             │   "Execute once"          │
             └─────────────┬─────────────┘
                           │
                           ▼
             ┌───────────────────────────┐
             │   LLM Communication       │
             │  "How do we inform?"      │
             └─────────────┬─────────────┘
                           │
                           ▼
             ┌───────────────────────────┐
             │   A/B Attribution         │
             │  "Did it create value?"   │
             └───────────────────────────┘
```

---

## ✨ Key Features & Capabilities

- **Backend-Projected Decision Audit Trail:** Transparent, step-by-step visual trace for every recovery case: *Payment Attempt $\rightarrow$ Calibrated ML Probability $\rightarrow$ ENV Engine Evaluation $\rightarrow$ Route Safety & Policy Check $\rightarrow$ Action Dispatch $\rightarrow$ Attribution Summary*.
- **Gateway Route Degradation Monitor:** Statistical Z-score monitoring across canonical `(gateway, payment_method, bank)` combinations.
- **Merchant Policy Safety Controls:** Versioned, merchant-configured guardrails for retry counts, retry intervals, notification limits, maximum discount caps, and manual approval thresholds.
- **Deterministic 7-Preset Lab:** Reproducible test suite validating edge cases: Bank Timeouts, Confirmed Degradations, Budget Incentives, High-Value Manual Reviews, Privacy Opt-Outs, Fraud Blocks, and Post-Recovery Refunds.
- **Zero Financial Hallucinations:** LLMs generate contextual customer text based strictly on immutable, pre-computed backend parameters (link URLs, discount values, order amounts).

---

## 🏗️ System Architecture

```text
┌─────────────────┐      ┌──────────────────────────┐      ┌─────────────────────────┐
│ Checkout Event  │ ────►│ Webhook Ingestion        │ ────►│ Case Lifecycle          │
│ Payment Failure │      │ HMAC & Idempotency Check │      │ Case Ingestion & Status │
└─────────────────┘      └──────────────────────────┘      └────────────┬────────────┘
                                                                        │
┌─────────────────────────┐      ┌──────────────────────────┐           │
│ ENV Action Engine       │◄──── │ Calibrated ML Model      │◄──────────┘
│ Maximize Expected Profit│      │ Gradient Boost + Isotonic│
└────────────┬────────────┘      └──────────────────────────┘
             │
             ▼
┌─────────────────────────┐      ┌──────────────────────────┐      ┌─────────────────────────┐
│ Outage/Route Health     │ ────►│ Policy Guardrails        │ ────►│ Idempotent Executor     │
│ Z-Score Failure Monitor │      │ Caps & Risk Review Gates │      │ Payment Link / Retry    │
└─────────────────────────┘      └──────────────────────────┘      └────────────┬────────────┘
                                                                        │
┌─────────────────────────┐      ┌──────────────────────────┐           │
│ A/B Attribution         │◄──── │ LLM Communication Agent  │◄──────────┘
│ Treatment vs Control    │      │ Gemini / OpenAI / Mock   │
└─────────────────────────┘      └──────────────────────────┘
```

---

## 🔬 Technical Architecture

### Webhook Ingestion & Idempotency Layer
- **Endpoint:** `POST /api/v1/webhooks/razorpay`
- **Security:** HMAC-SHA256 signature verification against configured webhook secret keys (`X-Razorpay-Signature`).
- **Idempotency:** Unique `event_id` tracking in PostgreSQL prevents duplicate processing of retried webhook payloads.
- **Event Handlers:**
  - `payment.failed` $\rightarrow$ Triggers case ingestion and recovery pipeline evaluation.
  - `payment.captured` / `payment.authorized` $\rightarrow$ Transitions case to `RECOVERED` or `AUTO_RESOLVED`, recording gross and net revenue.
  - `refund.processed` $\rightarrow$ Deducts refund amount from net recovered revenue metrics.

### Simplified Case Lifecycle State Machine
Governed by `PaymentStateMachine` (`backend/app/recovery/case_manager.py`), enforcing valid state transitions:

```text
[INITIATED] ──► [FAILED] ──► [PENDING_VERIFICATION] ──► [RECOVERY_ELIGIBLE] ──► [RECOVERY_ACTIVE]
                                                                                      │
               ┌───────────────────────┬───────────────────────┬──────────────────────┤
               ▼                       ▼                       ▼                      ▼
          [RECOVERED]          [MANUAL_REVIEW]         [POLICY_BLOCKED]     [CUSTOMER_OPTED_OUT]
```

### Calibrated ML Recovery Model
- **Features Extracted (`MLFeatureVector`):**
  - Order amount in INR.
  - Customer Lifetime Value (LTV), 30-day failure count, 90-day success count.
  - Attempt number, payment method (UPI, Card, Netbanking), failure reason (`bank_timeout`, `insufficient_funds`, `card_expired`, `fraud_rejection`).
  - Time of day / hour of day.
- **Model Classifier:** `XGBoostClassifier` (fallback: `HistGradientBoostingClassifier`).
- **Probability Calibration:** `CalibratedClassifierCV` with **Isotonic Regression** (`calibration_method="isotonic"`).
  - *Why Calibration Matters:* Raw ML model scores can be overconfident. Isotonic calibration aligns model probabilities strictly with empirical historical recovery frequencies ($P(\text{recovery}) \in [0.0, 1.0]$).

### Expected Net Value (ENV) Decision Engine
Evaluates candidate recovery actions: `NO_ACTION`, `RETRY`, `INSTANT_PAYMENT_LINK`, `DISCOUNTED_PAYMENT_LINK_5`, `DISCOUNTED_PAYMENT_LINK_10`, and `MANUAL_REVIEW`.

**Economic Optimization Model:**
For every candidate action $A$, RecoverAI estimates expected recovered value and subtracts gateway fees, communication costs, expected discount costs, and customer-fatigue penalties:

$$\text{ENV}(A) = S \cdot P(A) - C_{\text{gateway}} - C_{\text{comm}} - \left(S \cdot \text{discount} \cdot P(A)\right) - C_{\text{fatigue}}$$

Where:
- $S$ = Order Amount at Risk (INR)
- $P(A)$ = Estimated recovery probability under action $A$

The engine then calculates incremental value relative to the natural baseline:
$$\text{Incremental ENV}(A) = \text{ENV}(A) - \text{ENV}(\text{NO\_ACTION})$$

The engine dispatches action $A^*$ only if $\text{Incremental ENV}(A^*) > 0$, maximizing net merchant profit rather than pursuing recovery at any cost.

### Gateway Route Degradation Protection
RecoverAI monitors each canonical `(gateway, payment_method, bank)` route using a sliding observation window and compares its observed failure rate against a baseline failure rate.

The system computes a one-sided statistical Z-score:
$$Z = \frac{F_{\text{window}} - F_{\text{baseline}}}{\sqrt{\frac{F_{\text{baseline}}(1 - F_{\text{baseline}})}{N}}}$$

**Route Health States:**
- **`NORMAL`:** Standard route operation.
- **`SUSPECTED`:** Failure rate elevated above baseline.
- **`CONFIRMED`:** Route confirmed degraded when sample size $N \ge 20$, $F_{\text{window}} > F_{\text{baseline}}$, and $Z > 2.5$.
- **`RECOVERING`:** Route failure rate returning toward baseline.

When a route is confirmed degraded, direct gateway retries are automatically blocked while payment link recovery options remain available.

### Merchant Safety & Policy Guardrails
Implemented in `PolicyEngine` (`backend/app/recovery/policy.py`):
- **Manual Review Threshold:** Transactions exceeding `manual_approval_threshold` (e.g. ₹25,000) are routed for human review instead of being handled automatically.
- **Discount Ceiling:** Enforces `max_discount_percentage` (e.g. 10.0%), ensuring the system cannot offer a higher discount simply because it might increase recovery.
- **Privacy Enforcement:** If `customer.opt_out == True`, outbound customer messaging is blocked (`CUSTOMER_OPTED_OUT`).
- **Fraud Decline Block:** Hard-blocks recovery interventions on stolen cards or fraud decline reasons (`POLICY_BLOCKED`).

### LLM Customer Communication Agent
- **Providers Supported:** Google Gemini, OpenAI, and a deterministic local Mock Provider (`backend/app/llm/`).
- **Safety Architecture:** LLMs are used strictly for customer messaging and human-readable explanations. Financial parameters (payment amounts, discount percentages, payment URLs, recovery actions) are 100% backend-controlled and deterministic.
- **Defense-in-Depth:** Applies opt-out checks, PII minimization, URL validation, monetary consistency checks, prompt-injection defenses, and channel-specific formatting (WhatsApp / SMS / Email).

### Randomized A/B Evaluation & Revenue Attribution
- **Engine:** `AttributionEngine` (`backend/app/analytics/attribution.py`).
- **Randomized Evaluation:** Deterministic assignment into `TREATMENT` (RecoverAI active policy) vs `CONTROL` (Natural self-recovery / baseline static retry).
- **Estimated Incremental Net Revenue:**
  Estimated by comparing treatment outcomes against the control recovery rate and applying the observed control baseline to the treatment amount-at-risk population:
  $$\text{Estimated Incremental Net Revenue} = \sum_{i \in \text{Treatment}} \text{NetRecovered}_i - \left( \text{RR}_{\text{control}} \times \sum_{i \in \text{Treatment}} \text{AmountAtRisk}_i \right)$$
- **Zero Revenue Overcounting:** Isolates organic self-recoveries from treatment lift calculations.

### Deterministic Simulation Suite & Preset Lab
Includes 7 pre-configured simulation scenarios (`simulation/presets.py`):

| Preset Key | Description | Expected Action | Expected Outcome Status |
| :--- | :--- | :--- | :--- |
| `BANK_TIMEOUT_RECOVERY` | VIP customer, ₹2,500 UPI/HDFC timeout | `DISCOUNTED_PAYMENT_LINK_10` | `RECOVERED` |
| `CONFIRMED_HDFC_DEGRADATION` | HDFC route in confirmed outage state ($Z > 2.5$) | `DISCOUNTED_PAYMENT_LINK_10` | `RECOVERED` |
| `BUDGET_DISCOUNT_RECOVERY` | Price-sensitive budget customer, ₹1,200 failure | `DISCOUNTED_PAYMENT_LINK_10` | `RECOVERED` |
| `HIGH_VALUE_MANUAL_REVIEW` | ₹30,000 transaction exceeding ₹25,000 threshold | `MANUAL_REVIEW` | `MANUAL_REVIEW` |
| `OPTED_OUT_CUSTOMER` | Customer opted out of outbound messages | `NO_ACTION` | `CUSTOMER_OPTED_OUT` |
| `FRAUD_DECLINE_BLOCK` | Stolen card / fraud decline error reason | `NO_ACTION` | `POLICY_BLOCKED` |
| `REFUND_AFTER_RECOVERY` | Recovered payment followed by ₹500 partial refund | `DISCOUNTED_PAYMENT_LINK_10` | `RECOVERED` |

---

## 🗄️ Database Schema & Data Model

Built on PostgreSQL with SQLAlchemy ORM models (`backend/app/models/models.py`):

```text
                       SIMPLIFIED DATABASE RELATIONSHIPS
                       
  ┌────────────┐         ┌───────────────┐         ┌──────────────┐
  │  Customer  │───┐     │ RecoveryCase  │ ───┬───►│ PaymentAttempt│
  └────────────┘   │     └───────┬───────┘    │    └──────────────┘
                   │             │            │    ┌─────────────────────┐
  ┌────────────┐   ├───► ┌───────▼───────┐    ├───►│ GatewayRouteStatus  │
  │   Order    │───┤     │ ModelPrediction│   │    └─────────────────────┘
  └────────────┘   │     └───────┬───────┘    │    ┌─────────────────────┐
                   │             │            ├───►│   PolicyDecision    │
  ┌────────────┐   │     ┌───────▼───────┐    │    └─────────────────────┘
  │  Payment   │───┘     │ AgentDecision │    │    ┌─────────────────────┐
  └────────────┘         └───────┬───────┘    ├───►│   RecoveryAction    │
                                 │            │    └─────────────────────┘
                         ┌───────▼───────┐    │    ┌─────────────────────┐
                         │   Outcome     │◄───┴───►│   AuditLog / Event  │
                         └───────────────┘         └─────────────────────┘
```

- **`RecoveryCase`:** Primary record tracking lifecycle status, amount at risk, timestamps, and customer/order/payment IDs.
- **`PaymentAttempt`:** Log of gateway attempts, error codes, banks, and payment methods.
- **`GatewayRouteStatus`:** Real-time health, failure rates, and $Z$-scores per route (`NORMAL`, `SUSPECTED`, `CONFIRMED`, `RECOVERING`).
- **`ModelPrediction`:** Stores raw and calibrated ML probabilities and feature vector snapshots.
- **`AgentDecision`:** Records selected recovery actions, ENV scores, and diagnosis summaries.
- **`PolicyDecision`:** Logs safety check decisions (`ALLOW`, `BLOCK`, `MANUAL_REVIEW`) and policy reasons.
- **`RecoveryAction`:** Tracks executed recovery interventions and idempotency keys.
- **`Outcome`:** Tracks gross cash collected, refund deductions, net revenue, and attribution status (`DIRECT`, `NATURAL_RECOVERY`).

---

## 📡 REST API Reference

### Executive Dashboard & Analytics
- `GET /api/v1/dashboard/summary` — Returns total recovered revenue, NRR %, recovery rate %, active cases.
- `GET /api/v1/attribution/report` — Returns A/B trial results, conversion lift, p-values, and estimated incremental revenue.
- `GET /api/v1/degradation/routes` — Returns active gateway/bank route degradation metrics and $Z$-scores.

### Case Stream & Decision Audit Timeline
- `GET /api/v1/cases` — Paginated list of recovery cases with status filters, search, and sorting.
- `GET /api/v1/cases/{case_id}` — Detailed metadata for a single recovery case.
- `GET /api/v1/cases/{case_id}/timeline` — Backend-projected decision audit timeline explicitly separating failure ingestion, ML scoring, ENV action selection, policy checks, execution, and attribution.

### Merchant Policy Controls
- `GET /api/v1/policy` — Returns active merchant policy configuration.
- `PUT /api/v1/policy` — Updates policy guardrails (versioned updates with optimistic locking).

### Simulation & Presets
- `POST /api/v1/simulation/run` — Executes a batch synthetic simulation (e.g. 20 cases).
- `GET /api/v1/presets` — Lists available deterministic demo presets.
- `POST /api/v1/presets/run` — Runs a single preset scenario or all presets.
- `POST /api/v1/presets/run_all` — Executes all 7 deterministic preset scenarios.

---

## 🎬 Recommended Demo Flow & Video Link

🎥 **5-Min Pitch Video & Assets:** [Google Drive Folder](https://drive.google.com/drive/folders/1eQ_v0HPAqTuvK785mvbHhTnwRBnxReGu?usp=drive_link)

When demonstrating RecoverAI:
1. **Open Merchant Control Center (`http://localhost:3000`):** Overview of active cases, NRR %, and operational metrics.
2. **Inspect a Failed Payment Case:** Navigate to the Recovery Case Stream and locate a failed transaction (e.g. Case #449).
3. **Open AI Decision Audit:** Click **"View AI Decision"** to inspect the step-by-step decision trace.
4. **Show ML Probability:** Review the calibrated recovery probability output.
5. **Show ENV Action Selection:** Review the candidate action evaluation summary.
6. **Show Safety & Outage Checks:** Verify route health status and policy rule checks.
7. **Show Communication & Outcome:** Review the generated message and revenue attribution.
8. **Inspect Gateway Outage Monitor:** Show route health tracking and degradation handling.
9. **Inspect Policy Guardrails Drawer:** Demonstrate merchant-configured safety boundaries.
10. **Review A/B Attribution:** Show treatment vs. control performance and estimated incremental net revenue.

---

## 🎯 Current Scope & Production Boundaries

RecoverAI is a production-oriented prototype and simulation environment demonstrating the complete revenue recovery lifecycle:

- **What is Built & Functional:** Complete ML calibration pipeline, ENV decision engine, real-time route health monitoring, policy guardrails engine, idempotent execution abstractions, LLM customer communication agent, A/B attribution engine, decision audit timeline, interactive Next.js dashboard, and deterministic test suite.
- **Production Deployment Requirements:** Deploying to live production requires real payment provider API credentials (e.g. live Razorpay/Stripe webhooks), production merchant authentication/SSO, distributed job queues (e.g. Redis/Celery), and enterprise monitoring/compliance infrastructure.

---

## ⚙️ Getting Started & Installation

### Prerequisites
- **Python:** 3.10 or higher
- **Node.js:** 18.x or higher (`npm` included)
- **PostgreSQL:** 14.x or higher running locally on port 5432
- **Virtual Environment:** `venv` or `conda`

### 1. Clone Repository
```bash
git clone https://github.com/your-username/AI_Revenue_Recovery_.git
cd AI_Revenue_Recovery_
```

### 2. Environment Configuration
Create a `.env` file in the root directory:
```env
DATABASE_URL=postgresql://localhost:5432/ai_revenue_recovery
ENVIRONMENT=development
SECRET_KEY=super-secret-development-key
API_V1_STR=/api/v1
DEFAULT_MERCHANT_ID=1

# Optional: Google Gemini API Key or OpenAI Key
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Backend Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Database Setup & Migrations
```bash
createdb ai_revenue_recovery || true
alembic upgrade head
```

### 5. Frontend Setup
```bash
cd frontend
npm install
cd ..
```

---

## 🚀 Running the Application

### Using Development Launch Script
```bash
chmod +x run_dev.sh
./run_dev.sh
```

### Using Makefile
```bash
# Terminal 1: Backend FastAPI Server (http://localhost:8000)
make dev

# Terminal 2: Frontend Next.js Control Center (http://localhost:3000)
make frontend
```

Navigate to **`http://localhost:3000`** in your browser.

---

## 🧪 Testing & Quality Assurance

```bash
# Run complete test suite via wrapper script
chmod +x run_tests.sh
./run_tests.sh

# Or run specific module tests directly
pytest backend/tests/test_webhook_ingestion.py
pytest backend/tests/test_state_machine.py
pytest backend/tests/test_attribution.py
pytest backend/tests/test_route_health.py
pytest backend/tests/test_preset_runner.py
```

---

## 📁 Project Directory Structure

```text
AI_Revenue_Recovery_/
├── backend/
│   ├── alembic/                      # Database migration scripts
│   ├── app/
│   │   ├── analytics/                # A/B trial attribution & lift calculation
│   │   ├── api/v1/                   # FastAPI REST API endpoints
│   │   ├── communication/            # Customer communication & LLM agents
│   │   ├── core/                     # Core settings & database configuration
│   │   ├── experiments/              # Causal experiment assignment & baselines
│   │   ├── llm/                      # Gemini, OpenAI, & Mock LLM providers
│   │   ├── ml/                       # XGBoost model, isotonic calibration, preprocessor
│   │   ├── models/                   # SQLAlchemy database models & enums
│   │   ├── recovery/                 # Case manager, state machine, ENV engine, policy
│   │   ├── risk/                     # Risk gate & route health outage monitor
│   │   ├── schemas/                  # Pydantic request/response schemas
│   │   ├── webhooks/                 # HMAC verification & webhook handlers
│   │   └── main.py                   # FastAPI app initialization
│   └── tests/                        # Pytest suite
├── frontend/
│   ├── app/                          # Next.js 14 app router & components
│   ├── public/                       # Static UI assets
│   └── package.json                  # Frontend dependencies
├── ml/                               # ML training data & training scripts
├── simulation/                       # Synthetic simulation engine & 7 presets
├── Makefile                          # Dev commands (make dev, make frontend)
├── run_dev.sh                        # Development launch script
├── run_tests.sh                      # Test execution wrapper
├── requirements.txt                  # Python dependencies
└── README.md                         # Project documentation
```

---

## 📄 License & Acknowledgments

This project is open-source software licensed under the **[MIT License](LICENSE)**.
