# ⚡ Autonomous Payment Reconciliation & Cash Controller
> **Enterprise-Grade 3-Way Payment Reconciliation, ReAct Cognitive Anomaly Resolution, Cryptographic Ledger Audit Chaining, and Forward Liquidity Forecasting.**

![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue?style=for-the-badge&logo=python)
![Streamlit](https://img.shields.io/badge/Streamlit-1.35%2B-FF4B4B?style=for-the-badge&logo=streamlit)
![AI Reasoning](https://img.shields.io/badge/AI%20Engine-Google%20Gemini-4285F4?style=for-the-badge&logo=google)
![CI Build](https://img.shields.io/badge/CI-Automated%20Audit%20Passing-success?style=for-the-badge&logo=githubactions)

---

## 🏬 Executive Summary

Modern high-volume digital commerce suffers from **2–4% annual financial leakage** due to payment gateway fee variations, unapplied promotional discounts, settlement timing delays ($T+1$ to $T+3$), and unverified refunds. Manual reconciliation in spreadsheets is slow, error-prone, and incapable of providing real-time cash visibility.

The **Autonomous AI Finance Controller** provides a presentation-grade, production-ready solution that combines:
1. **Layer 1: Deterministic Fast-Path Matching** ($<0.01\text{s}$ execution for 50–70% of standard traffic).
2. **Layer 1.5: Multi-Threaded ReAct Cognitive Agents** powered by **Google Gemini** for resolving complex payment anomalies.
3. **Deterministic Mathematical Guardrails** ($|\Delta| \le ₹1.00$) preventing AI arithmetic hallucinations.
4. **Post-Reconciliation Cryptographic Audit Chaining** (tamper-proof SHA-256 blockchain-style hash chain).
5. **Dual-Track Treasury Accounting** (Realized Bank Cash vs. Pending Gateway Float).
6. **7-Day Predictive Liquidity Forecaster** (non-linear settlement liquidation curve modeling).
7. **Closed-Loop ERP Journal Dispatch Studio** (one-click double-entry balanced JSON posting to QuickBooks / NetSuite).

---

## 🏗️ 5-Layer Hybrid Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              THE 5-LAYER HYBRID ENGINE                                 │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Layer 1: Deterministic Fast-Path Matcher (Exact matching in <0.01s)                  │
│  Layer 1.5: Multi-Threaded 5-in-1 Batched ReAct AI Detective (Google Gemini)          │
│  Layer 2: Dual-Track Treasury & Realized vs Float Split                                │
│  Layer 3: 7-Day Non-Linear Predictive Liquidity Forecaster                             │
│  Layer 4: Automated Ticket Triage & Closed-Loop ERP Journal Dispatch                   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🖥️ Executive Dashboard Preview

The application features a 3-tab interactive fintech controller dashboard matching top industry standards (Numeric, Nominal, Osfin.ai, Razorpay):

* **Tab 1: Autonomous Reconciliation Master Ledger**: Live status badges (`CONFIRMED MATCH`, `FEE VARIATION`, `EXCEPTION`), transaction filtering, and a **Slide-out Cognitive Inspector Drawer** to view step-by-step AI thought chains (**THINK $\rightarrow$ ACT $\rightarrow$ OBSERVE $\rightarrow$ DECIDE**) and mathematical delta checks.
* **Tab 2: Cash Position & 7-Day Forecast**: Dual-track split of Realized Bank Cash vs. Pending Float with interactive Plotly liquidity forecast charts.
* **Tab 3: Exceptions & ERP Dispatch Studio**: Operational ticket queue with one-click **"Dispatch to General Ledger (ERP)"** buttons, live double-entry JSON payload visualizer, and single-click CSV audit report exports.

---

## 🚀 Quickstart & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/nilaksh200/Ai-finance-controller-.git
cd Ai-finance-controller-
```

### 2. Set Up Virtual Environment & Dependencies
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

### 4. Launch the Executive Dashboard
```bash
streamlit run dashboard.py
```
Open your browser at `http://localhost:8501`.

---

## 📂 Codebase Structure

| File | Purpose |
| :--- | :--- |
| [`dashboard.py`](dashboard.py) | Streamlit dashboard, custom CSS design system, Plotly charts, ReAct drawer, and ERP studio. |
| [`finance_controller.py`](finance_controller.py) | Dual-track treasury controller, 7-day cash forecaster, exception triage, and ERP JSON generator. |
| [`reconcile.py`](reconcile.py) | 3-way reconciliation engine, multi-threaded batching, ReAct reasoning, and SHA-256 audit chaining. |
| [`opencode/llm.py`](opencode/llm.py) | Multi-tier resilient LLM gateway with SSRF-safe local Ollama execution and deterministic fallback mock. |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | GitHub Actions continuous integration workflow running automated audits on every push. |
| [`requirements.txt`](requirements.txt) | Environment dependencies (Streamlit, Pandas, Plotly, Requests). |

---

## 🔄 GitHub Actions CI & Continuous Deployment

This repository uses **GitHub Actions** (`.github/workflows/ci.yml`) to automatically validate every push and pull request:
- Compiles Python code and checks syntax.
- Runs synthetic 3-way data generation and executes the autonomous reconciliation audit.
- Verifies mathematical guardrail tolerances ($|\Delta| \le ₹1.00$) and confirms $F_1 \ge 0.85$.
- Verifies Streamlit dashboard integrity.

---

## 🛡️ License
Licensed under the [MIT License](LICENSE).
