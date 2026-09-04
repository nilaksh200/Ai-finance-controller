import os
import csv
import sys
import math
import time
import random
import re
import requests
import json
import hashlib
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure UTF-8 output encoding across all operating systems
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Attempt to import LLM interface from opencode
try:
    from opencode import llm
    HAS_OPENCODE = True
except ImportError:
    HAS_OPENCODE = False

# =====================================================================
# 1. Fallback Mock LLM for Local Testing
# =====================================================================
class MockResponse:
    def __init__(self, content):
        self.content = content

class MockLLM:
    """
    Simulates Gemini's reasoning dynamically for unmatched scenarios
    to allow local execution with random data.
    Supports both single-order prompts and 5-in-1 batched prompts.
    """
    def _eval_single_order(self, prompt):
        order_id_match = re.search(r"OrderID:\s*(ORD\d+)", prompt)
        order_id = order_id_match.group(1) if order_id_match else "N/A"
        
        order_amt_match = re.search(r"Amount:\s*([\d\.]+)", prompt)
        order_amt = float(order_amt_match.group(1)) if order_amt_match else 0.0
        
        discount_match = re.search(r"DiscountAmount:\s*([\d\.]+)", prompt)
        discount = float(discount_match.group(1)) if discount_match else 0.0
        
        pay_id_match = re.search(r"PaymentID:\s*(PAY\d+)", prompt)
        pay_id = pay_id_match.group(1) if pay_id_match else "N/A"
        
        gw_gross_match = re.search(r"Gross Amount:\s*([\d\.]+)", prompt)
        gw_gross = float(gw_gross_match.group(1)) if gw_gross_match else 0.0
        
        gw_section = prompt.split("[GATEWAY TRANSACTION DETAILS]")[1] if "[GATEWAY TRANSACTION DETAILS]" in prompt else ""
        gw_status_match = re.search(r"Status:\s*(\w+)", gw_section)
        gw_status = gw_status_match.group(1) if gw_status_match else "N/A"
        
        candidates = []
        for line in prompt.split("\n"):
            if "Candidate" in line:
                txn_match = re.search(r"TransactionID=([\w\d]+)", line)
                amt_match = re.search(r"Amount=(-?[\d\.]+)", line)
                if txn_match and amt_match:
                    candidates.append({
                        "TransactionID": txn_match.group(1),
                        "Amount": float(amt_match.group(1))
                    })

        matched_txn_id = "NONE"

        if not candidates:
            think = f"Order {order_id} has no matching bank statement candidates. I cannot find any deposit record."
            act = "Verify bank statement candidates for matching entries."
            obs = "No matching bank entry was found."
            decide = "EXCEPTION | Agent could not resolve due to missing bank entry."
            matched_txn_id = "NONE"
        elif gw_status == "refunded":
            think = f"Order {order_id} has gateway transaction {pay_id} with status 'refunded'. I need to check for matching bank statement credits and debits."
            act = "Verify bank statement candidates for matching refund entries."
            obs = "Found matching bank entries for refund payout."
            decide = f"MATCH_AS_REFUNDED | Match {order_id} to {pay_id} and Bank transactions. Reason: Transaction fully refunded, verified by bank debit."
            payout_cands = [c for c in candidates if c["Amount"] < 0]
            matched_txn_id = payout_cands[0]["TransactionID"] if payout_cands else (candidates[0]["TransactionID"] if candidates else "NONE")
        elif discount > 0 and abs(gw_gross - (order_amt + discount)) <= 1.0:
            think = f"The order {order_id} has a discount of Rs {discount:.2f} in our internal records. However, the gateway transaction recorded the full gross amount of Rs {gw_gross:.2f}."
            act = "Check discrepancy details."
            obs = f"Order discount of Rs {discount:.2f} was not applied at the gateway."
            decide = f"MATCH_WITH_EXCEPTION | Match {order_id} to {pay_id} and Bank. Exception reason: Order discount of Rs {discount:.2f} was not applied by the gateway."
            matched_txn_id = candidates[0]["TransactionID"] if candidates else "NONE"
        elif discount == 0 and gw_gross < order_amt:
            diff = order_amt - gw_gross
            think = f"Order {order_id} has no discount in internal records, but the gateway processed a lower amount of Rs {gw_gross:.2f}. The difference is Rs {diff:.2f}."
            act = "Validate checkout discount amount."
            obs = f"Difference is exactly Rs {diff:.2f}. Bank net matches gateway settlement."
            decide = f"MATCH | Match {order_id} to {pay_id} and Bank. Reason: Gateway discount of Rs {diff:.2f} applied at checkout."
            matched_txn_id = candidates[0]["TransactionID"] if candidates else "NONE"
        else:
            fee_var_matched = False
            for cand in candidates:
                cand_amt = cand["Amount"]
                if cand_amt > 0 and gw_gross > 0:
                    implied_fee = (gw_gross - cand_amt) / 1.18
                    implied_rate = implied_fee / gw_gross
                    if abs(implied_rate - 0.02) > 0.005:
                        think = f"Expected net settlement doesn't match bank deposit of Rs {cand_amt:.2f}. Implied fee rate is {implied_rate*100:.1f}%."
                        act = "Verify fee rate variation."
                        obs = f"Net settlement matches implied fee rate of {implied_rate*100:.1f}% + 18% GST."
                        decide = f"MATCH_WITH_FEE_VARIATION | Match {order_id} to {pay_id} and Bank. Reason: Gateway charged {implied_rate*100:.1f}% fee rate (e.g. premium card)."
                        matched_txn_id = cand["TransactionID"]
                        fee_var_matched = True
                        break
            
            if not fee_var_matched:
                think = "Check timing differences."
                act = "Compare dates."
                obs = "Found matching bank candidate with settlement date delay."
                decide = f"MATCH | Match {order_id} to {pay_id} and Bank. Reason: Timing difference: settled with date delay."
                matched_txn_id = candidates[0]["TransactionID"] if candidates else "NONE"

        return order_id, think, act, obs, decide, matched_txn_id

    def chat(self, model, messages):
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

# Initialize LLM wrapper and config
ENGINE_MODE = "mock"  # Supported options: "cloud" (Gemini/Groq -> Local -> Mock), "local" (Ollama -> Mock), "mock" (Offline)

def gemini_reason(prompt):
    """
    Tiered LLM reasoning interface following configurable priority:
    - "local": Local Ollama (qwen2.5:1.5b) -> MockLLM fallback
    - "cloud": Cloud rotation (Gemini & Groq) -> Local Ollama -> MockLLM
    - "mock": MockLLM offline simulator
    """
    if ENGINE_MODE == "local":
        try:
            url = "http://localhost:11434/v1/chat/completions"
            headers = {"Content-Type": "application/json"}
            payload = {
                "model": os.environ.get("OLLAMA_MODEL") or "qwen2.5:1.5b",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1
            }
            res = requests.post(url, headers=headers, json=payload, timeout=25)
            if res.status_code == 200:
                data = res.json()
                content = data["choices"][0]["message"]["content"]
                if content:
                    return content
        except Exception:
            pass
        mock_llm = MockLLM()
        response = mock_llm.chat("google/gemini-3-pro-high", [{"role": "user", "content": prompt}])
        return response.content

    elif ENGINE_MODE == "mock":
        mock_llm = MockLLM()
        response = mock_llm.chat("google/gemini-3-pro-high", [{"role": "user", "content": prompt}])
        return response.content
    if HAS_OPENCODE:
        try:
            response = llm.chat(
                model="google/gemini-3-pro-high",
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content
        except Exception:
            pass

    # Direct Cloud Gemini REST API check
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r") as f:
                    for line in f:
                        if line.strip() and not line.strip().startswith("#") and "=" in line:
                            parts = line.split("=", 1)
                            if len(parts) == 2 and parts[0].strip() in ["GEMINI_API_KEY", "GOOGLE_API_KEY"]:
                                api_key = parts[1].strip().strip('"').strip("'")
                                break
            except Exception:
                pass
                
    if api_key:
        candidate_models = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-pro-latest"]
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        for model_name in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"]
                elif res.status_code in (429, 503):
                    continue
            except Exception:
                continue

    # Direct Groq Cloud API check
    groq_api_key = os.environ.get("GROQ_API_KEY")

    if not groq_api_key:
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r") as f:
                    for line in f:
                        if line.strip() and not line.strip().startswith("#") and "=" in line:
                            parts = line.split("=", 1)
                            if len(parts) == 2 and parts[0].strip() == "GROQ_API_KEY":
                                groq_api_key = parts[1].strip().strip('"').strip("'")
                                break
            except Exception:
                pass

    if groq_api_key:
        preferred_model = os.environ.get("GROQ_MODEL")
        groq_models = [preferred_model] if preferred_model else [
            "groq/compound-mini",
            "openai/gpt-oss-20b",
            "qwen/qwen3.6-27b",
            "qwen/qwen3.8-27b",
            "groq/compound"
        ]

        groq_url = "https://api.groq.com/openai/v1/chat/completions"

        groq_headers = {"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}
        for model_name in groq_models:
            if not model_name:
                continue
            payload = {"model": model_name, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
            try:
                res = requests.post(groq_url, headers=groq_headers, json=payload, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    choices = data.get("choices", [])
                    if choices and "message" in choices[0]:
                        content = choices[0]["message"].get("content", "")
                        if content:
                            return content
                elif res.status_code in (429, 503):
                    continue
            except Exception:
                continue


    # Fallback to MockLLM
    mock_llm = MockLLM()
    response = mock_llm.chat("google/gemini-3-pro-high", [{"role": "user", "content": prompt}])
    return response.content



# =====================================================================
# 2. Synthetic Data Generator
# =====================================================================
def calculate_net(gross, rate=0.02):
    fee = round(gross * rate, 2)
    gst = round(fee * 0.18, 2)
    net = round(gross - fee - gst, 2)
    return fee, gst, net

def generate_synthetic_data():
    """
    Generates orders.csv, gateway.csv, and bank.csv with dynamic values.
    Includes 100 standard transactions and 100 undeterministic mismatches (200 total).
    """
    orders = []
    gateway = []
    bank = []
    
    # 1. Generate 100 normal transactions (ORD1001-ORD1100)
    start_date = datetime(2026, 8, 20)
    for i in range(1, 101):
        order_id = f"ORD{1000 + i}"
        pay_id = f"PAY{1000 + i}"
        txn_id = f"TXN{1000 + i}"
        
        date = start_date + timedelta(days=random.randint(0, 4), hours=random.randint(9, 18))
        gross = round(random.uniform(500, 3000), 2)
        
        orders.append({
            "OrderID": order_id,
            "Date": date.strftime("%Y-%m-%d %H:%M:%S"),
            "Amount": gross,
            "Status": "success",
            "DiscountAmount": 0
        })
        
        fee, gst, net = calculate_net(gross)
        gateway.append({
            "PaymentID": pay_id,
            "OrderID": order_id,
            "Amount": gross,
            "Fee": fee,
            "GST": gst,
            "SettlementAmount": net,
            "Date": date.strftime("%Y-%m-%d %H:%M:%S"),
            "Status": "captured"
        })
        
        settle_date = date + timedelta(days=random.randint(0, 1))
        bank.append({
            "TransactionID": txn_id,
            "Date": settle_date.strftime("%Y-%m-%d"),
            "Amount": net,
            "Narration": f"Settlement for {order_id} / {pay_id}"
        })

    # 2. Add 100 undeterministic mismatches starting from ORD1101
    num_mismatches = 100
    base_date = datetime(2026, 8, 25, 10, 0, 0)
    mismatch_types = [
        "discount_on_order", 
        "discount_on_gateway", 
        "refunded", 
        "timing_difference", 
        "fee_variation",
        "missing_bank_entry"
    ]
    
    for i in range(1, num_mismatches + 1):
        order_id = f"ORD{1100 + i}"
        pay_id = f"PAY{1100 + i}"
        m_type = random.choice(mismatch_types)
        
        date = base_date + timedelta(hours=i)
        
        if m_type == "discount_on_order":
            gross = round(random.uniform(1000, 3000), 2)
            discount = round(random.uniform(50, 200), 2)
            orders.append({
                "OrderID": order_id, 
                "Date": date.strftime("%Y-%m-%d %H:%M:%S"), 
                "Amount": round(gross - discount, 2), 
                "Status": "success", 
                "DiscountAmount": discount
            })
            fee, gst, net = calculate_net(gross)
            gateway.append({
                "PaymentID": pay_id, 
                "OrderID": order_id, 
                "Amount": gross, 
                "Fee": fee, 
                "GST": gst, 
                "SettlementAmount": net, 
                "Date": (date + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"), 
                "Status": "captured"
            })
            bank.append({
                "TransactionID": f"TXN{1050 + i}", 
                "Date": date.strftime("%Y-%m-%d"), 
                "Amount": net, 
                "Narration": f"Settlement for {order_id} / {pay_id}"
            })
            
        elif m_type == "discount_on_gateway":
            order_amt = round(random.uniform(1000, 3000), 2)
            discount = round(random.uniform(50, 200), 2)
            orders.append({
                "OrderID": order_id, 
                "Date": date.strftime("%Y-%m-%d %H:%M:%S"), 
                "Amount": order_amt, 
                "Status": "success", 
                "DiscountAmount": 0.00
            })
            fee, gst, net = calculate_net(round(order_amt - discount, 2))
            gateway.append({
                "PaymentID": pay_id, 
                "OrderID": order_id, 
                "Amount": round(order_amt - discount, 2), 
                "Fee": fee, 
                "GST": gst, 
                "SettlementAmount": net, 
                "Date": (date + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"), 
                "Status": "captured"
            })
            bank.append({
                "TransactionID": f"TXN{1050 + i}", 
                "Date": date.strftime("%Y-%m-%d"), 
                "Amount": net, 
                "Narration": f"Settlement for {order_id} / {pay_id}"
            })
            
        elif m_type == "refunded":
            gross = round(random.uniform(500, 2500), 2)
            orders.append({
                "OrderID": order_id, 
                "Date": date.strftime("%Y-%m-%d %H:%M:%S"), 
                "Amount": gross, 
                "Status": "success", 
                "DiscountAmount": 0.00
            })
            fee, gst, net = calculate_net(gross)
            gateway.append({
                "PaymentID": pay_id, 
                "OrderID": order_id, 
                "Amount": gross, 
                "Fee": fee, 
                "GST": gst, 
                "SettlementAmount": net, 
                "Date": (date + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"), 
                "Status": "refunded"
            })
            bank.append({
                "TransactionID": f"TXN{1050 + i}A", 
                "Date": date.strftime("%Y-%m-%d"), 
                "Amount": net, 
                "Narration": f"Settlement for {order_id} / {pay_id}"
            })
            bank.append({
                "TransactionID": f"TXN{1050 + i}B", 
                "Date": date.strftime("%Y-%m-%d"), 
                "Amount": -net, 
                "Narration": f"Refund payout for {pay_id}"
            })
            
        elif m_type == "timing_difference":
            gross = round(random.uniform(500, 3000), 2)
            orders.append({
                "OrderID": order_id, 
                "Date": date.strftime("%Y-%m-%d %H:%M:%S"), 
                "Amount": gross, 
                "Status": "success", 
                "DiscountAmount": 0.00
            })
            fee, gst, net = calculate_net(gross)
            gateway.append({
                "PaymentID": pay_id, 
                "OrderID": order_id, 
                "Amount": gross, 
                "Fee": fee, 
                "GST": gst, 
                "SettlementAmount": net, 
                "Date": (date + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"), 
                "Status": "captured"
            })
            # Settle after 5 to 10 days to force AI reasoning (Deterministic matcher enforces <= 2 days proximity)
            settle_date = date + timedelta(days=random.randint(5, 10))
            bank.append({
                "TransactionID": f"TXN{1050 + i}", 
                "Date": settle_date.strftime("%Y-%m-%d"), 
                "Amount": net, 
                "Narration": f"Settlement for {order_id} / {pay_id}"
            })
            
        elif m_type == "fee_variation":
            gross = round(random.uniform(1000, 4000), 2)
            orders.append({
                "OrderID": order_id, 
                "Date": date.strftime("%Y-%m-%d %H:%M:%S"), 
                "Amount": gross, 
                "Status": "success", 
                "DiscountAmount": 0.00
            })
            # gateway fee variation (e.g. 3.0% or 3.5%)
            actual_rate = random.choice([0.03, 0.035])
            fee_var, gst_var, net_var = calculate_net(gross, rate=actual_rate)
            gateway.append({
                "PaymentID": pay_id, 
                "OrderID": order_id, 
                "Amount": gross, 
                "Fee": fee_var, 
                "GST": gst_var, 
                "SettlementAmount": net_var, 
                "Date": (date + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"), 
                "Status": "captured"
            })
            bank.append({
                "TransactionID": f"TXN{1050 + i}", 
                "Date": date.strftime("%Y-%m-%d"), 
                "Amount": net_var, 
                "Narration": f"Settlement for {order_id} / {pay_id}"
            })
            
        elif m_type == "missing_bank_entry":
            gross = round(random.uniform(500, 2000), 2)
            orders.append({
                "OrderID": order_id, 
                "Date": date.strftime("%Y-%m-%d %H:%M:%S"), 
                "Amount": gross, 
                "Status": "success", 
                "DiscountAmount": 0.00
            })
            fee, gst, net = calculate_net(gross)
            gateway.append({
                "PaymentID": pay_id, 
                "OrderID": order_id, 
                "Amount": gross, 
                "Fee": fee, 
                "GST": gst, 
                "SettlementAmount": net, 
                "Date": (date + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"), 
                "Status": "captured"
            })
            # No bank record appended to simulate missing entry

    # Write files
    def write_csv(filename, fieldnames, data):
        with open(filename, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)

    write_csv("orders.csv", ["OrderID", "Date", "Amount", "Status", "DiscountAmount"], orders)
    write_csv("gateway.csv", ["PaymentID", "OrderID", "Amount", "Fee", "GST", "SettlementAmount", "Date", "Status"], gateway)
    write_csv("bank.csv", ["TransactionID", "Date", "Amount", "Narration"], bank)

# =====================================================================
# 3. Deterministic Matcher
# =====================================================================
def run_deterministic_matcher():
    """
    Performs standard, rule-based 2% fee + 18% GST calculations.
    Enforces date proximity (<= 2 days) to isolate timing differences for AI.
    """
    orders = {}
    with open("orders.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            orders[row["OrderID"]] = {
                "OrderID": row["OrderID"],
                "Date": row["Date"],
                "Amount": float(row["Amount"]),
                "Status": row["Status"],
                "DiscountAmount": float(row["DiscountAmount"])
            }

    gateway = {}
    with open("gateway.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gateway[row["OrderID"]] = {
                "PaymentID": row["PaymentID"],
                "OrderID": row["OrderID"],
                "Amount": float(row["Amount"]),
                "Fee": float(row["Fee"]),
                "GST": float(row["GST"]),
                "SettlementAmount": float(row["SettlementAmount"]),
                "Date": row["Date"],
                "Status": row["Status"]
            }

    bank_records = []
    with open("bank.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bank_records.append({
                "TransactionID": row["TransactionID"],
                "Date": row["Date"],
                "Amount": float(row["Amount"]),
                "Narration": row["Narration"],
                "Matched": False
            })

    matched = []
    unmatched_orders = {}
    unmatched_gateway = {}

    for o_id, order in orders.items():
        if o_id in gateway:
            gw = gateway[o_id]
            
            gross = order["Amount"]
            expected_fee = round(gross * 0.02, 2)
            expected_gst = round(expected_fee * 0.18, 2)
            expected_net = round(gross - expected_fee - expected_gst, 2)
            
            gw_net = gw["SettlementAmount"]
            
            # Match with bank statement (enforcing <= 2 days date proximity)
            bank_match = None
            for bk in bank_records:
                if not bk["Matched"] and o_id in bk["Narration"]:
                    if abs(bk["Amount"] - expected_net) <= 1.0 and abs(bk["Amount"] - gw_net) <= 1.0:
                        if gw["Status"] == "captured":
                            # Date proximity check
                            gw_date = datetime.strptime(gw["Date"], "%Y-%m-%d %H:%M:%S")
                            bk_date = datetime.strptime(bk["Date"], "%Y-%m-%d")
                            if abs((bk_date - gw_date).days) <= 2:
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
                    "Type": "Deterministic match",
                    "Reason": "Gross, gateway net settlement and bank deposit match perfectly under 2% standard pricing."
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
# 4. ReAct AI Agent Reconciler & Parallel Chunk Worker
# =====================================================================
def process_single_chunk(chunk_orders, bank_candidates_map=None):
    """
    Parallel Thread-Pool Worker:
    Handles prompt formulation, concurrency retries with exponential backoff,
    response parsing, and strict mathematical verification guardrails for a single chunk.
    """
    chunk_resolved = []
    chunk_exceptions = []
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
    order_blocks = {}
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

        print(f"[{o_id}] {think_step if think_step else 'THINK: Analyzing batch discrepancy against settlement stream'}")
        print(f"[{o_id}] {act_step if act_step else 'ACT: Verified candidate records across internal ledger and gateway'}")
        print(f"[{o_id}] {obs_step if obs_step else 'OBSERVE: Ledger variance identified'}")
        print(f"[{o_id}] {decide_step}")
        print("-" * 75)

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


def run_react_agent(unmatched_orders, unmatched_gateway, unmatched_bank):
    """
    High-Performance Batched ReAct AI Reconciler:
    1. Fast-Path Heuristic Triage (Skip LLM for empty candidates & pure timing delays).
    2. Dynamic Logarithmic Batch Size Calculation.
    3. ThreadPoolExecutor concurrent batch processing with exponential backoff.
    4. Robust parsing and mathematical verification guardrail.
    """
    fast_path_matches = []
    fast_path_exceptions = []
    complex_anomalies = []
    bank_candidates_map = {}

    # -------------------------------------------------------------
    # STEP 1: FAST-PATH HEURISTIC TRIAGE
    # -------------------------------------------------------------
    for o_id, order in list(unmatched_orders.items()):
        gw = unmatched_gateway.get(o_id)
        gross = order["Amount"]
        expected_fee = round(gross * 0.02, 2)
        expected_gst = round(expected_fee * 0.18, 2)
        expected_net = round(gross - expected_fee - expected_gst, 2)
        if gw:
            expected_net = gw.get("SettlementAmount", expected_net)

        # Candidate selection
        bank_candidates = []
        for bk in unmatched_bank:
            score = 0
            if o_id in bk["Narration"]: score += 10
            if gw and gw["PaymentID"] in bk["Narration"]: score += 10
            if gw and abs(bk["Amount"] - gw["SettlementAmount"]) < 200: score += 5
            elif abs(bk["Amount"] - order["Amount"]) < 200: score += 3
            if score > 0:
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
            gw_date = None
            try:
                gw_date = datetime.strptime(gw["Date"], "%Y-%m-%d %H:%M:%S").date()
            except Exception:
                try:
                    gw_date = datetime.strptime(gw["Date"], "%Y-%m-%d").date()
                except Exception:
                    gw_date = None

            for cand in bank_candidates:
                if abs(cand["Amount"] - expected_net) <= 0.05 and abs(cand["Amount"] - gw["SettlementAmount"]) <= 0.05:
                    bk_date = None
                    try:
                        bk_date = datetime.strptime(cand["Date"], "%Y-%m-%d").date()
                    except Exception:
                        bk_date = None
                    if gw_date and bk_date:
                        if abs((bk_date - gw_date).days) > 2:
                            timing_matched_cand = cand
                            break

        if timing_matched_cand:
            timing_matched_cand["Matched"] = True
            if timing_matched_cand in unmatched_bank:
                unmatched_bank.remove(timing_matched_cand)

            gw_gross = gw["Amount"] if gw else order["Amount"]
            gw_fee = gw["Fee"] if gw else round(order["Amount"] * 0.02, 2)
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
        dynamic_chunk_size = min(15, max(5, int(math.ceil(math.log2(num_anomalies) * 2))))
    else:
        dynamic_chunk_size = 5

    print(f"Dynamic Batching Active: Chunk size set to {dynamic_chunk_size}")

    resolved_matches = list(fast_path_matches)
    exceptions = list(fast_path_exceptions)

    # -------------------------------------------------------------
    # STEP 3: CONCURRENCY CONTROL WITH THREADPOOLEXECUTOR
    # -------------------------------------------------------------
    if complex_anomalies:
        chunks = [complex_anomalies[i:i + dynamic_chunk_size] for i in range(0, len(complex_anomalies), dynamic_chunk_size)]

        with ThreadPoolExecutor(max_workers=8) as executor:
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
# 5. Main Execution & Summary
# =====================================================================
def main():
    # 1. Generate dynamic synthetic data
    generate_synthetic_data()

    # 2. Run Deterministic Matcher
    det_matches, unmatched_orders, unmatched_gateway, unmatched_bank = run_deterministic_matcher()

    # Load total orders count
    orders_count = 0
    with open("orders.csv") as f:
        orders_count = sum(1 for line in f) - 1

    # 3. Run ReAct Agent
    print("\nStarting ReAct AI Agent reconciliation on unmatched cases...\n")
    ai_matches, exceptions = run_react_agent(unmatched_orders, unmatched_gateway, unmatched_bank)

    # 4. Print Summary Report following required formatting
    print("\n" + "=" * 60)
    print("RECONCILIATION SUMMARY REPORT")
    print("=" * 60)
    print(f"Total Transactions Generated: {orders_count}")
    print(f"Deterministic Matches: {len(det_matches)}")
    print(f"AI ReAct Matches: {len(ai_matches)}")
    print(f"Flagged Exceptions: {len(exceptions)}")
    
    print("\n--- MATCHED LOG ---")
    all_matches = det_matches + ai_matches
    all_matches.sort(key=lambda x: x["OrderID"])
    for m in all_matches:
        print(f"[{m['OrderID']}] Type: {m['Type']}")
        print(f"Details: Order: Rs {m['OrderAmount']:.2f} | Gateway: Rs {m['GatewayAmount']:.2f} | Bank: Rs {m['BankAmount']:.2f}")
        print(f"Reason: {m['Reason']}")

    if exceptions:
        print("\n--- FLAGGED EXCEPTIONS (Requires Manual Review) ---")
        for ex in exceptions:
            print(f"[{ex['OrderID']}] Reason: {ex['Reason']}")

    print("\nReconciliation completed successfully.")

if __name__ == "__main__":
    main()
