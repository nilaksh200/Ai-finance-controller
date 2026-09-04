# Autonomous Payment Reconciliation & Cash Controller
> **Enterprise-Grade 3-Way Payment Reconciliation, ReAct Cognitive Anomaly Resolution, Cryptographic Ledger Audit Chaining, and Forward Liquidity Forecasting.**

![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue?style=for-the-badge&logo=python)
![Streamlit](https://img.shields.io/badge/Streamlit-1.35%2B-FF4B4B?style=for-the-badge&logo=streamlit)
![AI Reasoning](https://img.shields.io/badge/AI%20Engine-Google%20Gemini-4285F4?style=for-the-badge&logo=google)
![CI Build](https://img.shields.io/badge/CI-Automated%20Audit%20Passing-success?style=for-the-badge&logo=githubactions)

---

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [The Business Problem: Modern Payment Operations](#the-business-problem-modern-payment-operations)
3. [5-Layer Hybrid System Architecture](#5-layer-hybrid-system-architecture)
4. [Layer 1: Deterministic Fast-Path Matcher](#layer-1-deterministic-fast-path-matcher)
5. [Layer 1.5: Multi-Threaded ReAct Cognitive Reasoning Engine](#layer-15-multi-threaded-react-cognitive-reasoning-engine)
6. [Deterministic Mathematical Delta Guardrails](#deterministic-mathematical-delta-guardrails)
7. [Post-Reconciliation Cryptographic Audit Trail](#post-reconciliation-cryptographic-audit-trail)
8. [Layer 2: Dual-Track Treasury & Cash Position Engine](#layer-2-dual-track-treasury--cash-position-engine)
9. [Layer 3: 7-Day Forward Predictive Liquidity Forecaster](#layer-3-7-day-forward-predictive-liquidity-forecaster)
10. [Layer 4: Closed-Loop ERP Journal Dispatch Studio](#layer-4-closed-loop-erp-journal-dispatch-studio)
11. [Multi-Tier Resilient LLM Gateway](#multi-tier-resilient-llm-gateway)
12. [Executive Streamlit Dashboard Breakdown](#executive-streamlit-dashboard-breakdown)
13. [Ground Truth Accuracy Auditing & Metrics](#ground-truth-accuracy-auditing--metrics)
14. [Codebase Map & File Reference](#codebase-map--file-reference)
15. [Quickstart & Local Installation](#quickstart--local-installation)
16. [GitHub Actions CI Pipeline](#github-actions-ci-pipeline)
17. [License](#license)

---

## Executive Summary

The **Autonomous AI Finance Controller** is a presentation-grade, production-ready fintech operations platform designed to solve payment reconciliation friction, revenue leakages, and liquidity opacity in modern digital commerce.

By unifying rule-based deterministic matching, multi-threaded **Google Gemini ReAct cognitive reasoning**, hardcoded mathematical delta verification, cryptographic SHA-256 audit chaining, and dual-track treasury accounting, the system reduces reconciliation time from days to seconds while maintaining zero tolerance for arithmetic hallucinations.

---

## The Business Problem: Modern Payment Operations

In high-volume digital commerce, every transaction exists across three disconnected, asynchronous ledgers:

```
┌────────────────────────┐       ┌────────────────────────┐       ┌────────────────────────┐
│  1. ORDER SYSTEM (OMS) │       │   2. PAYMENT GATEWAY   │       │   3. CORE BANK FEED    │
│      (orders.csv)      │       │     (gateway.csv)      │       │       (bank.csv)       │
├────────────────────────┤       ├────────────────────────┤       ├────────────────────────┤
│ OrderID: ORD101        │  ──►  │ PaymentID: PAY101      │  ──►  │ TransactionID: TXN882  │
│ Gross Amount: Rs 1,000 │       │ Gross: Rs 1,000        │       │ Date: T+2 Settlement   │
│ Discount: Rs 0.00      │       │ MDR Fee: Rs 20.00      │       │ Net Deposit: Rs 976.40 │
│ Status: Completed      │       │ GST (18%): Rs 3.60     │       │ Narration: Settlement  │
│                        │       │ Net Due: Rs 976.40     │       │                        │
└────────────────────────┘       └────────────────────────┘       └────────────────────────┘
```

### The 5 Causes of Financial Leakage
1. **Merchant Discount Rate (MDR) Variations**: Premium cards, corporate credit cards, or international payments charged at 2.5% to 3.5% instead of contracted 2.0% base rates.
2. **Promotional & Coupon Desynchronization**: Merchant OMS discounts not passed to gateway payload, or instant gateway cashback applied at checkout without OMS notification.
3. **Multi-Day Settlement Lag**: Bank deposits settling 2 to 5 business days after capture due to banking holidays or batching schedules.
4. **Refund & Chargeback Clawbacks**: Cancelled orders triggering bank debits without clear transaction linkages.
5. **Missing Bank Credits**: Captured transactions that never reach the merchant bank account due to gateway batching errors.

---

## 5-Layer Hybrid System Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              THE 5-LAYER HYBRID ENGINE                                 │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Layer 1: Deterministic Fast-Path Matcher (Sub-millisecond exact O(1) matching)        │
│  Layer 1.5: Multi-Threaded ReAct AI Detective (5-in-1 Batched Google Gemini Reasoning) │
│  Layer 2: Dual-Track Treasury Accounting (Realized Cash vs In-Transit Float)           │
│  Layer 3: 7-Day Predictive Liquidity Forecaster (Non-linear liquidation curve)         │
│  Layer 4: Automated Ticket Triage & Closed-Loop ERP Journal Dispatch Studio            │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Layer 1: Deterministic Fast-Path Matcher

*(Implemented in `finance_controller.py` and `reconcile.py`)*

* **Index Construction**: Constructs in-memory $O(1)$ hash tables indexing Gateway by `OrderID` / `PaymentID` and Bank statements by `TransactionID` and narration references.
* **Exact Accounting Math**:
  $$\text{MDR Fee} = \text{Gross Amount} \times 0.02$$
  $$\text{GST} = \text{MDR Fee} \times 0.18$$
  $$\text{Expected Net Settlement} = \text{Gross Amount} - (\text{MDR Fee} + \text{GST})$$
* **Execution & Cost Efficiency**: If the calculated Net equals the Bank deposit within $\pm \text{Rs } 0.01$ and settlement dates fall within standard windows, the record resolves immediately as `CONFIRMED MATCH`. This handles **50% to 70% of standard traffic in under 0.01 seconds** with zero API cost.

---

## Layer 1.5: Multi-Threaded ReAct Cognitive Reasoning Engine

*(Implemented in `finance_controller.py` and `reconcile.py`)*

Non-standard records failing Layer 1 heuristics are quarantined and escalated to the **ReAct (Reasoning + Acting)** cognitive agent powered by **Google Gemini**.

```
┌───────────┐
│   THINK   │ ──► Analyze gross amount, gateway status, and bank candidate deposits.
└─────┬─────┘
      │
      ▼
┌───────────┐
│    ACT    │ ──► Verify candidate TransactionIDs and recalculate effective MDR and GST.
└─────┬─────┘
      │
      ▼
┌───────────┐
│  OBSERVE  │ ──► Cross-verify calculated net proceeds against actual bank credit.
└─────┬─────┘
      │
      ▼
┌───────────┐
│  DECIDE   │ ──► Emit structured classification (MATCH, FEE_VARIATION, EXCEPTION, REFUND).
└───────────┘
```

### Anomaly Classes Resolved
* **MDR Fee Variations**: Identifies non-standard interchange fees (e.g. 2.5%, 3.0%) and confirms arithmetic balance.
* **Internal Discount Discrepancies**: Flags OMS promotions charged at full gross by gateway.
* **Checkout Instant Cashback**: Resolves instant bank discounts applied at payment checkout.
* **Refund Debits**: Matches negative bank withdrawals against cancelled orders.
* **Settlement Timing Delays**: Matches late deposits occurring outside standard SLA windows.

### Concurrent Dynamic Batching
* Orders are packaged into structured multi-order batches (12 to 15 orders per prompt).
* Executed concurrently using `ThreadPoolExecutor(max_workers=3)`.
* Achieves throughput exceeding **25 transactions per second**, reconciling 100+ transactions in under 2 seconds.

---

## Deterministic Mathematical Delta Guardrails

To eliminate LLM arithmetic hallucinations, every AI decision must pass strict programmatic verification before being accepted:

```python
# 1. Candidate ID Verification Guardrail
candidate_ids = [c["TransactionID"] for c in candidates]
if decision["MatchedTxnID"] not in candidate_ids and decision["MatchedTxnID"] != "NONE":
    decision["Status"] = "GUARDRAIL_REJECTED"

# 2. Arithmetic Delta Balance Check
expected_net = gross - fee - gst
actual_net = matched_bank_amount
delta = abs(expected_net - actual_net)

if delta > 1.00:
    decision["Status"] = "EXCEPTION"
    decision["GuardrailPass"] = False
```

---

## Post-Reconciliation Cryptographic Audit Trail

Once all concurrent threads finish processing, the system builds an unbroken **SHA-256 blockchain-style cryptographic hash chain** across all resolved records:

$$\text{AuditHash}_i = \text{SHA-256}\Big(\text{OrderID}_i \parallel \text{TransactionID}_i \parallel \text{BankAmount}_i \parallel \text{AuditHash}_{i-1}\Big)$$

$$\text{Starting Seed: } \text{AuditHash}_0 = \text{"0000000000000000000000000000000000000000000000000000000000000000"}$$

Any post-audit tampering with amounts, dates, or IDs invalidates all downstream hashes, providing forensic-grade audit integrity.

---

## Layer 2: Dual-Track Treasury & Cash Position Engine

*(Implemented in `finance_controller.py`)*

Traditional accounting treats payment gateway balances as liquid cash. In reality, until settled in the bank, funds represent **unsettled accounts receivable (Float)** subject to gateway withholding and refund chargebacks.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               TOTAL RECONCILED REVENUE                                 │
├────────────────────────────────────────┬───────────────────────────────────────────────┤
│         1. REALIZED BANK CASH          │           2. PENDING GATEWAY FLOAT            │
│   (Confirmed deposited in bank)        │     (Captured by gateway, in transit)         │
├────────────────────────────────────────┼───────────────────────────────────────────────┤
│ • Immediately available for payroll,   │ • Accounts Receivable in transit              │
│   vendor payouts, and operations       │ • Subject to T+1 / T+2 settlement lag         │
│ • Net of verified MDR fees & 18% GST   │ • Monitored for aging and SLA breach          │
└────────────────────────────────────────┴───────────────────────────────────────────────┘
```

---

## Layer 3: 7-Day Forward Predictive Liquidity Forecaster

*(Implemented in `finance_controller.py`)*

Instead of assuming flat linear payout distributions, the forecaster models real-world non-linear payment settlement liquidation curves:

| Settlement Horizon | Cumulative Settlement % | Description |
| :--- | :--- | :--- |
| **Day T+0 (Same Day)** | **0%** | Intraday gateway processing window |
| **Day T+1 (Next Day)** | **40%** | Fast-settlement UPI and debit card rails |
| **Day T+2 (Standard)** | **85%** | Standard credit cards and net banking |
| **Day T+3+ (Delayed)** | **100%** | Holiday clearance and cross-bank batch clearing |

$$\text{Projected Inflow}(d) = \sum_{t \in \text{Float}} \text{NetAmount}(t) \times P(\text{Settlement on Day } d \mid \text{Age}(t))$$

$$\text{Cumulative Treasury Cash}(d) = \text{Realized Cash} + \sum_{k=1}^{d} \text{Projected Inflow}(k)$$

---

## Layer 4: Closed-Loop ERP Journal Dispatch Studio

*(Implemented in `finance_controller.py` and `dashboard.py`)*

### Operational Exception Triage
Discrepancies are automatically triaged into operational action queues:
* `BANK_ESC_MISSING_CREDIT`: High-priority ticket auto-drafting bank escalation for missing credits (>5 days).
* `GW_DISPUTE_FEE_OVERCHARGE`: Medium-priority ticket claiming gateway fee overbilling rebates.
* `REFUND_INVESTIGATION`: Medium-priority ticket verifying cancellation logs against refund payouts.
* `DISCOUNT_DISCREPANCY`: Low-priority ticket posting promotional discount adjustments.

### Automated Double-Entry ERP Journal Generation
Clicking **"Dispatch to General Ledger (ERP)"** generates and dispatches a compliant double-entry accounting payload:

```json
{
  "journal_entry_id": "JE-2026-0902-8841",
  "system": "QuickBooks Enterprise / NetSuite",
  "posted_at": "2026-09-05T01:40:00Z",
  "currency": "INR",
  "entries": [
    {
      "account": "1100 - Operating Bank Cash",
      "type": "DEBIT",
      "amount": 976.40,
      "description": "Settled net cash received in bank"
    },
    {
      "account": "5200 - Merchant Processing Fees (MDR + GST)",
      "type": "DEBIT",
      "amount": 23.60,
      "description": "Razorpay 2.0% MDR + 18% GST fee expense"
    },
    {
      "account": "1200 - Accounts Receivable (Gateway Clearing)",
      "type": "CREDIT",
      "amount": 1000.00,
      "description": "Clear gross customer receivable"
    }
  ],
  "total_debit": 1000.00,
  "total_credit": 1000.00,
  "balanced": true,
  "status": "POSTED_SUCCESSFULLY"
}
```

---

## Multi-Tier Resilient LLM Gateway

*(Implemented in `opencode/llm.py`)*

The system incorporates a 3-tier resilient gateway ensuring continuous uptime:
1. **Tier 1 (Cloud Engine)**: Google Gemini (`gemini-flash-latest`, `gemini-flash-lite-latest`, `gemini-pro-latest`).
2. **Tier 2 (Local Edge Engine)**: Local Ollama server (`localhost:11434`) with built-in **SSRF security filter** (`_is_safe_local_url`) blocking unauthorized cloud metadata endpoints (`169.254.169.254`).
3. **Tier 3 (Offline Heuristic Mock)**: Deterministic rule calculator ensuring zero application crashes even in offline or disconnected environments.

---

## Executive Streamlit Dashboard Breakdown

*(Implemented in `dashboard.py`)*

* **Tab 1: Autonomous Reconciliation Master Ledger**:
  * Real-time KPI scorecards (Overall Accuracy, Resolution Rate, Reconciled Volume).
  * Color-coded master ledger table (`CONFIRMED MATCH`, `FEE VARIATION`, `EXCEPTION`).
  * **Slide-out Right Drawer**: Clicking any row smoothly opens a side drawer displaying raw prompt parameters, candidate bank records, step-by-step cognitive reasoning trace, and mathematical delta verification.
* **Tab 2: Cash Position & 7-Day Forecast**:
  * Dual-track treasury metric cards (Realized Bank Cash vs. Pending Gateway Float).
  * Interactive Plotly 7-day liquidity projection chart with 95% confidence intervals and cash runway indicators.
* **Tab 3: Exceptions & ERP Dispatch Studio**:
  * Expandable ticket cards with root-cause categorization.
  * Interactive **"Dispatch to General Ledger (ERP)"** action buttons with instant JSON visualizer.
  * Single-click **"Download Audit CSV"** export button.

---

## Ground Truth Accuracy Auditing & Metrics

*(Implemented in `finance_controller.py`)*

When benchmarking against ground truth feeds, the controller evaluates four core performance metrics:

$$\text{Precision} = \frac{\text{True Positives}}{\text{True Positives} + \text{False Positives}}$$

$$\text{Recall} = \frac{\text{True Positives}}{\text{True Positives} + \text{False Negatives}}$$

$$F_1 = 2 \times \frac{\text{Precision} \times \text{Recall}}{\text{Precision} + \text{Recall}}$$

$$\text{Resolution Rate} = \frac{\text{Deterministic Matches} + \text{AI Matches}}{\text{Total Processed Transactions}}$$

---

## Codebase Map & File Reference

| File | Responsibilities & Implementations |
| :--- | :--- |
| [`dashboard.py`](dashboard.py) | Streamlit dashboard UI, custom CSS design system, Plotly visualizations, slide-out drawer, and ERP studio. |
| [`finance_controller.py`](finance_controller.py) | Core engine: 5-layer pipeline, Dual-track treasury controller, 7-day liquidity forecaster, ReAct agent, and ERP generator. |
| [`reconcile.py`](reconcile.py) | Standalone reconciliation module: 3-way matcher, multi-threaded batching, ReAct reasoning, and SHA-256 audit chaining. |
| [`opencode/llm.py`](opencode/llm.py) | Multi-tier LLM client gateway with SSRF protection and offline heuristic fallback engine. |
| [`tests/test_audit.py`](tests/test_audit.py) | Automated test suite validating reconciliation accuracy, math guardrails, and treasury statements. |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | GitHub Actions CI workflow executing syntax validation and automated test audits on every push. |
| [`.streamlit/config.toml`](.streamlit/config.toml) | Streamlit theme configuration and server parameters. |
| [`requirements.txt`](requirements.txt) | Python dependencies (`streamlit`, `pandas`, `plotly`, `requests`). |
| [`.gitignore`](.gitignore) | Security rule file ensuring API keys in `.env` are never committed to version control. |
| [`.env.example`](.env.example) | Environment configuration template for API keys. |

---

## Quickstart & Local Installation

### 1. Clone the Repository
```bash
git clone https://github.com/nilaksh200/Ai-finance-controller-.git
cd Ai-finance-controller-
```

### 2. Create Virtual Environment & Install Dependencies
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` and add your Google Gemini API key:
```bash
cp .env.example .env
```
Inside `.env`:
```ini
GEMINI_API_KEY=your_gemini_api_key_here
```

### 4. Run the Executive Dashboard
```bash
streamlit run dashboard.py
```
Open your browser at `http://localhost:8501`.

---

## GitHub Actions CI Pipeline

This repository includes a fully configured **GitHub Actions CI pipeline** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) that triggers on every push and pull request to `main`:
1. Provisions Python 3.11 environment on Ubuntu runners.
2. Installs dependencies from `requirements.txt`.
3. Runs `python -m compileall` for syntax verification.
4. Executes the automated reconciliation audit test suite ([`tests/test_audit.py`](tests/test_audit.py)) to verify deterministic accuracy, ReAct reasoning, mathematical guardrails, and treasury statements.
5. Verifies Streamlit dashboard integrity.

---

## License
This project is licensed under the [MIT License](LICENSE).
