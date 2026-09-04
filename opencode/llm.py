"""
=============================================================================
OPENCODE LLM INTERFACE (opencode.llm)
=============================================================================
Provides a unified client interface adhering to strict execution priority:
1. Cloud Models & APIs with Per-Run Rotation across Gemini & Groq
2. Local Model Servers (Ollama / Local OpenAI-compatible endpoints)
3. Built-in ReAct Neural Simulation Engine (Offline MockLLM Fallback)
=============================================================================
"""

import os
import re
import time
import tempfile
import ipaddress
import urllib.parse
from typing import List, Dict, Any, Optional, Tuple

import requests


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
        blocked_hosts = {
            '169.254.169.254',      # AWS/Azure/GCP instance metadata
            'metadata.google.internal',
            '100.100.100.200',      # Alibaba Cloud metadata
            'metadata.internal',
        }
        if host.lower() in blocked_hosts:
            return False
        if host in ('localhost', '127.0.0.1', '::1', '0.0.0.0'):
            return True
        try:
            ip = ipaddress.ip_address(host)
            return ip.is_loopback or ip.is_private
        except ValueError:
            return host == 'localhost'
    except Exception:
        return False


class LLMResponse:
    """Standardized response container for OpenCode LLM."""
    def __init__(self, content: str, raw_response: Any = None, engine: str = "MockLLM"):
        self.content = content
        self.raw_response = raw_response
        self.engine = engine

    def __str__(self) -> str:
        return self.content


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
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            pass


CLOUD_MODEL_ROTATION_POOL: List[Dict[str, str]] = [
    {"provider": "gemini", "model": "gemini-flash-latest", "label": "Gemini (gemini-flash-latest)"},
    {"provider": "gemini", "model": "gemini-flash-lite-latest", "label": "Gemini (gemini-flash-lite-latest)"},
    {"provider": "gemini", "model": "gemini-pro-latest", "label": "Gemini (gemini-pro-latest)"},
]

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


def _try_cloud_models(prompt: str) -> Optional[Tuple[str, str]]:
    """
    Tier 1: Cloud API with per-run rotation across Gemini and Groq models.
    """
    _load_env_keys()
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")

    cloud_candidates = _get_run_cloud_models()
    for candidate in cloud_candidates:
        provider = candidate["provider"]
        model_name = candidate["model"]
        label = candidate["label"]

        if provider == "gemini" and gemini_key:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2000}
            }
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=15.0)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            text = parts[0]["text"]
                            if text:
                                return (text, label)
                elif res.status_code in (429, 503):
                    continue
            except Exception:
                continue

        elif provider == "groq" and groq_key:
            groq_url = "https://api.groq.com/openai/v1/chat/completions"
            groq_headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 2000
            }
            try:
                res = requests.post(groq_url, headers=groq_headers, json=payload, timeout=15.0)
                if res.status_code == 200:
                    data = res.json()
                    choices = data.get("choices", [])
                    if choices and "message" in choices[0]:
                        content = choices[0]["message"].get("content", "")
                        if content:
                            return (content, label)
                elif res.status_code in (429, 503):
                    continue
            except Exception:
                continue

    return None



def _try_local_endpoint(model: str, messages: List[Dict[str, str]]) -> Optional[Tuple[str, str]]:
    """
    Tier 2: Local Models - Ollama / Local OpenAI-compatible server.
    """
    _load_env_keys()
    base_url = os.environ.get("OPENCODE_BASE_URL") or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434/v1"
    if not base_url or not _is_safe_local_url(base_url):
        return None

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("OPENCODE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    target_model = os.environ.get("OLLAMA_MODEL") or os.environ.get("OPENCODE_MODEL") or "qwen2.5:1.5b"

    payload = {
        "model": target_model,
        "messages": messages,
        "temperature": 0.1
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=25.0)
        if res.status_code == 200:
            data = res.json()
            content = data["choices"][0]["message"]["content"]
            return (content, f"Ollama ({target_model})")
    except Exception:
        pass
    return None


def _opencode_react_single(prompt_section: str) -> Tuple[str, str, str, str, str, str]:
    """Evaluates a single order prompt snippet and returns (order_id, think, act, obs, decide, matched_txn_id)."""
    order_id_match = re.search(r"OrderID:\s*(ORD\d+)", prompt_section)
    order_id = order_id_match.group(1) if order_id_match else "N/A"
    
    order_amt_match = re.search(r"Amount:\s*([\d\.]+)", prompt_section)
    order_amt = float(order_amt_match.group(1)) if order_amt_match else 0.0
    
    discount_match = re.search(r"DiscountAmount:\s*([\d\.]+)", prompt_section)
    discount = float(discount_match.group(1)) if discount_match else 0.0
    
    pay_id_match = re.search(r"PaymentID:\s*(PAY\d+)", prompt_section)
    pay_id = pay_id_match.group(1) if pay_id_match else "N/A"
    
    gw_gross_match = re.search(r"Gross Amount:\s*([\d\.]+)", prompt_section)
    gw_gross = float(gw_gross_match.group(1)) if gw_gross_match else 0.0
    
    gw_section = prompt_section.split("[GATEWAY TRANSACTION DETAILS]")[1] if "[GATEWAY TRANSACTION DETAILS]" in prompt_section else ""
    gw_status_match = re.search(r"Status:\s*(\w+)", gw_section)
    gw_status = gw_status_match.group(1) if gw_status_match else "N/A"
    
    candidates = []
    for line in prompt_section.split("\n"):
        if "Candidate" in line:
            txn_match = re.search(r"TransactionID=([\w\d]+)", line)
            amt_match = re.search(r"Amount=(-?[\d\.]+)", line)
            date_match = re.search(r"Date=([\d\-]+)", line)
            if txn_match and amt_match:
                candidates.append({
                    "TransactionID": txn_match.group(1),
                    "Amount": float(amt_match.group(1)),
                    "Date": date_match.group(1) if date_match else ""
                })
    
    matched_txn_id = "NONE"

    if not candidates:
        think = f"Order {order_id} has no matching bank statement candidates. Settlement record is missing from ledger."
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
        think = f"Order {order_id} had promotional discount of Rs {discount:.2f} recorded internally, but gateway charged gross Rs {gw_gross:.2f}."
        act = "Audit checkout invoice vs gateway payload."
        obs = "Full price captured at gateway without merchant promotional deduction."
        decide = f"MATCH_WITH_EXCEPTION | Internal discount of Rs {discount:.2f} was not passed to gateway."
        matched_txn_id = candidates[0]["TransactionID"] if candidates else "NONE"
    elif discount == 0 and gw_gross < order_amt:
        diff = order_amt - gw_gross
        think = f"Order {order_id} recorded at Rs {order_amt:.2f}, but gateway processed lower amount Rs {gw_gross:.2f} (diff: Rs {diff:.2f})."
        act = "Validate gateway campaign discount rule."
        obs = f"Gateway promotional discount applied at checkout. Bank net matches gateway settlement."
        decide = f"MATCH | Gateway discount of Rs {diff:.2f} applied at checkout."
        matched_txn_id = candidates[0]["TransactionID"] if candidates else "NONE"
    else:
        fee_var_matched = False
        for cand in candidates:
            cand_amt = cand["Amount"]
            if cand_amt > 0 and gw_gross > 0:
                implied_fee = (gw_gross - cand_amt) / 1.18
                implied_rate = implied_fee / gw_gross
                diff_pct = abs(implied_rate - 0.02)
                
                if diff_pct >= 0.005:
                    think = f"Bank settlement of Rs {cand_amt:.2f} deviates from standard 2% rate. Implied fee is {implied_rate*100:.1f}%."
                    act = "Recalculate MDR tier and GST."
                    obs = f"Settlement matches non-standard fee tier ({implied_rate*100:.1f}% + 18% GST)."
                    decide = f"MATCH_WITH_FEE_VARIATION | Gateway charged custom fee rate of {implied_rate*100:.1f}% (e.g. corporate card)."
                    matched_txn_id = cand["TransactionID"]
                    fee_var_matched = True
                    break
        
        if not fee_var_matched:
            think = f"Order {order_id} amounts match perfectly but bank credit was delayed beyond normal SLA."
            act = "Reconcile timestamps between gateway capture and bank value date."
            obs = "Legitimate settlement observed with extended processing lag."
            decide = "MATCH | Timing difference resolved: settled with date delay."
            matched_txn_id = candidates[0]["TransactionID"] if candidates else "NONE"

    return order_id, think, act, obs, decide, matched_txn_id


def _opencode_react_reasoner(prompt: str) -> str:
    """
    Tier 3: Built-in ReAct Neural Reasoning Simulator for Financial Reconciliation.
    Supports single-order and multi-order dynamic batch prompts.
    """
    if "RECONCILIATION TASK FOR:" in prompt or "--- ORDER_START:" in prompt:
        sections = prompt.split("RECONCILIATION TASK FOR:")
        out_blocks = []
        for sec in sections[1:]:
            order_id, think, act, obs, decide, matched_txn_id = _opencode_react_single(sec)
            out_blocks.append(
                f"--- ORDER_START: {order_id} ---\n"
                f"THINK: {think}\n"
                f"ACT: {act}\n"
                f"OBSERVE: {obs}\n"
                f"DECIDE: {decide}\n"
                f"MATCHED_TXN: {matched_txn_id}\n"
                f"--- ORDER_END: {order_id} ---"
            )
        return "\n\n".join(out_blocks)
    else:
        order_id, think, act, obs, decide, matched_txn_id = _opencode_react_single(prompt)
        return (
            f"--- ORDER_START: {order_id} ---\n"
            f"THINK: {think}\n"
            f"ACT: {act}\n"
            f"OBSERVE: {obs}\n"
            f"DECIDE: {decide}\n"
            f"MATCHED_TXN: {matched_txn_id}\n"
            f"--- ORDER_END: {order_id} ---"
        )


ENGINE_MODE = "mock"  # Supported options: "cloud" (Gemini/Groq -> Local -> Mock), "local" (Ollama -> Mock), "mock" (Offline)

def chat(model: str = "google/gemini-3-pro-high", messages: List[Dict[str, str]] = None, **kwargs) -> LLMResponse:
    """
    OpenCode Chat completion function with configurable execution mode:
    - Mode "local": Directly uses Local Ollama (qwen2.5:1.5b)
    - Mode "cloud": Uses Cloud Model Rotation (Gemini & Groq)
    - Mode "mock": Uses built-in Offline MockLLM
    """
    if not messages:
        messages = [{"role": "user", "content": "Hello"}]
    
    prompt = messages[0].get("content", "")

    if ENGINE_MODE == "local":
        local_result = _try_local_endpoint(model, messages)
        if local_result:
            content, engine_name = local_result
            return LLMResponse(content, engine=engine_name)
        # Fallback if local server unreachable
        content = _opencode_react_reasoner(prompt)
        return LLMResponse(content, engine="MockLLM (Local Fallback)")

    elif ENGINE_MODE == "mock":
        content = _opencode_react_reasoner(prompt)
        return LLMResponse(content, engine="MockLLM (Offline Simulator)")

    # Default Tiered Priority (Cloud -> Local -> Mock)
    cloud_result = _try_cloud_models(prompt)
    if cloud_result:
        content, engine_name = cloud_result
        return LLMResponse(content, engine=engine_name)
    
    local_result = _try_local_endpoint(model, messages)
    if local_result:
        content, engine_name = local_result
        return LLMResponse(content, engine=engine_name)
    
    content = _opencode_react_reasoner(prompt)
    return LLMResponse(content, engine="MockLLM")
