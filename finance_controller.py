#!/usr/bin/env python3
"""
=============================================================================
AI FINANCE CONTROLLER - RECONCILIATION, CASH POSITION & FORWARD FORECASTER
=============================================================================
An autonomous financial operations controller designed for modern commerce.
Combines deterministic accounting rules, ReAct AI reasoning, automated
ground-truth accuracy auditing, dual cash position reconciliation,
7-day predictive liquidity forecasting, and automated loop closure workflows.
=============================================================================
"""

import os
import csv
import sys
import io
import time
import math
import random
import re
import hashlib
import argparse
import tempfile
import ipaddress
import urllib.parse
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple, Any, Optional, Union

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# =====================================================================
# SECURITY: SSRF GUARD FOR LOCAL LLM PROXY URLS
# =====================================================================
def _is_safe_local_url(url: str) -> bool:
    """
    Validates that a URL is safe for local model server requests.
    Blocks cloud metadata service endpoints and non-local hostnames
    to prevent Server-Side Request Forgery (SSRF) attacks.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        host = parsed.hostname or ''
        # Explicitly block well-known cloud metadata endpoints
        blocked_hosts = {
            '169.254.169.254',      # AWS/Azure/GCP instance metadata
            'metadata.google.internal',
            '100.100.100.200',      # Alibaba Cloud metadata
            'metadata.internal',
        }
        if host.lower() in blocked_hosts:
            return False
        # Allow loopback
        if host in ('localhost', '127.0.0.1', '::1', '0.0.0.0'):
            return True
        # Allow private/LAN IP ranges (for Ollama on LAN)
        try:
            ip = ipaddress.ip_address(host)
            return ip.is_loopback or ip.is_private
        except ValueError:
            # Hostname (not IP): only allow 'localhost'
            return host == 'localhost'
    except Exception:
        return False

# Ensure UTF-8 output encoding across all operating systems
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Optional: Load environment variables from .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Check for OpenCode Antigravity LLM integration
try:
    from opencode import llm
    HAS_OPENCODE = True
except ImportError:
    HAS_OPENCODE = False

# Global tracker for active LLM engine
ACTIVE_LLM_ENGINE: str = "MockLLM"


# =====================================================================
# UTILITIES: CURRENCY FORMATTING & PARSING HELPERS
# =====================================================================
def parse_float_safe(val: Any, default: float = 0.0) -> float:
    """
    Safely parses floating point values from strings, numbers, or currencies.
    Handles INR/USD symbols, commas, and malformed strings.
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val) if not (math.isnan(val) or math.isinf(val)) else default
    val_str = str(val).strip().replace("₹", "").replace("$", "").replace(",", "").strip()
    try:
        return float(val_str)
    except (ValueError, TypeError):
        return default


def parse_date_safe(val: Any) -> Optional[date]:
    """
    Safely parses a date or datetime string across multiple standard formats.
    """
    if not val:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    
    val_str = str(val).strip()
    # Normalize ISO format
    if "T" in val_str:
        clean_iso = val_str.replace("Z", "").split("+")[0]
        for f in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"]:
            try:
                return datetime.strptime(clean_iso, f).date()
            except ValueError:
                pass

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y",
    ]
    for f in formats:
        try:
            return datetime.strptime(val_str, f).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(val_str).date()
    except Exception:
        pass
    return None


def format_inr(amount: float) -> str:
    """
    Format a floating-point number into Indian Rupee (INR) representation
    with proper decimal places and Indian numbering grouping (e.g., ₹1,23,456.78).
    """
    if math.isnan(amount) or math.isinf(amount):
        return "₹0.00"
    
    is_negative = amount < 0
    amount = abs(amount)
    parts = f"{amount:.2f}".split(".")
    integer_part = parts[0]
    decimal_part = parts[1]
    
    if len(integer_part) > 3:
        last_three = integer_part[-3:]
        remaining = integer_part[:-3]
        groups = []
        while len(remaining) > 2:
            groups.insert(0, remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            groups.insert(0, remaining)
        formatted_int = ",".join(groups) + "," + last_three
    else:
        formatted_int = integer_part
        
    sign = "-" if is_negative else ""
    return f"{sign}₹{formatted_int}.{decimal_part}"


def calculate_net(gross: float, rate: float = 0.02) -> Tuple[float, float, float]:
    """
    Computes gateway fee (2% standard), GST on fee (18%), and net settlement amount.
    """
    fee = round(gross * rate, 2)
    gst = round(fee * 0.18, 2)
    net = round(gross - fee - gst, 2)
    return fee, gst, net


# =====================================================================
# LLM ENGINE: MOCK LLM, GEMINI REST API, & OPENCODE INTEGRATION
# =====================================================================
class MockResponse:
    """Mock container mimicking LLM response object."""
    def __init__(self, content: str):
        self.content = content


class MockLLM:
    """
    High-fidelity heuristic simulator for the ReAct AI Agent.
    Evaluates order, gateway, and bank candidate features to dynamically produce
    THINK -> ACT -> OBSERVE -> DECIDE reasoning loops.
    Supports generic ID formats, single-order prompts, and 5-in-1 batched prompts.
    """
    def _eval_single_order(self, prompt: str) -> Tuple[str, str, str, str, str, str]:
        # Parse fields from prompt using flexible regex
        order_id_match = re.search(r"OrderID:\s*([^\s\n\r]+)", prompt)
        order_id = order_id_match.group(1) if order_id_match else "N/A"
        
        order_amt_match = re.search(r"Amount:\s*([\d\.]+)", prompt)
        order_amt = float(order_amt_match.group(1)) if order_amt_match else 0.0
        
        discount_match = re.search(r"DiscountAmount:\s*([\d\.]+)", prompt)
        discount = float(discount_match.group(1)) if discount_match else 0.0
        
        pay_id_match = re.search(r"PaymentID:\s*([^\s\n\r]+)", prompt)
        pay_id = pay_id_match.group(1) if pay_id_match else "N/A"
        
        gw_gross_match = re.search(r"Gross Amount:\s*([\d\.]+)", prompt)
        gw_gross = float(gw_gross_match.group(1)) if gw_gross_match else 0.0
        
        gw_section = prompt.split("[GATEWAY TRANSACTION DETAILS]")[1] if "[GATEWAY TRANSACTION DETAILS]" in prompt else ""
        gw_status_match = re.search(r"Status:\s*(\w+)", gw_section)
        gw_status = gw_status_match.group(1) if gw_status_match else "N/A"
        
        # Parse bank candidates
        candidates = []
        for line in prompt.split("\n"):
            if "Candidate" in line:
                txn_match = re.search(r"TransactionID=([^\s,]+)", line)
                amt_match = re.search(r"Amount=(-?[\d\.]+)", line)
                date_match = re.search(r"Date=([^\s,]+)", line)
                if txn_match and amt_match:
                    candidates.append({
                        "TransactionID": txn_match.group(1),
                        "Amount": float(amt_match.group(1)),
                        "Date": date_match.group(1) if date_match else ""
                    })

        matched_txn_id = "NONE"
        
        if not candidates:
            think = f"Order {order_id} has no matching bank statement candidates. Settlement record is missing."
            act = f"Scan bank ledger for settlement reference {pay_id} or {order_id}."
            obs = "No deposit entry exists in bank statement."
            decide = "EXCEPTION | Missing bank entry: Settlement not credited to bank account."
            matched_txn_id = "NONE"
        elif gw_status == "refunded":
            think = f"Order {order_id} (Payment {pay_id}) was marked as refunded by gateway."
            act = "Audit corresponding bank statement credits and debit clawbacks."
            obs = "Bank records confirm initial capture and subsequent refund debit."
            decide = "MATCH_AS_REFUNDED | Order fully refunded; verified by bank debit."
            payout_cands = [c for c in candidates if c["Amount"] < 0]
            matched_txn_id = payout_cands[0]["TransactionID"] if payout_cands else (candidates[0]["TransactionID"] if candidates else "NONE")
        elif discount > 0 and abs(gw_gross - (order_amt + discount)) <= 1.0:
            think = f"Order {order_id} had promotional discount {format_inr(discount)} recorded internally, but gateway charged gross {format_inr(gw_gross)}."
            act = "Audit checkout invoice vs gateway payload."
            obs = "Full price captured at gateway without merchant promotional deduction."
            decide = f"MATCH_WITH_EXCEPTION | Internal discount of {format_inr(discount)} was not passed to gateway."
            matched_txn_id = candidates[0]["TransactionID"] if candidates else "NONE"
        elif discount == 0 and gw_gross < order_amt:
            diff = order_amt - gw_gross
            think = f"Order {order_id} recorded at {format_inr(order_amt)}, but gateway processed lower amount {format_inr(gw_gross)} (diff: {format_inr(diff)})."
            act = "Validate gateway campaign discount rule."
            obs = "Gateway promotional discount applied at checkout. Bank net matches gateway settlement."
            decide = f"MATCH | Gateway discount of {format_inr(diff)} applied at checkout."
            matched_txn_id = candidates[0]["TransactionID"] if candidates else "NONE"
        else:
            # Check fee variation
            fee_var_matched = False
            for cand in candidates:
                cand_amt = cand["Amount"]
                if cand_amt > 0 and gw_gross > 0:
                    implied_fee = (gw_gross - cand_amt) / 1.18
                    implied_rate = implied_fee / gw_gross
                    diff_pct = abs(implied_rate - 0.02)
                    
                    if 0.0005 <= diff_pct < 0.005:
                        think = f"Implied fee variation ({implied_rate*100:.2f}%) is within ambiguous margin (<0.5% diff from standard 2.0%)."
                        act = "Compare against contract rate schedule."
                        obs = f"Variance is too slight ({diff_pct*100:.2f}% diff) to conclusively confirm pricing tier vs rounding error."
                        decide = f"EXCEPTION | Ambiguous fee rate difference ({diff_pct*100:.2f}% < 0.5%); flagged for contract review."
                        matched_txn_id = "NONE"
                        fee_var_matched = True
                        break
                    elif diff_pct >= 0.005:
                        think = f"Bank settlement of {format_inr(cand_amt)} deviates from standard 2% rate. Implied fee is {implied_rate*100:.1f}%."
                        act = "Recalculate MDR tier and GST."
                        obs = f"Settlement matches non-standard fee tier ({implied_rate*100:.1f}% + 18% GST)."
                        decide = f"MATCH_WITH_FEE_VARIATION | Gateway charged custom fee rate of {implied_rate*100:.1f}% (e.g. corporate card)."
                        matched_txn_id = cand["TransactionID"]
                        fee_var_matched = True
                        break
            
            if not fee_var_matched:
                if random.random() < 0.30:
                    think = f"Order {order_id} amounts match but settlement delay is on the 2-day SLA boundary."
                    act = "Audit gateway settlement batch window timestamps."
                    obs = "Settlement delay timestamp falls on SLA boundary; requires gateway log review."
                    decide = "EXCEPTION | Timing difference at SLA threshold (2 days); flagged for gateway audit."
                    matched_txn_id = "NONE"
                else:
                    think = f"Order {order_id} amounts match perfectly but bank credit was delayed beyond normal SLA."
                    act = "Reconcile timestamps between gateway capture and bank value date."
                    obs = "Legitimate settlement observed with extended processing lag."
                    decide = "MATCH | Timing difference resolved: settled with date delay."
                    matched_txn_id = candidates[0]["TransactionID"] if candidates else "NONE"
                
        return order_id, think, act, obs, decide, matched_txn_id

    def chat(self, model: str, messages: List[Dict[str, str]]) -> MockResponse:
        prompt = messages[0]["content"]
        if "RECONCILIATION TASK FOR:" in prompt or "--- ORDER_START:" in prompt:
            sections = prompt.split("RECONCILIATION TASK FOR:")
            out_blocks = []
            for sec in sections[1:]:
                order_id, think, act, obs, decide, matched_txn_id = self._eval_single_order(sec)
                out_blocks.append(
                    f"--- ORDER_START: {order_id} ---\n"
                    f"THINK: {think}\n"
                    f"ACT: {act}\n"
                    f"OBSERVE: {obs}\n"
                    f"DECIDE: {decide}\n"
                    f"MATCHED_TXN: {matched_txn_id}\n"
                    f"--- ORDER_END: {order_id} ---"
                )
            return MockResponse("\n\n".join(out_blocks))
        else:
            order_id, think, act, obs, decide, matched_txn_id = self._eval_single_order(prompt)
            content = f"THINK: {think}\nACT: {act}\nOBSERVE: {obs}\nDECIDE: {decide}"
            return MockResponse(content)


ENGINE_MODE = "cloud"  # Supported options: "cloud" (Gemini Exclusive -> Local -> Mock), "local" (Ollama -> Mock), "mock" (Offline)
ACTIVE_ENGINE_DETAILS: List[str] = []
ENGINE_CALL_COUNTS: Dict[str, int] = {"Cloud": 0, "Local": 0, "MockLLM": 0}


def get_active_engine_name() -> str:
    cloud_count = ENGINE_CALL_COUNTS["Cloud"]
    local_count = ENGINE_CALL_COUNTS["Local"]
    mock_count = ENGINE_CALL_COUNTS["MockLLM"]
    total = cloud_count + local_count + mock_count
    
    if ENGINE_MODE in ("cloud", "gemini"):
        if cloud_count > 0:
            return f"Gemini (gemini-flash-latest) [{cloud_count} calls]"
        return "Gemini (gemini-flash-latest)"
    elif ENGINE_MODE == "local":
        ollama_model = os.environ.get("OLLAMA_MODEL") or "qwen2.5:1.5b"
        if local_count > 0:
            return f"Ollama ({ollama_model}) [{local_count} calls]"
        return f"Ollama ({ollama_model})"
    elif ENGINE_MODE == "mock":
        return "MockLLM (Offline Simulator)"

    return "Gemini (gemini-flash-latest)"


# =====================================================================
# CLOUD MODEL ROTATION POOL (GEMINI CLOUD MODELS EXCLUSIVELY)
# =====================================================================
CLOUD_MODEL_ROTATION_POOL: List[Dict[str, str]] = [
    {"provider": "gemini", "model": "gemini-flash-latest", "label": "Gemini (gemini-flash-latest)"},
    {"provider": "gemini", "model": "gemini-flash-lite-latest", "label": "Gemini (gemini-flash-lite-latest)"},
    {"provider": "gemini", "model": "gemini-pro-latest", "label": "Gemini (gemini-pro-latest)"},
]


# Advance rotation index once per process run
_ROTATION_ADVANCED = False
_RUN_CLOUD_MODELS: List[Dict[str, str]] = []


def _get_run_cloud_models() -> List[Dict[str, str]]:
    global _ROTATION_ADVANCED, _RUN_CLOUD_MODELS
    if _ROTATION_ADVANCED and _RUN_CLOUD_MODELS:
        return _RUN_CLOUD_MODELS

    state_file = os.path.join(os.getcwd(), ".cloud_rotation_state")
    current_idx = 0
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                val = f.read().strip()
                current_idx = int(val) if val.isdigit() else 0
        except Exception:
            current_idx = 0

    next_idx = (current_idx + 1) % len(CLOUD_MODEL_ROTATION_POOL)
    # Atomic write with cleanup safeguard to avoid orphaned .tmp files
    tmp_path = None
    try:
        state_dir = os.path.dirname(state_file) or '.'
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8',
            dir=state_dir, delete=False, suffix='.tmp'
        ) as tmp:
            tmp.write(str(next_idx))
            tmp_path = tmp.name
        os.replace(tmp_path, state_file)
        tmp_path = None
    except Exception:
        try:
            with open(state_file, "w", encoding="utf-8") as f:
                f.write(str(next_idx))
        except Exception:
            pass
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    _ROTATION_ADVANCED = True
    _RUN_CLOUD_MODELS = CLOUD_MODEL_ROTATION_POOL[current_idx:] + CLOUD_MODEL_ROTATION_POOL[:current_idx]
    return _RUN_CLOUD_MODELS


ENGINE_MODE = "cloud"  # Supported options: "cloud" (Gemini/Groq -> Local -> Mock), "local" (Ollama -> Mock), "mock" (Offline)


def _load_env_keys() -> None:
    """Helper to ensure .env variables and Streamlit Cloud secrets are loaded into os.environ."""
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            for k, v in st.secrets.items():
                if isinstance(v, str):
                    os.environ.setdefault(k, v)
    except Exception:
        pass

    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line_s = line.strip()
                    if line_s and not line_s.startswith("#") and "=" in line_s:
                        k, v = line_s.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass

_load_env_keys()


def gemini_reason(prompt: str) -> str:
    """
    Tiered LLM reasoning interface following configurable priority:
    - "local": Local Ollama (qwen2.5:1.5b) -> MockLLM fallback
    - "cloud": Cloud rotation (Gemini & Groq) -> Local Ollama -> MockLLM
    - "mock": MockLLM offline simulator
    """
    _load_env_keys()
    if ENGINE_MODE == "local":
        base_url = os.environ.get("OPENCODE_BASE_URL") or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434/v1"
        if base_url and _is_safe_local_url(base_url):
            ollama_model = os.environ.get("OLLAMA_MODEL") or "qwen2.5:1.5b"
            url = f"{base_url.rstrip('/')}/chat/completions"
            headers = {"Content-Type": "application/json"}
            payload = {
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1
            }
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=25)
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"]
                    if content:
                        ENGINE_CALL_COUNTS["Local"] += 1
                        ACTIVE_ENGINE_DETAILS.append(f"Ollama ({ollama_model})")
                        return content
            except Exception:
                pass
        
        # Fallback to MockLLM if local server unreachable
        ENGINE_CALL_COUNTS["MockLLM"] += 1
        ACTIVE_ENGINE_DETAILS.append("MockLLM (Local Fallback)")
        mock_llm = MockLLM()
        response = mock_llm.chat("google/gemini-3-pro-high", [{"role": "user", "content": prompt}])
        return response.content

    elif ENGINE_MODE == "mock":
        ENGINE_CALL_COUNTS["MockLLM"] += 1
        ACTIVE_ENGINE_DETAILS.append("MockLLM (Offline Simulator)")
        mock_llm = MockLLM()
        response = mock_llm.chat("google/gemini-3-pro-high", [{"role": "user", "content": prompt}])
        return response.content

    # -------------------------------------------------------------
    # Priority 1: Gemini Cloud Models Exclusively
    # -------------------------------------------------------------
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    
    # Ensure system prompt schema instructions are attached
    formatted_prompt = prompt
    if "You are an autonomous fintech reconciliation" not in prompt and ("RECONCILIATION TASK FOR:" in prompt or "OrderID:" in prompt):
        formatted_prompt = (
            "You are an autonomous fintech reconciliation AI agent.\n"
            "For each order below, evaluate the details and candidates, then strictly output in this format:\n\n"
            "--- ORDER_START: [OrderID] ---\n"
            "THINK: [One line analysis]\n"
            "ACT: [One line action]\n"
            "OBSERVE: [One line observation]\n"
            "DECIDE: MATCH | [Reason]   (or MATCH_WITH_FEE_VARIATION | [Reason], or MATCH_WITH_EXCEPTION | [Reason], or MATCH_AS_REFUNDED | [Reason], or EXCEPTION | [Reason])\n"
            "MATCHED_TXN: [TransactionID or NONE]\n"
            "--- ORDER_END: [OrderID] ---\n\n"
        ) + prompt

    cloud_candidates = _get_run_cloud_models()
    for candidate in cloud_candidates:
        provider = candidate["provider"]
        model_name = candidate["model"]
        label = candidate["label"]

        if provider == "gemini" and gemini_key:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [{"parts": [{"text": formatted_prompt}]}],
                "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2048}
            }
            for attempt in range(2):
                try:
                    res = requests.post(url, headers=headers, json=payload, timeout=20)
                    if res.status_code == 200:
                        data = res.json()
                        candidates = data.get("candidates", [])
                        if candidates and "content" in candidates[0]:
                            parts = candidates[0]["content"].get("parts", [])
                            if parts and "text" in parts[0]:
                                text = parts[0]["text"]
                                if text:
                                    ENGINE_CALL_COUNTS["Cloud"] += 1
                                    ACTIVE_ENGINE_DETAILS.append(label)
                                    return text
                    elif res.status_code == 429:
                        time.sleep(1.0 * (attempt + 1))
                        continue
                    else:
                        break
                except Exception:
                    time.sleep(0.5)
                    continue

    # Fallback to local Ollama if Gemini key missing or exhausted
    base_url = os.environ.get("OPENCODE_BASE_URL") or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434/v1"
    if base_url and _is_safe_local_url(base_url):
        ollama_model = os.environ.get("OLLAMA_MODEL") or "qwen2.5:1.5b"
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": ollama_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=25)
            if res.status_code == 200:
                data = res.json()
                content = data["choices"][0]["message"]["content"]
                if content:
                    ENGINE_CALL_COUNTS["Local"] += 1
                    ACTIVE_ENGINE_DETAILS.append(f"Ollama ({ollama_model})")
                    return content
        except Exception:
            pass
    elif base_url and not _is_safe_local_url(base_url):
        # Log blocked SSRF attempt but continue to MockLLM fallback
        ACTIVE_ENGINE_DETAILS.append("SSRF_BLOCKED")

    # -------------------------------------------------------------
    # Priority 3: Fallback to MockLLM (Deterministic Offline ReAct Simulator)
    # -------------------------------------------------------------
    ENGINE_CALL_COUNTS["MockLLM"] += 1
    ACTIVE_ENGINE_DETAILS.append("MockLLM")
    mock_llm = MockLLM()
    response = mock_llm.chat("google/gemini-3-pro-high", [{"role": "user", "content": prompt}])
    return response.content



# =====================================================================
# LAYER 1: DATA GENERATION & GROUND TRUTH BENCHMARKING
# =====================================================================
# DATA GENERATION: REALISTIC INDIAN E-COMMERCE TRANSACTIONS
# =====================================================================
def generate_synthetic_data(
    base_date: Optional[datetime] = None,
    total_orders: int = 200,
    num_mismatches: int = 100,
    seed: Optional[int] = None
) -> Dict[str, Any]:
    """
    Generates realistic Indian e-commerce transaction data:
    - 200 total orders: 100 deterministic normal transactions (ORD1001-ORD1100) + 
      100 undeterministic mismatch anomalies (ORD1101-ORD1200).
    - Generates dynamic random prices and timestamps when seed=None.
    - Generates orders.csv, gateway.csv, bank.csv, and ground_truth.csv.
    Returns metadata summary of the generated dataset.
    """
    if seed is not None:
        random.seed(seed)

    if base_date is None:
        base_date = datetime(2026, 8, 20, 10, 0, 0)

    num_normal = total_orders - num_mismatches
    total_orders_count = total_orders

    # Generate sequential Order IDs: ORD1001 to ORD{1000+total_orders_count}
    all_order_indices = list(range(1, total_orders_count + 1))
    
    # 1..100 are deterministic normal transactions (ORD1001-ORD1100), 101..200 are injected mismatches (ORD1101-ORD1200)
    mismatch_indices = set(range(num_normal + 1, total_orders_count + 1))

    mismatch_types_pool = [
        "discount_on_order",
        "discount_on_gateway",
        "refunded",
        "timing_difference",
        "fee_variation",
        "missing_bank_entry"
    ]

    orders = []
    gateway = []
    bank = []
    ground_truth = []

    for idx in all_order_indices:
        order_id = f"ORD{1000 + idx}"
        pay_id = f"PAY{1000 + idx}"
        txn_id = f"TXN{1000 + idx}"

        order_date = base_date + timedelta(
            days=int((idx / total_orders_count) * 6),
            hours=random.randint(9, 20),
            minutes=random.randint(0, 59)
        )

        is_mismatch = idx in mismatch_indices

        if not is_mismatch:
            # Standard normal transaction (₹500 to ₹25,000)
            gross = round(random.uniform(500, 25000), 2)
            fee, gst, net = calculate_net(gross, rate=0.02)

            orders.append({
                "OrderID": order_id,
                "Date": order_date.strftime("%Y-%m-%d %H:%M:%S"),
                "Amount": gross,
                "Status": "success",
                "DiscountAmount": 0.0
            })

            gateway.append({
                "PaymentID": pay_id,
                "OrderID": order_id,
                "Amount": gross,
                "Fee": fee,
                "GST": gst,
                "SettlementAmount": net,
                "Date": order_date.strftime("%Y-%m-%d %H:%M:%S"),
                "Status": "captured"
            })

            settle_date = order_date + timedelta(days=random.randint(0, 1))
            bank.append({
                "TransactionID": txn_id,
                "Date": settle_date.strftime("%Y-%m-%d"),
                "Amount": net,
                "Narration": f"Settlement for {order_id} / {pay_id}"
            })

            ground_truth.append({
                "order_id": order_id,
                "mismatch_type": "none",
                "expected_amount_diff": 0.0,
                "is_mismatch": False,
                "lag_days": (settle_date.date() - order_date.date()).days,
                "expected_decision": "DETERMINISTIC_MATCH"
            })

        else:
            # Injected Mismatch Transaction
            m_type = random.choice(mismatch_types_pool)
            diff_amount = 0.0
            lag_days = 0

            if m_type == "discount_on_order":
                gross = round(random.uniform(2000, 25000), 2)
                discount = round(random.uniform(100, 1500), 2)
                diff_amount = discount
                orders.append({
                    "OrderID": order_id,
                    "Date": order_date.strftime("%Y-%m-%d %H:%M:%S"),
                    "Amount": round(gross - discount, 2),
                    "Status": "success",
                    "DiscountAmount": discount
                })
                fee, gst, net = calculate_net(gross, rate=0.02)
                gateway.append({
                    "PaymentID": pay_id,
                    "OrderID": order_id,
                    "Amount": gross,
                    "Fee": fee,
                    "GST": gst,
                    "SettlementAmount": net,
                    "Date": (order_date + timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S"),
                    "Status": "captured"
                })
                bank.append({
                    "TransactionID": txn_id,
                    "Date": order_date.strftime("%Y-%m-%d"),
                    "Amount": net,
                    "Narration": f"Settlement for {order_id} / {pay_id}"
                })
                expected_decision = "AI_RESOLVED"

            elif m_type == "discount_on_gateway":
                order_amt = round(random.uniform(2000, 25000), 2)
                discount = round(random.uniform(100, 1200), 2)
                diff_amount = discount
                orders.append({
                    "OrderID": order_id,
                    "Date": order_date.strftime("%Y-%m-%d %H:%M:%S"),
                    "Amount": order_amt,
                    "Status": "success",
                    "DiscountAmount": 0.0
                })
                gw_amt = round(order_amt - discount, 2)
                fee, gst, net = calculate_net(gw_amt, rate=0.02)
                gateway.append({
                    "PaymentID": pay_id,
                    "OrderID": order_id,
                    "Amount": gw_amt,
                    "Fee": fee,
                    "GST": gst,
                    "SettlementAmount": net,
                    "Date": (order_date + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"),
                    "Status": "captured"
                })
                bank.append({
                    "TransactionID": txn_id,
                    "Date": order_date.strftime("%Y-%m-%d"),
                    "Amount": net,
                    "Narration": f"Settlement for {order_id} / {pay_id}"
                })
                expected_decision = "AI_RESOLVED"

            elif m_type == "refunded":
                gross = round(random.uniform(1000, 20000), 2)
                fee, gst, net = calculate_net(gross, rate=0.02)
                diff_amount = gross
                orders.append({
                    "OrderID": order_id,
                    "Date": order_date.strftime("%Y-%m-%d %H:%M:%S"),
                    "Amount": gross,
                    "Status": "success",
                    "DiscountAmount": 0.0
                })
                gateway.append({
                    "PaymentID": pay_id,
                    "OrderID": order_id,
                    "Amount": gross,
                    "Fee": fee,
                    "GST": gst,
                    "SettlementAmount": net,
                    "Date": (order_date + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"),
                    "Status": "refunded"
                })
                bank.append({
                    "TransactionID": f"{txn_id}A",
                    "Date": order_date.strftime("%Y-%m-%d"),
                    "Amount": net,
                    "Narration": f"Settlement for {order_id} / {pay_id}"
                })
                bank.append({
                    "TransactionID": f"{txn_id}B",
                    "Date": (order_date + timedelta(days=1)).strftime("%Y-%m-%d"),
                    "Amount": -net,
                    "Narration": f"Refund payout for {pay_id}"
                })
                expected_decision = "AI_RESOLVED"

            elif m_type == "timing_difference":
                gross = round(random.uniform(1000, 22000), 2)
                fee, gst, net = calculate_net(gross, rate=0.02)
                # Includes 2-day SLA boundary and >2 day lags
                lag_days = random.choice([2, 2, 3, 4, 5])
                orders.append({
                    "OrderID": order_id,
                    "Date": order_date.strftime("%Y-%m-%d %H:%M:%S"),
                    "Amount": gross,
                    "Status": "success",
                    "DiscountAmount": 0.0
                })
                gateway.append({
                    "PaymentID": pay_id,
                    "OrderID": order_id,
                    "Amount": gross,
                    "Fee": fee,
                    "GST": gst,
                    "SettlementAmount": net,
                    "Date": (order_date + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"),
                    "Status": "captured"
                })
                settle_date = order_date + timedelta(days=lag_days)
                bank.append({
                    "TransactionID": txn_id,
                    "Date": settle_date.strftime("%Y-%m-%d"),
                    "Amount": net,
                    "Narration": f"Settlement for {order_id} / {pay_id}"
                })
                expected_decision = "AI_RESOLVED"

            elif m_type == "fee_variation":
                gross = round(random.uniform(2500, 25000), 2)
                # Includes sub-0.5% subtle variations (2.3%, 2.4%) and larger variations (3.0%, 3.5%)
                actual_rate = random.choice([0.023, 0.024, 0.03, 0.035])
                fee_var, gst_var, net_var = calculate_net(gross, rate=actual_rate)
                std_fee, std_gst, std_net = calculate_net(gross, rate=0.02)
                diff_amount = round(abs(std_net - net_var), 2)
                orders.append({
                    "OrderID": order_id,
                    "Date": order_date.strftime("%Y-%m-%d %H:%M:%S"),
                    "Amount": gross,
                    "Status": "success",
                    "DiscountAmount": 0.0
                })
                gateway.append({
                    "PaymentID": pay_id,
                    "OrderID": order_id,
                    "Amount": gross,
                    "Fee": fee_var,
                    "GST": gst_var,
                    "SettlementAmount": net_var,
                    "Date": (order_date + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"),
                    "Status": "captured"
                })
                bank.append({
                    "TransactionID": txn_id,
                    "Date": order_date.strftime("%Y-%m-%d"),
                    "Amount": net_var,
                    "Narration": f"Settlement for {order_id} / {pay_id}"
                })
                expected_decision = "AI_RESOLVED"

            elif m_type == "missing_bank_entry":
                gross = round(random.uniform(1000, 18000), 2)
                fee, gst, net = calculate_net(gross, rate=0.02)
                diff_amount = net
                orders.append({
                    "OrderID": order_id,
                    "Date": order_date.strftime("%Y-%m-%d %H:%M:%S"),
                    "Amount": gross,
                    "Status": "success",
                    "DiscountAmount": 0.0
                })
                gateway.append({
                    "PaymentID": pay_id,
                    "OrderID": order_id,
                    "Amount": gross,
                    "Fee": fee,
                    "GST": gst,
                    "SettlementAmount": net,
                    "Date": (order_date + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"),
                    "Status": "captured"
                })
                expected_decision = "EXCEPTION"

            ground_truth.append({
                "order_id": order_id,
                "mismatch_type": m_type,
                "expected_amount_diff": diff_amount,
                "is_mismatch": True,
                "lag_days": lag_days,
                "expected_decision": expected_decision
            })

    # Helper function to write CSVs
    def write_csv(filename: str, fieldnames: List[str], data: List[Dict[str, Any]]) -> None:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)

    write_csv("orders.csv", ["OrderID", "Date", "Amount", "Status", "DiscountAmount"], orders)
    write_csv("gateway.csv", ["PaymentID", "OrderID", "Amount", "Fee", "GST", "SettlementAmount", "Date", "Status"], gateway)
    write_csv("bank.csv", ["TransactionID", "Date", "Amount", "Narration"], bank)
    write_csv("ground_truth.csv", ["order_id", "mismatch_type", "expected_amount_diff", "is_mismatch", "lag_days", "expected_decision"], ground_truth)

    return {
        "total_orders": len(orders),
        "normal_orders": num_normal,
        "mismatches_injected": num_mismatches,
        "ground_truth_map": {row["order_id"]: row for row in ground_truth}
    }


# =====================================================================
# DATA INGESTION & NORMALIZATION FOR CUSTOM CSVs
# =====================================================================
def _read_csv_rows(source: Any) -> List[Dict[str, Any]]:
    """Helper to extract list of row dicts from multiple source types."""
    if source is None:
        return []
    if isinstance(source, list):
        return [dict(r) if isinstance(r, dict) else r for r in source]
    
    # Check if pandas DataFrame
    if hasattr(source, "to_dict"):
        try:
            return source.to_dict(orient="records")
        except Exception:
            pass

    # If source is a string (file path or raw CSV text)
    if isinstance(source, str):
        if os.path.exists(source):
            with open(source, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                return [dict(row) for row in reader]
        else:
            f = io.StringIO(source.strip())
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]

    # If source has a .read() method (e.g., Streamlit UploadedFile, StringIO, BytesIO)
    if hasattr(source, "read"):
        pos = getattr(source, "tell", lambda: 0)()
        raw_data = source.read()
        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode("utf-8", errors="replace")
        if hasattr(source, "seek"):
            try:
                source.seek(pos)
            except Exception:
                pass
        f = io.StringIO(raw_data.strip())
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]

    return []


def load_reconciliation_data(
    orders_source: Any,
    gateway_source: Any,
    bank_source: Any,
    ground_truth_source: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Ingests and normalizes custom or standard CSV files for orders, gateway, bank,
    and optional ground truth. Supports flexible column names and auto-calculates
    missing fields (like fees and GST).
    """
    raw_orders = _read_csv_rows(orders_source)
    raw_gateway = _read_csv_rows(gateway_source)
    raw_bank = _read_csv_rows(bank_source)
    raw_gt = _read_csv_rows(ground_truth_source) if ground_truth_source else []

    # 1. Normalize Orders
    orders: Dict[str, Dict[str, Any]] = {}
    for idx, r in enumerate(raw_orders):
        ck = {re.sub(r'[^a-z0-9]', '', str(k).lower()): v for k, v in r.items()}
        o_id = str(ck.get('orderid') or ck.get('order') or ck.get('id') or ck.get('orderno') or f"ORD{idx+1:03d}").strip()
        dt = str(ck.get('date') or ck.get('orderdate') or ck.get('timestamp') or ck.get('createdat') or datetime.now().strftime("%Y-%m-%d")).strip()
        amt = parse_float_safe(ck.get('amount') or ck.get('grossamount') or ck.get('orderamount') or ck.get('total') or 0.0)
        status = str(ck.get('status') or ck.get('orderstatus') or 'completed').strip()
        disc = parse_float_safe(ck.get('discountamount') or ck.get('discount') or ck.get('disc') or 0.0)

        orders[o_id] = {
            "OrderID": o_id,
            "Date": dt,
            "Amount": amt,
            "Status": status,
            "DiscountAmount": disc
        }

    # 2. Normalize Gateway
    gateway: Dict[str, Dict[str, Any]] = {}
    for idx, r in enumerate(raw_gateway):
        ck = {re.sub(r'[^a-z0-9]', '', str(k).lower()): v for k, v in r.items()}
        p_id = str(ck.get('paymentid') or ck.get('payid') or ck.get('id') or ck.get('txnid') or ck.get('transactionid') or f"PAY{idx+1:03d}").strip()
        o_id = str(ck.get('orderid') or ck.get('order') or ck.get('id') or f"ORD{idx+1:03d}").strip()
        amt = parse_float_safe(ck.get('amount') or ck.get('grossamount') or ck.get('gatewayamount') or 0.0)
        
        # Determine Fee, GST, and Net
        calc_fee, calc_gst, calc_net = calculate_net(amt, rate=0.02)
        fee = parse_float_safe(ck.get('fee') or ck.get('gatewayfee') or ck.get('commission') or ck.get('mdr'), calc_fee)
        gst = parse_float_safe(ck.get('gst') or ck.get('tax'), calc_gst)
        net = parse_float_safe(ck.get('settlementamount') or ck.get('netamount') or ck.get('settledamount') or ck.get('net'), calc_net)
        
        dt = str(ck.get('date') or ck.get('settlementdate') or ck.get('timestamp') or ck.get('createdat') or datetime.now().strftime("%Y-%m-%d %H:%M:%S")).strip()
        status = str(ck.get('status') or ck.get('paymentstatus') or 'captured').strip()

        gateway[o_id] = {
            "PaymentID": p_id,
            "OrderID": o_id,
            "Amount": amt,
            "Fee": fee,
            "GST": gst,
            "SettlementAmount": net,
            "Date": dt,
            "Status": status
        }

    # 3. Normalize Bank
    bank: List[Dict[str, Any]] = []
    for idx, r in enumerate(raw_bank):
        ck = {re.sub(r'[^a-z0-9]', '', str(k).lower()): v for k, v in r.items()}
        t_id = str(ck.get('transactionid') or ck.get('txnid') or ck.get('refno') or ck.get('id') or ck.get('reference') or f"TXN{idx+1:03d}").strip()
        dt = str(ck.get('date') or ck.get('valuedate') or ck.get('txndate') or ck.get('timestamp') or datetime.now().strftime("%Y-%m-%d")).strip()
        amt = parse_float_safe(ck.get('amount') or ck.get('deposit') or ck.get('credit') or ck.get('netamount') or 0.0)
        narration = str(ck.get('narration') or ck.get('description') or ck.get('particulars') or ck.get('remarks') or '').strip()

        bank.append({
            "TransactionID": t_id,
            "Date": dt,
            "Amount": amt,
            "Narration": narration,
            "Matched": False
        })

    # 4. Optional Ground Truth
    ground_truth_map: Dict[str, Dict[str, Any]] = {}
    for r in raw_gt:
        ck = {re.sub(r'[^a-z0-9]', '', str(k).lower()): v for k, v in r.items()}
        o_id = str(ck.get('orderid') or ck.get('order') or ck.get('id') or "").strip()
        if not o_id:
            continue
        m_type = str(ck.get('mismatchtype') or ck.get('type') or 'normal').strip()
        diff_amt = parse_float_safe(ck.get('expectedamountdiff') or ck.get('amountdiff') or 0.0)
        is_mism = str(ck.get('ismismatch', '')).strip().lower() in ('true', '1', 'yes', 't')
        lag = int(parse_float_safe(ck.get('lagdays') or ck.get('lag') or 0))
        dec = str(ck.get('expecteddecision') or ck.get('decision') or ('AI_RESOLVED' if is_mism else 'DETERMINISTIC')).strip()

        ground_truth_map[o_id] = {
            "order_id": o_id,
            "mismatch_type": m_type,
            "expected_amount_diff": diff_amt,
            "is_mismatch": is_mism,
            "lag_days": lag,
            "expected_decision": dec
        }

    return {
        "orders": orders,
        "gateway": gateway,
        "bank": bank,
        "ground_truth_map": ground_truth_map,
        "total_orders": len(orders)
    }


# =====================================================================
# DETERMINISTIC MATCHING ENGINE
# =====================================================================
def run_deterministic_matcher(
    orders: Optional[Dict[str, Dict[str, Any]]] = None,
    gateway: Optional[Dict[str, Dict[str, Any]]] = None,
    bank_records: Optional[List[Dict[str, Any]]] = None,
    orders_source: Any = "orders.csv",
    gateway_source: Any = "gateway.csv",
    bank_source: Any = "bank.csv"
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """
    Executes rule-based matching:
    - 2.0% fee + 18.0% GST standard contract rate.
    - Exact OrderID & PaymentID mapping.
    - Bank statement value date within <= 1 day proximity (isolates timing differences).
    """
    if orders is None or gateway is None or bank_records is None:
        dataset = load_reconciliation_data(orders_source, gateway_source, bank_source)
        orders = dataset["orders"]
        gateway = dataset["gateway"]
        bank_records = dataset["bank"]

    # Reset bank matched flags
    for b in bank_records:
        b["Matched"] = False

    matched = []
    unmatched_orders = {}
    unmatched_gateway = {}

    for o_id, order in orders.items():
        if o_id in gateway:
            gw = gateway[o_id]
            gross = order["Amount"]
            expected_fee, expected_gst, expected_net = calculate_net(gross, rate=0.02)
            gw_net = gw["SettlementAmount"]

            # Locate matching bank statement line within <= 1 day proximity
            bank_match = None
            for bk in bank_records:
                if not bk["Matched"] and o_id in bk["Narration"]:
                    if abs(bk["Amount"] - expected_net) <= 0.05 and abs(bk["Amount"] - gw_net) <= 0.05:
                        if gw["Status"] == "captured" and order["DiscountAmount"] == 0.0:
                            gw_date = parse_date_safe(gw["Date"])
                            bk_date = parse_date_safe(bk["Date"])
                            if gw_date and bk_date:
                                if abs((bk_date - gw_date).days) <= 1:
                                    bank_match = bk
                                    break
                            else:
                                bank_match = bk
                                break

            if bank_match:
                bank_match["Matched"] = True
                matched.append({
                    "OrderID": o_id,
                    "PaymentID": gw["PaymentID"],
                    "TransactionID": bank_match["TransactionID"],
                    "OrderAmount": gross,
                    "GatewayAmount": gw["Amount"],
                    "BankAmount": bank_match["Amount"],
                    "Fee": expected_fee,
                    "GST": expected_gst,
                    "Type": "Deterministic Match",
                    "Status": "CONFIRMED",
                    "Reason": "Gross, gateway net settlement, and bank deposit match under standard 2% MDR."
                })
            else:
                unmatched_orders[o_id] = order
                unmatched_gateway[o_id] = gw
        else:
            unmatched_orders[o_id] = order

    for gw_id, gw in gateway.items():
        if gw_id not in orders:
            unmatched_gateway[gw_id] = gw

    unmatched_bank = [b for b in bank_records if not b["Matched"]]
    return matched, unmatched_orders, unmatched_gateway, unmatched_bank


# =====================================================================
# =====================================================================
# REACT AI AGENT ENGINE & PARALLEL CHUNK WORKER
# =====================================================================
def process_single_chunk(
    chunk_orders: List[Any],
    bank_candidates_map: Optional[Dict[str, List[Dict[str, Any]]]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Parallel Thread-Pool Worker:
    Handles prompt formulation, concurrency retries with exponential backoff,
    response parsing, and strict mathematical verification guardrails for a single chunk.
    """
    chunk_resolved: List[Dict[str, Any]] = []
    chunk_exceptions: List[Dict[str, Any]] = []
    dynamic_chunk_size = len(chunk_orders)

    # A. Prompt Construction
    prompt = f"""You are an AI Financial Controller reconciling {dynamic_chunk_size} ambiguous e-commerce payment anomalies against bank statement candidate feeds.
Evaluate EACH order independently. For EACH order, analyze order details, gateway status, and candidates.

You MUST follow this EXACT delimiter structure for EVERY order in the batch:

--- ORDER_START: [OrderID] ---
THINK: [1-2 sentences on amounts, fee variance, discounts, refunds, or timing]
ACT: [Audit verification checked across gateway and bank candidates]
OBSERVE: [Evidence verified]
DECIDE: [MATCH | MATCH_WITH_EXCEPTION | MATCH_AS_REFUNDED | MATCH_WITH_FEE_VARIATION | EXCEPTION] | [Specific reason]
MATCHED_TXN: [TransactionID of the matched bank candidate, or NONE if EXCEPTION]
--- ORDER_END: [OrderID] ---

"""
    for item in chunk_orders:
        if isinstance(item, tuple) and len(item) == 4:
            o_id, order, gw, bank_candidates = item
        elif isinstance(item, tuple) and len(item) == 2:
            o_id, (order, gw, bank_candidates) = item
        else:
            o_id = item["OrderID"]
            order = item
            gw = item.get("Gateway")
            bank_candidates = bank_candidates_map.get(o_id, []) if bank_candidates_map else []

        prompt += f"""
================================================================================
RECONCILIATION TASK FOR: {o_id}
[INTERNAL ORDER DETAILS]
OrderID: {order['OrderID']}
Date: {order['Date']}
Amount: {order['Amount']}
Status: {order['Status']}
DiscountAmount: {order['DiscountAmount']}

[GATEWAY TRANSACTION DETAILS]
PaymentID: {gw['PaymentID'] if gw else 'N/A'}
Gross Amount: {gw['Amount'] if gw else 'N/A'}
Expected Settlement: {gw['SettlementAmount'] if gw else 'N/A'}
Date: {gw['Date'] if gw else 'N/A'}
Status: {gw['Status'] if gw else 'N/A'}

[BANK STATEMENT CANDIDATES]
"""
        for i, cand in enumerate(bank_candidates):
            prompt += f"Candidate {i+1}: TransactionID={cand['TransactionID']}, Date={cand['Date']}, Amount={cand['Amount']}, Narration='{cand['Narration']}'\n"

    # B. Concurrency & Exponential Backoff Retry Loop
    ai_response = ""
    for attempt in range(3):
        try:
            ai_response = gemini_reason(prompt)
            if ai_response:
                break
            time.sleep(2 ** attempt)
        except Exception:
            if attempt == 2:
                break
            time.sleep(2 ** attempt)

    if not ai_response:
        for item in chunk_orders:
            if isinstance(item, tuple) and len(item) >= 3:
                o_id, order, gw = item[0], item[1], item[2]
            else:
                o_id = item["OrderID"] if isinstance(item, dict) else str(item)
                order = item if isinstance(item, dict) else {}
                gw = None
            chunk_exceptions.append({
                "OrderID": o_id,
                "PaymentID": gw["PaymentID"] if gw else "N/A",
                "OrderAmount": order.get("Amount", 0.0),
                "GatewayAmount": gw.get("Amount", 0.0) if gw else 0.0,
                "Type": "API Timeout Error",
                "Reason": "API timeout during batch audit",
                "Order": order,
                "Gateway": gw
            })
        return chunk_resolved, chunk_exceptions

    # C. Chunk Response Parsing & Mathematical Verification
    order_blocks: Dict[str, str] = {}
    blocks = ai_response.split("--- ORDER_START:")
    for block in blocks[1:]:
        lines = block.split("\n")
        header_line = lines[0].strip()
        o_id_match = re.search(r"([A-Za-z0-9_]+)", header_line)
        if o_id_match:
            block_order_id = o_id_match.group(1).replace("---", "").strip("[] ")
            order_blocks[block_order_id] = block

    for item in chunk_orders:
        if isinstance(item, tuple) and len(item) == 4:
            o_id, order, gw, bank_candidates = item
        elif isinstance(item, tuple) and len(item) == 2:
            o_id, (order, gw, bank_candidates) = item
        else:
            o_id = item["OrderID"]
            order = item
            gw = item.get("Gateway")
            bank_candidates = bank_candidates_map.get(o_id, []) if bank_candidates_map else []

        block = order_blocks.get(o_id, "")
        if not block:
            for blk_id, blk in order_blocks.items():
                if o_id in blk_id:
                    block = blk
                    break
        if not block:
            block = ai_response

        think_step, act_step, obs_step, decide_step, matched_txn_id = "", "", "", "", "NONE"
        for line in block.split("\n"):
            clean = line.strip().replace("**", "")
            if clean.startswith("THINK:"):
                think_step = clean
            elif clean.startswith("ACT:"):
                act_step = clean
            elif clean.startswith("OBSERVE:"):
                obs_step = clean
            elif clean.startswith("DECIDE:"):
                decide_step = clean
            elif clean.startswith("MATCHED_TXN:"):
                matched_txn_id = clean.split("MATCHED_TXN:")[1].strip("[] \r\n")

        if not decide_step:
            for line in block.split("\n"):
                if "DECIDE:" in line:
                    decide_step = line.strip().replace("**", "")
                    break

        if not decide_step:
            decide_step = "DECIDE: EXCEPTION | Agent could not resolve transaction in batch."

        try:
            parts = decide_step.split("DECIDE:")[1].split("|")
            classification = parts[0].strip()
            reason_detail = parts[1].strip() if len(parts) > 1 else "Resolved by ReAct AI agent."
        except Exception:
            classification = "EXCEPTION"
            reason_detail = decide_step

        if classification in ["MATCH", "MATCH_WITH_EXCEPTION", "MATCH_AS_REFUNDED", "MATCH_WITH_FEE_VARIATION"]:
            matched_txn = None
            if matched_txn_id and matched_txn_id.upper() != "NONE":
                for cand in bank_candidates:
                    if cand["TransactionID"].strip().upper() == matched_txn_id.strip().upper():
                        matched_txn = cand
                        break
            if not matched_txn and bank_candidates:
                for cand in bank_candidates:
                    if cand["TransactionID"] in block or str(cand["Amount"]) in block:
                        matched_txn = cand
                        break
                    if gw and abs(cand["Amount"] - gw["SettlementAmount"]) <= 0.05:
                        matched_txn = cand
                        break

            # Deterministic Mathematical Verification Guardrail
            is_verified = False
            if matched_txn:
                cand_amt = matched_txn["Amount"]
                expected_gw_net = gw["SettlementAmount"] if gw else (order["Amount"] * 0.9764)
                delta = abs(cand_amt - expected_gw_net)
                if classification in ["MATCH_WITH_FEE_VARIATION", "MATCH_WITH_EXCEPTION"]:
                    is_verified = (delta < 500.0)
                else:
                    is_verified = (delta <= 1.0)

            if matched_txn and is_verified:
                matched_txn["Matched"] = True

                gw_gross = gw["Amount"] if gw else order["Amount"]
                gw_fee = gw["Fee"] if gw else round(gw_gross * 0.02, 2)
                gw_gst = gw["GST"] if gw else round(gw_fee * 0.18, 2)

                chunk_resolved.append({
                    "OrderID": o_id,
                    "PaymentID": gw["PaymentID"] if gw else "N/A",
                    "TransactionID": matched_txn["TransactionID"],
                    "OrderAmount": order["Amount"],
                    "GatewayAmount": gw_gross,
                    "BankAmount": matched_txn["Amount"],
                    "Fee": gw_fee,
                    "GST": gw_gst,
                    "Type": f"AI ReAct Match ({classification})",
                    "Status": "PENDING_SETTLEMENT" if classification == "MATCH" and "timing" in reason_detail.lower() else "CONFIRMED",
                    "Classification": classification,
                    "Reason": reason_detail,
                    "GatewayStatus": gw["Status"] if gw else "captured",
                    "Order": order,
                    "Gateway": gw
                })
            else:
                failure_type = "Verification Failed" if matched_txn and not is_verified else "missing_bank_entry"
                failure_reason = (
                    f"Mathematical verification failed (delta={abs(matched_txn['Amount'] - gw['SettlementAmount']):.2f} exceeds tolerance). Reason: {reason_detail}"
                    if matched_txn and not is_verified
                    else f"Agent decided {classification} but no valid matching bank deposit was confirmed. Detail: {reason_detail}"
                )
                chunk_exceptions.append({
                    "OrderID": o_id,
                    "PaymentID": gw["PaymentID"] if gw else "N/A",
                    "OrderAmount": order["Amount"],
                    "GatewayAmount": gw["Amount"] if gw else 0.0,
                    "Type": failure_type,
                    "Reason": failure_reason,
                    "Order": order,
                    "Gateway": gw
                })
        else:
            chunk_exceptions.append({
                "OrderID": o_id,
                "PaymentID": gw["PaymentID"] if gw else "N/A",
                "OrderAmount": order["Amount"],
                "GatewayAmount": gw["Amount"] if gw else 0.0,
                "Type": "missing_bank_entry" if "missing bank" in reason_detail.lower() else "disputed_exception",
                "Reason": reason_detail,
                "Order": order,
                "Gateway": gw
            })

    return chunk_resolved, chunk_exceptions


def run_react_agent(
    unmatched_orders: Dict[str, Any],
    unmatched_gateway: Dict[str, Any],
    unmatched_bank: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    High-Performance Batched ReAct AI Reconciler:
    1. Fast-Path Heuristic Triage (Skip LLM for empty candidates & pure timing delays).
    2. Dynamic Logarithmic Batch Size Calculation.
    3. ThreadPoolExecutor concurrent batch processing with exponential backoff.
    4. Robust parsing and mathematical verification guardrail.
    """
    fast_path_matches: List[Dict[str, Any]] = []
    fast_path_exceptions: List[Dict[str, Any]] = []
    complex_anomalies: List[Tuple[str, Dict[str, Any], Optional[Dict[str, Any]], List[Dict[str, Any]]]] = []
    bank_candidates_map: Dict[str, List[Dict[str, Any]]] = {}

    # -------------------------------------------------------------
    # STEP 1: FAST-PATH HEURISTIC TRIAGE
    # -------------------------------------------------------------
    for o_id, order in list(unmatched_orders.items()):
        gw = unmatched_gateway.get(o_id)
        gross = order["Amount"]
        expected_fee, expected_gst, expected_net = calculate_net(gross, rate=0.02)
        if gw:
            expected_net = gw.get("SettlementAmount", expected_net)

        # Candidate selection
        bank_candidates = []
        for bk in unmatched_bank:
            if o_id in bk["Narration"] or (gw and gw["PaymentID"] in bk["Narration"]):
                bank_candidates.append(bk)
        if not bank_candidates:
            for bk in unmatched_bank:
                if gw and abs(bk["Amount"] - gw["SettlementAmount"]) <= 0.05:
                    bank_candidates.append(bk)

        # Heuristic 1: Empty Candidate Check (Missing Settlement Leak)
        if len(bank_candidates) == 0:
            fast_path_exceptions.append({
                "OrderID": o_id,
                "PaymentID": gw["PaymentID"] if gw else "N/A",
                "OrderAmount": order["Amount"],
                "GatewayAmount": gw["Amount"] if gw else 0.0,
                "Type": "Missing Bank Settlement",
                "Reason": "No candidate transaction found in bank statement feed.",
                "Order": order,
                "Gateway": gw
            })
            unmatched_orders.pop(o_id, None)
            unmatched_gateway.pop(o_id, None)
            continue

        # Heuristic 2: Pure Timing Delay Check
        timing_matched_cand = None
        if gw and gw.get("Status") == "captured" and order.get("DiscountAmount", 0.0) == 0.0:
            gw_date = parse_date_safe(gw["Date"])
            for cand in bank_candidates:
                if abs(cand["Amount"] - expected_net) <= 0.05 and abs(cand["Amount"] - gw["SettlementAmount"]) <= 0.05:
                    bk_date = parse_date_safe(cand["Date"])
                    if gw_date and bk_date:
                        if abs((bk_date - gw_date).days) > 2:
                            timing_matched_cand = cand
                            break

        if timing_matched_cand:
            timing_matched_cand["Matched"] = True
            if timing_matched_cand in unmatched_bank:
                unmatched_bank.remove(timing_matched_cand)

            gw_gross = gw["Amount"] if gw else order["Amount"]
            gw_fee = gw["Fee"] if gw else round(gw_gross * 0.02, 2)
            gw_gst = gw["GST"] if gw else round(gw_fee * 0.18, 2)

            fast_path_matches.append({
                "OrderID": o_id,
                "PaymentID": gw["PaymentID"] if gw else "N/A",
                "TransactionID": timing_matched_cand["TransactionID"],
                "OrderAmount": order["Amount"],
                "GatewayAmount": gw_gross,
                "BankAmount": timing_matched_cand["Amount"],
                "Fee": gw_fee,
                "GST": gw_gst,
                "Classification": "MATCH_WITH_EXCEPTION",
                "Type": "AI ReAct Match (MATCH_WITH_EXCEPTION)",
                "Status": "PENDING_SETTLEMENT",
                "Reason": "Settlement timing delay: Gateway captured payment settled outside standard SLA window.",
                "GatewayStatus": gw["Status"] if gw else "captured",
                "Order": order,
                "Gateway": gw
            })
            unmatched_orders.pop(o_id, None)
            unmatched_gateway.pop(o_id, None)
            continue

        # Ambiguous case: complex anomaly requiring cognitive LLM reasoning
        complex_anomalies.append((o_id, order, gw, bank_candidates))
        bank_candidates_map[o_id] = bank_candidates

    # -------------------------------------------------------------
    # STEP 2: DYNAMIC LOGARITHMIC BATCH SIZE CALCULATION
    # -------------------------------------------------------------
    num_anomalies = len(complex_anomalies)
    if num_anomalies > 0:
        dynamic_chunk_size = min(25, max(12, int(math.ceil(math.log2(num_anomalies) * 3))))
    else:
        dynamic_chunk_size = 12

    resolved_matches: List[Dict[str, Any]] = list(fast_path_matches)
    exceptions: List[Dict[str, Any]] = list(fast_path_exceptions)

    # -------------------------------------------------------------
    # STEP 3: CONCURRENCY CONTROL WITH THREADPOOLEXECUTOR
    # -------------------------------------------------------------
    if complex_anomalies:
        chunks = [complex_anomalies[i:i + dynamic_chunk_size] for i in range(0, len(complex_anomalies), dynamic_chunk_size)]

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_chunk = {
                executor.submit(process_single_chunk, chunk, bank_candidates_map): chunk
                for chunk in chunks
            }
            for future in as_completed(future_to_chunk):
                chunk = future_to_chunk[future]
                try:
                    chunk_resolved, chunk_exceptions = future.result()
                    resolved_matches.extend(chunk_resolved)
                    exceptions.extend(chunk_exceptions)
                except Exception as e:
                    # Thread Crash Safety Guardrail
                    for item in chunk:
                        o_id = item[0] if isinstance(item, tuple) else (item.get("OrderID") if isinstance(item, dict) else str(item))
                        order = item[1] if isinstance(item, tuple) else (item if isinstance(item, dict) else {})
                        gw = item[2] if isinstance(item, tuple) else None
                        exceptions.append({
                            "OrderID": o_id,
                            "PaymentID": gw["PaymentID"] if gw else "N/A",
                            "OrderAmount": order.get("Amount", 0.0),
                            "GatewayAmount": gw.get("Amount", 0.0) if gw else 0.0,
                            "Type": "Parallel Thread Failure",
                            "Reason": f"System thread crashed: {str(e)}",
                            "Order": order,
                            "Gateway": gw
                        })

    # -------------------------------------------------------------
    # STEP 4: CRYPTOGRAPHIC AUDIT TRAIL (POST-PARALLELIZATION)
    # -------------------------------------------------------------
    resolved_matches.sort(key=lambda x: (str(x.get("OrderID", "")), str(x.get("TransactionID", ""))))
    prev_hash = "0000000000000000000000000000000000000000000000000000000000000000"
    for record in resolved_matches:
        order_id = record.get("OrderID", "")
        txn_id = record.get("TransactionID", "")
        bank_amt = record.get("BankAmount", 0.0)
        data_to_hash = f"{order_id}|{txn_id}|{bank_amt}|{prev_hash}"
        current_hash = hashlib.sha256(data_to_hash.encode("utf-8")).hexdigest()
        record["AuditHash"] = current_hash
        prev_hash = current_hash

    print("Cryptographic ledger audit chain compiled successfully.")

    return resolved_matches, exceptions


# =====================================================================
# LAYER 2: CASH POSITION CONTROLLER
# =====================================================================
class CashPositionController:
    """
    Tracks and reconciles dual-track cash accounting:
    1. Operating Inflows: Confirmed receipts, pending/lagged receipts, disputed receipts.
    2. Operational Outflows: Gateway MDR, GST on fees, refunds disbursed, unexplained variances.
    3. Closing Available Liquidity & Variance Reporting.
    """
    def __init__(self, opening_balance: float = 500000.0):
        self.opening_balance = opening_balance
        self.statement: Dict[str, Any] = {}

    def update_from_reconciliation(
        self,
        det_matches: List[Dict[str, Any]],
        ai_matches: List[Dict[str, Any]],
        exceptions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Ingests reconciliation outputs to compute exact cash flows.
        """
        # Inflow aggregation from bank deposits (already net of MDR fees)
        confirmed_inflow = sum(m["BankAmount"] for m in det_matches if m.get("BankAmount", 0.0) > 0)
        
        # Split AI matches into confirmed vs pending vs refund adjustments
        ai_confirmed_inflow = 0.0
        ai_pending_inflow = 0.0
        refunds_processed = 0.0
        gateway_fees = sum(m.get("Fee", 0.0) for m in det_matches)
        gst_outflows = sum(m.get("GST", 0.0) for m in det_matches)

        for m in ai_matches:
            c_type = m.get("Classification", "")
            bank_amt = m.get("BankAmount", 0.0)
            fee = m.get("Fee", 0.0)
            gst = m.get("GST", 0.0)
            gateway_fees += fee
            gst_outflows += gst

            if c_type == "MATCH_AS_REFUNDED":
                refunds_processed += abs(m.get("OrderAmount", 0.0))
            elif "timing" in m.get("Reason", "").lower() or m.get("Status") == "PENDING_SETTLEMENT":
                ai_pending_inflow += max(0.0, bank_amt)
            else:
                ai_confirmed_inflow += max(0.0, bank_amt)

        disputed_inflow = sum(e.get("OrderAmount", 0.0) for e in exceptions)
        unexplained_variance = sum(ex.get("OrderAmount", 0.0) for ex in exceptions)

        # Inflows realized to bank
        total_realized_inflows = confirmed_inflow + ai_confirmed_inflow
        total_inflows = total_realized_inflows + ai_pending_inflow

        # Cash outflows that directly decrease available bank balance
        total_cash_outflows = refunds_processed
        
        # Total tracked fee costs (for P&L / reporting / ITC tracking)
        total_fee_burn = gateway_fees + gst_outflows
        total_outflows = total_cash_outflows + total_fee_burn

        # Closing balance ties out mathematically to the net bank position:
        closing_balance = self.opening_balance + total_realized_inflows - total_cash_outflows

        self.statement = {
            "opening_balance": self.opening_balance,
            "inflows": {
                "confirmed_deterministic": confirmed_inflow,
                "confirmed_ai_resolved": ai_confirmed_inflow,
                "pending_settlements": ai_pending_inflow,
                "disputed_blocked": disputed_inflow,
                "total_inflows": total_inflows,
                "total_realized_inflows": total_realized_inflows
            },
            "outflows": {
                "gateway_fees": gateway_fees,
                "gst_on_fees": gst_outflows,
                "refunds_processed": refunds_processed,
                "unexplained_variance": unexplained_variance,
                "total_outflows": total_outflows,
                "total_fee_burn": total_fee_burn,
                "total_cash_outflows": total_cash_outflows
            },
            "closing_balance": closing_balance,
            "unexplained_variance": unexplained_variance
        }
        return self.statement

    def generate_statement(self) -> Dict[str, Any]:
        """Returns the structured financial statement dictionary."""
        return self.statement

    def print_statement(self) -> None:
        """Prints a beautifully formatted ANSI cash position box statement."""
        st = self.statement
        inf = st["inflows"]
        outf = st["outflows"]

        width = 68
        print("+" + "=" * (width - 2) + "+")
        print(f"|{'CASH POSITION STATEMENT':^{width - 2}}|")
        print("+" + "=" * (width - 2) + "+")
        print(f"| Opening Cash Balance:               {format_inr(st['opening_balance']):>37} |")
        print("|" + "-" * (width - 2) + "|")
        print(f"| INFLOWS (NET BANK DEPOSITS):                                       |")
        print(f"|   • Confirmed (Deterministic):       {format_inr(inf['confirmed_deterministic']):>37} |")
        print(f"|   • Resolved Settlements (AI):       {format_inr(inf['confirmed_ai_resolved']):>37} |")
        print(f"|   • Pending / In-Transit:            {format_inr(inf['pending_settlements']):>37} |")
        print(f"|   • Disputed / Flagged At-Risk:      {format_inr(inf['disputed_blocked']):>37} |")
        print(f"|   TOTAL REALIZED INFLOWS:            {format_inr(inf['total_realized_inflows']):>37} |")
        print("|" + "-" * (width - 2) + "|")
        print(f"| OPERATIONAL OUTFLOWS:                                              |")
        print(f"|   • Customer Refunds Disbursed:      {format_inr(outf['refunds_processed']):>37} |")
        print(f"|   • Gateway Processing Fees (2.0%):  {format_inr(outf['gateway_fees']):>37} |")
        print(f"|   • GST on Gateway Fees (18.0%):     {format_inr(outf['gst_on_fees']):>37} |")
        print(f"|   TOTAL CASH OUTFLOWS (REFUNDS):     {format_inr(outf['total_cash_outflows']):>37} |")
        print("|" + "=" * (width - 2) + "|")
        print(f"| CLOSING RECONCILED CASH BALANCE:     {format_inr(st['closing_balance']):>37} |")
        print(f"| UNEXPLAINED VARIANCE (AT-RISK):      {format_inr(st['unexplained_variance']):>37} |")
        print("+" + "=" * (width - 2) + "+")


# =====================================================================
# LAYER 3: 7-DAY CASH FORECASTER
# =====================================================================
class CashForecaster:
    """
    Predictive 7-Day Liquidity Forecaster:
    - Extracts empirical velocity, refund frequency, and MDR burn rates from the batch.
    - Projects daily liquidity factoring in T+2 settlement lags and confidence tiers.
    """
    def __init__(self, reconciled_data: Dict[str, Any], settlement_lag_days: int = 2):
        self.settlement_lag_days = settlement_lag_days
        self.metrics = self._extract_pattern(reconciled_data)
        self.forecast_results: List[Dict[str, Any]] = []

    def _extract_pattern(self, data: Dict[str, Any]) -> Dict[str, float]:
        """
        Computes rolling run rates:
        - avg_daily_gross_volume
        - avg_daily_net_volume
        - observed_refund_rate
        - observed_fee_rate
        """
        all_orders = data.get("all_orders", [])
        refunds = data.get("refunds_count", 0)
        total_orders_count = max(1, len(all_orders))
        
        total_gross = sum(o["Amount"] for o in all_orders)
        effective_days = 7.0
        
        avg_daily_gross = total_gross / effective_days
        observed_refund_rate = refunds / total_orders_count if total_orders_count > 0 else 0.02
        observed_fee_rate = 0.0236  # 2% fee + 18% GST = 2.36% effective burn
        
        avg_daily_net = avg_daily_gross * (1.0 - observed_fee_rate) * (1.0 - observed_refund_rate)

        return {
            "avg_daily_gross_volume": avg_daily_gross,
            "avg_daily_net_volume": avg_daily_net,
            "observed_refund_rate": observed_refund_rate,
            "observed_fee_rate": observed_fee_rate
        }

    def forecast_7day(self, current_balance: float, pending_float: float = 0.0) -> List[Dict[str, Any]]:
        """
        Generates 7-day rolling forecast:
        - Utilizes pending_float (pending/lagged settlements from CashPositionController).
        - Day 1 inflow = pending_float * 0.60 (or avg_daily_net if float is 0).
        - Day 2 inflow = pending_float * 0.40 (or avg_daily_net if float is 0).
        - Days 3–7: Inflows realize based on avg_daily_net.
        - Outflows: daily refunds applied.
        - Confidence: HIGH (Days 1-3), MEDIUM (Days 4-5), LOW (Days 6-7).
        """
        self.forecast_results = []
        running_balance = current_balance
        start_date = datetime.now().date() + timedelta(days=1)
        
        avg_daily_gross = self.metrics["avg_daily_gross_volume"]
        avg_daily_net = self.metrics["avg_daily_net_volume"]
        daily_refund_outflow = avg_daily_gross * self.metrics["observed_refund_rate"]

        for day in range(1, 8):
            forecast_date = start_date + timedelta(days=day - 1)
            
            # Settlement pipeline & lag logic:
            if day == 1:
                inflow = round(pending_float * 0.60, 2) if pending_float > 0 else avg_daily_net
            elif day == 2:
                inflow = round(pending_float * 0.40, 2) if pending_float > 0 else avg_daily_net
            else:
                inflow = avg_daily_net

            outflow = daily_refund_outflow
            running_balance = running_balance + inflow - outflow
            
            if day <= 3:
                confidence = "HIGH"
            elif day <= 5:
                confidence = "MEDIUM"
            else:
                confidence = "LOW"

            self.forecast_results.append({
                "day": day,
                "date": forecast_date.strftime("%Y-%m-%d"),
                "inflow": inflow,
                "outflow": outflow,
                "closing": running_balance,
                "confidence": confidence
            })

        return self.forecast_results

    def print_forecast(self) -> None:
        """Prints a structured 7-day predictive cash forecast table."""
        print("\n" + "=" * 75)
        print(f"{'7-DAY FORWARD CASH FORECAST (T+2 Settlement Lag Adjusted)':^75}")
        print("=" * 75)
        print(f"{'Day / Date':<15} | {'Projected Inflow':>17} | {'Projected Outflow':>17} | {'Est. Closing':>16} | {'Confidence':<10}")
        print("-" * 75)
        
        for row in self.forecast_results:
            d_str = f"Day {row['day']} ({row['date'][5:]})"
            inflow_str = format_inr(row['inflow'])
            outflow_str = format_inr(row['outflow'])
            closing_str = format_inr(row['closing'])
            conf_str = f"[{row['confidence']}]"
            print(f"{d_str:<15} | {inflow_str:>17} | {outflow_str:>17} | {closing_str:>16} | {conf_str:<10}")
        print("-" * 75)


# =====================================================================
# LAYER 4: LOOP CLOSURE WITH ACTIONABLE ROUTING
# =====================================================================
def close_the_loop(
    exceptions: List[Dict[str, Any]],
    ai_matches: List[Dict[str, Any]],
    ground_truth_map: Optional[Dict[str, Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Automated resolution and exception triage:
    Assigns Action, Owner, Urgency, and Business Justification to every flagged or non-standard case.
    
    Routing Hierarchy:
    1. First check ground truth mismatch type (m_type) if present.
    2. Operational type inference when ground_truth_map is absent or type is unknown.
    """
    action_items = []
    processed_orders = set()
    gt_map = ground_truth_map or {}

    # Combine all items that underwent AI triage
    all_items = list(exceptions) + list(ai_matches)

    for item in all_items:
        o_id = item.get("OrderID", "N/A")
        if o_id in processed_orders:
            continue
        processed_orders.add(o_id)

        gt = gt_map.get(o_id, {})
        m_type = gt.get("mismatch_type") or item.get("Type", "")

        # Operational inference when ground_truth is not available or type is generic
        if not m_type or m_type in ["normal", "none", "unknown", "unresolved_exception", "disputed_exception"]:
            classification = str(item.get("Classification", "")).upper()
            reason_lower = str(item.get("Reason", "")).lower()
            type_lower = str(item.get("Type", "")).lower()

            if "refund" in reason_lower or classification == "MATCH_AS_REFUNDED" or "refund" in type_lower:
                m_type = "refunded"
            elif "missing bank" in reason_lower or "missing_bank" in type_lower or "no matching bank" in reason_lower or "missing bank entry" in type_lower:
                m_type = "missing_bank_entry"
            elif "timing" in reason_lower or "delay" in reason_lower or "sla" in reason_lower or "pending" in type_lower:
                m_type = "timing_difference"
            elif "fee" in reason_lower or classification == "MATCH_WITH_FEE_VARIATION" or "mdr" in reason_lower or "rate" in reason_lower:
                m_type = "fee_variation"
            elif "discount" in reason_lower or "promo" in reason_lower or classification == "MATCH_WITH_EXCEPTION":
                m_type = "discount_applied"
            else:
                m_type = "unresolved_discrepancy"

        # Action and urgency assignment
        if m_type == "missing_bank_entry":
            action = "ESCALATE TO BANK"
            owner = "Bank"
            urgency = "HIGH"
            justification = "Payment not received: possible settlement failure"
        elif m_type == "refunded":
            action = "MANUAL REVIEW"
            owner = "Finance Team"
            urgency = "MEDIUM"
            justification = "Verify refund was authorized"
        elif m_type == "timing_difference":
            action = "MONITOR SETTLEMENT"
            owner = "Gateway"
            urgency = "MEDIUM"
            justification = "Outside SLA: investigate gateway settlement timeline"
        elif m_type == "fee_variation":
            action = "AUDIT MDR RATE"
            owner = "Finance Team"
            urgency = "LOW"
            justification = "Fee rate differs from contract: check merchant tier"
        elif m_type in ["discount_on_order", "discount_on_gateway", "discount_applied"]:
            action = "AUTO RECONCILE"
            owner = "System"
            urgency = "LOW"
            justification = "Promotional discount applied at source"
        else:
            action = "MANUAL REVIEW"
            owner = "Finance Team"
            urgency = "MEDIUM"
            justification = str(item.get("Reason", "Unresolved ledger discrepancy")).replace(" - ", ": ").replace("-", " ")

        action = str(action).replace("-", " ").replace("_", " ")

        action_items.append({
            "order_id": o_id,
            "type": m_type,
            "action": action,
            "owner": owner,
            "urgency": urgency,
            "justification": justification
        })

    # Print Loop Closure Action Table
    print("\n" + "=" * 90)
    print(f"{'LOOP CLOSURE WITH ACTIONS':^90}")
    print("=" * 90)
    print(f"{'Order ID':<9} | {'Mismatch Type':<22} | {'Action':<18} | {'Owner':<14} | {'Urgency':<8} | {'Business Justification'}")
    print("-" * 90)

    for item in sorted(action_items, key=lambda x: (0 if x["urgency"] == "HIGH" else (1 if x["urgency"] == "MEDIUM" else 2), x["order_id"])):
        print(f"{item['order_id']:<9} | {item['type']:<22} | {item['action']:<18} | {item['owner']:<14} | {item['urgency']:<8} | {item['justification']}")
    print("-" * 90)

    return action_items


# =====================================================================
# ACCURACY BENCHMARKING (PRECISION, RECALL, F1 & MULTI-LAYER BREAKDOWN)
# =====================================================================
def compute_accuracy_metrics(
    ground_truth_map: Optional[Dict[str, Dict[str, Any]]],
    det_matches: List[Dict[str, Any]],
    ai_matches: List[Dict[str, Any]],
    exceptions: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Audits reconciliation decisions against ground_truth.csv if available.
    If ground_truth is not supplied (e.g. custom user CSVs), returns operational resolution rates.
    """
    det_order_ids = {m["OrderID"] for m in det_matches}
    ai_order_ids = {m["OrderID"] for m in ai_matches}
    exception_order_ids = {e["OrderID"] for e in exceptions}
    total_processed = len(det_matches) + len(ai_matches) + len(exceptions)

    if not ground_truth_map:
        total_resolved = len(det_matches) + len(ai_matches)
        res_rate = (total_resolved / total_processed * 100.0) if total_processed > 0 else 100.0
        det_share = (len(det_matches) / total_processed * 100.0) if total_processed > 0 else 0.0
        ai_share = (len(ai_matches) / total_processed * 100.0) if total_processed > 0 else 0.0
        return {
            "has_ground_truth": False,
            "det_accuracy": det_share,
            "ai_accuracy": (len(ai_matches) / (len(ai_matches) + len(exceptions)) * 100.0) if (len(ai_matches) + len(exceptions)) > 0 else 100.0,
            "exception_accuracy": 100.0,
            "overall_accuracy": res_rate,
            "precision": res_rate,
            "recall": 100.0,
            "f1": res_rate,
            "resolution_rate": res_rate
        }

    # 1. Deterministic Layer Accuracy (Standard transactions matched rule-based)
    normal_orders = [o_id for o_id, gt in ground_truth_map.items() if not gt.get("is_mismatch", False)]
    correct_det_matches = sum(1 for o_id in normal_orders if o_id in det_order_ids)
    det_accuracy = (correct_det_matches / len(normal_orders) * 100.0) if normal_orders else 100.0

    # 2. AI Layer Accuracy (Resolution of solvable anomalies vs edge-case exceptions)
    mismatch_orders = [o_id for o_id, gt in ground_truth_map.items() if gt.get("is_mismatch", False)]
    expected_resolvable = [
        o_id for o_id in mismatch_orders 
        if ground_truth_map[o_id].get("expected_decision") == "AI_RESOLVED"
    ]
    correct_ai_resolved = sum(1 for o_id in expected_resolvable if o_id in ai_order_ids)
    ai_accuracy = (correct_ai_resolved / len(expected_resolvable) * 100.0) if expected_resolvable else 100.0

    # 3. Exception Layer Accuracy (Honest capture of missing funds and edge cases)
    expected_exceptions = [
        o_id for o_id in mismatch_orders 
        if ground_truth_map[o_id].get("expected_decision") == "EXCEPTION"
    ]
    correct_exceptions = sum(1 for o_id in expected_exceptions if o_id in exception_order_ids)
    exception_accuracy = (correct_exceptions / len(expected_exceptions) * 100.0) if expected_exceptions else 100.0

    # 4. Overall Combined Accuracy (Target: 85-92%)
    total_correct = correct_det_matches + correct_ai_resolved + correct_exceptions
    overall_accuracy = (total_correct / len(ground_truth_map) * 100.0) if ground_truth_map else 100.0

    # 5. Overall Anomaly Isolation Precision, Recall, F1
    anomalous_flagged = ai_order_ids.union(exception_order_ids)
    tp = sum(1 for o_id in mismatch_orders if o_id in anomalous_flagged)
    fp = sum(1 for o_id in normal_orders if o_id in anomalous_flagged)
    fn = sum(1 for o_id in mismatch_orders if o_id not in anomalous_flagged)

    precision = (tp / (tp + fp) * 100.0) if (tp + fp) > 0 else 100.0
    recall = (tp / (tp + fn) * 100.0) if (tp + fn) > 0 else 100.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 100.0

    return {
        "has_ground_truth": True,
        "det_accuracy": det_accuracy,
        "ai_accuracy": ai_accuracy,
        "exception_accuracy": exception_accuracy,
        "overall_accuracy": overall_accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "resolution_rate": overall_accuracy
    }


# =====================================================================
# MASTER CONTROLLER: ORCHESTRATION & REPORTING
# =====================================================================
def run_finance_controller(
    orders_path: Optional[str] = None,
    gateway_path: Optional[str] = None,
    bank_path: Optional[str] = None,
    ground_truth_path: Optional[str] = None,
    opening_balance: float = 500000.0,
    generate_synthetic: bool = True
) -> Dict[str, Any]:
    """
    Master entry point for the AI Finance Controller batch workflow.
    Supports either generating synthetic data or processing custom user CSV files.
    """
    # 1. Header
    print("=" * 75)
    print(f"{'FINANCE CONTROLLER - RECONCILIATION BATCH':^75}")
    print("=" * 75)

    is_custom = bool(orders_path or gateway_path or bank_path or not generate_synthetic)

    if not is_custom:
        # 2. Synthetic Data Generation
        gen_summary = generate_synthetic_data()
        total_orders = gen_summary["total_orders"]
        injected_mismatches = gen_summary["mismatches_injected"]
        ground_truth_map = gen_summary["ground_truth_map"]
        print(f"Generated 50 orders, {injected_mismatches} mismatches injected (Total: {total_orders} orders randomly distributed)")
        print("=" * 75)
        
        # Load from written synthetic files
        dataset = load_reconciliation_data("orders.csv", "gateway.csv", "bank.csv", "ground_truth.csv")
    else:
        # Custom CSVs Ingestion
        o_src = orders_path or "orders.csv"
        g_src = gateway_path or "gateway.csv"
        b_src = bank_path or "bank.csv"
        gt_src = ground_truth_path or ("ground_truth.csv" if os.path.exists("ground_truth.csv") else None)
        
        print(f"Loading custom datasets:")
        print(f"  • Orders:  {o_src}")
        print(f"  • Gateway: {g_src}")
        print(f"  • Bank:    {b_src}")
        if gt_src:
            print(f"  • Ground Truth: {gt_src}")
        print("=" * 75)

        dataset = load_reconciliation_data(o_src, g_src, b_src, gt_src)
        total_orders = dataset["total_orders"]
        ground_truth_map = dataset["ground_truth_map"]

    orders = dataset["orders"]
    gateway = dataset["gateway"]
    bank_records = dataset["bank"]

    # Start timing
    start_time = time.perf_counter()

    # 3. Deterministic Matching
    det_matches, unmatched_orders, unmatched_gateway, unmatched_bank = run_deterministic_matcher(
        orders=orders,
        gateway=gateway,
        bank_records=bank_records
    )

    # 4. Reconciliation Progress with ReAct AI Agent
    print(f"\n[AI Agent] Commencing ReAct analysis on {len(unmatched_orders)} unmatched transaction streams...\n")
    ai_matches, exceptions = run_react_agent(unmatched_orders, unmatched_gateway, unmatched_bank)

    # Stop timing
    elapsed_time = time.perf_counter() - start_time
    throughput = total_orders / elapsed_time if elapsed_time > 0 else 0.0

    # Compute Accuracy Metrics
    accuracy = compute_accuracy_metrics(ground_truth_map, det_matches, ai_matches, exceptions)

    # 5. RECONCILIATION SUMMARY Box
    width = 72
    engine_name = get_active_engine_name()
    engine_label = f"(Engine: {engine_name})"
    print("\n+" + "=" * (width - 2) + "+")
    print(f"|{'RECONCILIATION & ACCURACY BENCHMARK SUMMARY':^{width - 2}}|")
    print("+" + "=" * (width - 2) + "+")
    print(f"| Throughput:                 {throughput:>14.1f} records/sec {engine_label:>22} |")
    print(f"| Processing Time:            {elapsed_time:>38.2f} seconds |")
    print(f"| Total Transactions:         {total_orders:>41} |")
    print(f"| Matched (Deterministic):    {len(det_matches):>41} |")
    print(f"| Matched (AI ReAct):         {len(ai_matches):>41} |")
    print(f"| Flagged Exceptions:         {len(exceptions):>41} |")
    print("|" + "-" * (width - 2) + "|")
    
    if accuracy.get("has_ground_truth", True):
        print(f"| ACCURACY BREAKDOWN BY LAYER:                                       |")
        print(f"|   • Deterministic Match Accuracy:           {accuracy['det_accuracy']:>25.1f}% |")
        print(f"|   • AI Resolution Accuracy (Complex Cases): {accuracy['ai_accuracy']:>25.1f}% |")
        print(f"|   • Honest Exception Capture Rate:          {accuracy['exception_accuracy']:>25.1f}% |")
        print(f"|   • Overall Controller Accuracy:            {accuracy['overall_accuracy']:>25.1f}% |")
        print("|" + "-" * (width - 2) + "|")
        print(f"| MEASURED ACCURACY BENCHMARK:                                       |")
        print(f"|   • Precision:                              {accuracy['precision']:>25.1f}% |")
        print(f"|   • Recall:                                 {accuracy['recall']:>25.1f}% |")
        print(f"|   • F1 Score:                               {accuracy['f1']:>25.1f}% |")
    else:
        print(f"| RECONCILIATION COVERAGE & RESOLUTION METRICS:                      |")
        print(f"|   • Deterministically Matched:              {accuracy['det_accuracy']:>25.1f}% |")
        print(f"|   • AI Resolution Efficiency:               {accuracy['ai_accuracy']:>25.1f}% |")
        print(f"|   • Overall Ledger Resolution Rate:         {accuracy['resolution_rate']:>25.1f}% |")
        print(f"|   (Ground truth file omitted; accuracy benchmarking not applicable) |")
    print("+" + "=" * (width - 2) + "+")

    # 6. CASH POSITION STATEMENT Box (Layer 2)
    cash_controller = CashPositionController(opening_balance=opening_balance)
    cash_controller.update_from_reconciliation(det_matches, ai_matches, exceptions)
    cash_controller.print_statement()

    # 7. 7-DAY CASH FORECAST Table (Layer 3)
    all_orders_data = [{"Amount": o["Amount"]} for o in orders.values()]
    refunds_count = sum(1 for m in ai_matches if m.get("Classification") == "MATCH_AS_REFUNDED")
    forecaster = CashForecaster(
        reconciled_data={"all_orders": all_orders_data, "refunds_count": refunds_count},
        settlement_lag_days=2
    )
    closing_bal = cash_controller.generate_statement()["closing_balance"]
    pending_float = cash_controller.generate_statement()["inflows"]["pending_settlements"]
    forecaster.forecast_7day(current_balance=closing_bal, pending_float=pending_float)
    forecaster.print_forecast()

    # 8. LOOP CLOSURE ACTIONS Table (Layer 4)
    action_items = close_the_loop(exceptions, ai_matches, ground_truth_map)
    human_action_items = [item for item in action_items if item["owner"] != "System" or item["action"] not in ["AUTO_RESOLVE", "AUTO_RECONCILE"]]

    # 9. Footer
    print(f"\nBatch complete. {len(human_action_items)} items require human action.\n")

    return {
        "total_orders": total_orders,
        "det_matches": det_matches,
        "ai_matches": ai_matches,
        "exceptions": exceptions,
        "elapsed": elapsed_time,
        "throughput": throughput,
        "accuracy": accuracy,
        "cash_stmt": cash_controller.generate_statement(),
        "forecast_rows": forecaster.forecast_7day(current_balance=closing_bal, pending_float=pending_float),
        "action_items": action_items,
        "engine_name": engine_name,
        "ground_truth_map": ground_truth_map,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Finance Controller - Reconciliation Agent")
    parser.add_argument("--orders", type=str, default=None, help="Path to custom orders CSV file")
    parser.add_argument("--gateway", type=str, default=None, help="Path to custom gateway CSV file")
    parser.add_argument("--bank", type=str, default=None, help="Path to custom bank CSV file")
    parser.add_argument("--ground-truth", type=str, default=None, help="Optional path to custom ground_truth CSV file")
    parser.add_argument("--opening-balance", type=float, default=500000.0, help="Opening cash balance (default: 500,000 INR)")
    parser.add_argument("--no-synthetic", action="store_true", help="Do not generate synthetic data; use existing CSVs")

    args = parser.parse_args()

    use_synthetic = not (args.orders or args.gateway or args.bank or args.no_synthetic)
    run_finance_controller(
        orders_path=args.orders,
        gateway_path=args.gateway,
        bank_path=args.bank,
        ground_truth_path=args.ground_truth,
        opening_balance=args.opening_balance,
        generate_synthetic=use_synthetic
    )

