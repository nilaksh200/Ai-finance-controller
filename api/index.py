#!/usr/bin/env python3
"""
=============================================================================
VERCEL SERVERLESS FASTAPI BACKEND - AUTONOMOUS AI FINANCE CONTROLLER
=============================================================================
Provides serverless API endpoints on Vercel for 3-Way Payment Reconciliation,
Cognitive ReAct Anomaly Resolution, Dual-Track Treasury Accounting,
Predictive Liquidity Forecasting, and ERP Journal Dispatch.
=============================================================================
"""

import sys
import os
import io
import time
import csv
from datetime import datetime
from typing import Dict, List, Any, Optional

from fastapi import FastAPI, UploadFile, File, Form, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

# Ensure workspace root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from finance_controller import (
    generate_synthetic_data,
    load_reconciliation_data,
    run_deterministic_matcher,
    run_react_agent,
    CashPositionController,
    CashForecaster,
    close_the_loop,
    compute_accuracy_metrics,
    get_active_engine_name,
    format_inr,
    parse_float_safe,
    calculate_net,
)

app = FastAPI(
    title="Autonomous Payment Reconciliation & Cash Controller API",
    description="Enterprise-grade 3-Way reconciliation and ReAct anomaly detective API for Vercel",
    version="2.0.0"
)

# Enable CORS for cross-origin local dev and Vercel edge routing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _generate_erp_payload(item: Dict[str, Any], orders_dict: Dict[str, Any], gateway_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Generates a compliant double-entry General Ledger journal adjustment payload."""
    o_id = item.get("order_id", "")
    order = orders_dict.get(o_id, {})
    gw = gateway_dict.get(o_id, {})

    gross_amt = parse_float_safe(order.get("Amount", gw.get("Amount", 1250.0)))
    if gross_amt <= 0:
        gross_amt = 1250.0

    if gw:
        fee_amt = parse_float_safe(gw.get("Fee", round(gross_amt * 0.02, 2)))
        gst_amt = parse_float_safe(gw.get("GST", round(fee_amt * 0.18, 2)))
        total_fee = round(fee_amt + gst_amt, 2)
        net_amt = parse_float_safe(gw.get("SettlementAmount", round(gross_amt - total_fee, 2)))
    else:
        fee_amt = round(gross_amt * 0.02, 2)
        gst_amt = round(fee_amt * 0.18, 2)
        total_fee = round(fee_amt + gst_amt, 2)
        net_amt = round(gross_amt - total_fee, 2)

    m_type = str(item.get("type", "")).lower()
    just = str(item.get("justification", "")).lower()

    if "refund" in m_type or "refund" in just:
        entries = [
            {"account": "4100 - Sales Returns & Allowances", "type": "DEBIT", "amount": round(gross_amt, 2)},
            {"account": "1100 - Operating Bank Cash", "type": "CREDIT", "amount": round(gross_amt, 2)}
        ]
    elif "missing" in m_type or "missing" in just:
        entries = [
            {"account": "1150 - Settlement In-Transit (Suspense)", "type": "DEBIT", "amount": round(net_amt, 2)},
            {"account": "5200 - Merchant Processing Fees", "type": "DEBIT", "amount": round(total_fee, 2)},
            {"account": "1200 - Accounts Receivable", "type": "CREDIT", "amount": round(gross_amt, 2)}
        ]
    else:
        entries = [
            {"account": "1100 - Operating Bank Cash", "type": "DEBIT", "amount": round(net_amt, 2)},
            {"account": "5200 - Merchant processing Fees", "type": "DEBIT", "amount": round(total_fee, 2)},
            {"account": "1200 - Accounts Receivable", "type": "CREDIT", "amount": round(gross_amt, 2)}
        ]

    num_digits = "".join(c for c in o_id if c.isdigit()) or "1001"
    today_str = datetime.utcnow().strftime("%Y-%m%d")
    je_id = f"JE-{today_str}-{num_digits.zfill(4)}"
    posted_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "journal_entry_id": je_id,
        "system": "QuickBooks Enterprise Online",
        "posted_at": posted_iso,
        "entries": entries,
        "status": "POSTED_SUCCESSFULLY"
    }


@app.get("/api/status")
@app.get("/status")
def get_system_status():
    """Returns engine health, active AI reasoning model, and system status."""
    engine_name = get_active_engine_name()
    return {
        "status": "operational",
        "active_engine": engine_name,
        "timestamp": datetime.utcnow().isoformat(),
        "platform": "Vercel Serverless Function",
    }


@app.post("/api/generate")
@app.post("/generate")
def generate_fresh_dataset():
    """Generates a brand-new randomized 200-order synthetic dataset."""
    summary = generate_synthetic_data(seed=None)
    return {
        "status": "success",
        "message": "Generated fresh random dataset with 200 transactions.",
        "summary": {
            "total_orders": summary.get("total_orders", 200),
            "normal_orders": summary.get("normal_orders", 100),
            "mismatches_injected": summary.get("mismatches_injected", 100),
        }
    }


@app.post("/api/reconcile")
@app.post("/reconcile")
async def run_reconciliation(payload: Dict[str, Any] = Body(default={})):
    """
    Executes the 5-layer 3-way continuous audit and reconciliation pipeline.
    Accepts custom CSV content or runs on default demo synthetic dataset.
    """
    start_ts = time.perf_counter()
    opening_balance = float(payload.get("opening_balance", 500_000.0))

    orders_csv = payload.get("orders_csv")
    gateway_csv = payload.get("gateway_csv")
    bank_csv = payload.get("bank_csv")
    ground_truth_csv = payload.get("ground_truth_csv")

    is_custom = bool(orders_csv and gateway_csv and bank_csv)

    if is_custom:
        dataset = load_reconciliation_data(
            orders_source=orders_csv,
            gateway_source=gateway_csv,
            bank_source=bank_csv,
            ground_truth_source=ground_truth_csv
        )
    else:
        # Load standard files or generate if missing
        csv_files = ["orders.csv", "gateway.csv", "bank.csv", "ground_truth.csv"]
        paths = [os.path.join(BASE_DIR, f) for f in csv_files]
        if not all(os.path.exists(p) for p in paths):
            generate_synthetic_data(seed=None)
            # Re-check paths in temp dir if root was read-only
            paths = [p if os.path.exists(p) else os.path.join(os.environ.get("TEMP", "/tmp"), f) for f, p in zip(csv_files, paths)]

        dataset = load_reconciliation_data(paths[0], paths[1], paths[2], paths[3])

    orders = dataset["orders"]
    gateway = dataset["gateway"]
    bank_records = dataset["bank"]
    ground_truth_map = dataset.get("ground_truth_map", {})
    total_orders = len(orders)

    # 1. Deterministic Fast-Path
    det_matches, unmatched_orders, unmatched_gateway, unmatched_bank = run_deterministic_matcher(
        orders=orders,
        gateway=gateway,
        bank_records=bank_records,
    )

    # 2. ReAct Cognitive Anomaly Detective
    ai_matches, exceptions = run_react_agent(
        unmatched_orders=unmatched_orders,
        unmatched_gateway=unmatched_gateway,
        unmatched_bank=unmatched_bank,
    )

    elapsed = max(time.perf_counter() - start_ts, 0.001)
    throughput = total_orders / elapsed

    # 3. Ground Truth Benchmarking & Accuracy
    accuracy = compute_accuracy_metrics(
        ground_truth_map=ground_truth_map,
        det_matches=det_matches,
        ai_matches=ai_matches,
        exceptions=exceptions,
    )

    # 4. Dual-Track Cash Position Statement
    cash_ctrl = CashPositionController(opening_balance=opening_balance)
    cash_stmt = cash_ctrl.update_from_reconciliation(
        det_matches=det_matches,
        ai_matches=ai_matches,
        exceptions=exceptions,
    )

    # 5. 7-Day Predictive Liquidity Trajectory
    all_orders = list(orders.values())
    refunds_count = sum(1 for m in ai_matches if m.get("Classification") == "MATCH_AS_REFUNDED")
    forecaster = CashForecaster(reconciled_data={
        "all_orders": all_orders,
        "refunds_count": refunds_count,
    })
    pending_float = cash_stmt["inflows"]["pending_settlements"]
    forecast_rows = forecaster.forecast_7day(
        current_balance=cash_stmt["closing_balance"],
        pending_float=pending_float
    )

    # 6. Operational Loop Closure & Action Items
    action_items = close_the_loop(exceptions, ai_matches, ground_truth_map)
    engine_name = get_active_engine_name()

    return {
        "status": "success",
        "total_orders": total_orders,
        "det_matches": det_matches,
        "ai_matches": ai_matches,
        "exceptions": exceptions,
        "elapsed": elapsed,
        "throughput": throughput,
        "accuracy": accuracy,
        "cash_stmt": cash_stmt,
        "forecast_rows": forecast_rows,
        "action_items": action_items,
        "engine_name": engine_name,
        "is_custom": is_custom,
        "orders_dict": orders,
        "gateway_dict": gateway,
    }


@app.post("/api/dispatch-erp")
@app.post("/dispatch-erp")
def dispatch_erp(payload: Dict[str, Any] = Body(...)):
    """Dispatches an action ticket to General Ledger and returns double-entry journal."""
    item = payload.get("item", {})
    orders_dict = payload.get("orders_dict", {})
    gateway_dict = payload.get("gateway_dict", {})

    journal = _generate_erp_payload(item, orders_dict, gateway_dict)
    return {
        "status": "success",
        "order_id": item.get("order_id"),
        "journal_entry": journal
    }


@app.post("/api/dispatch-all-erp")
@app.post("/dispatch-all-erp")
def dispatch_all_erp(payload: Dict[str, Any] = Body(...)):
    """Batch dispatches all action tickets to ERP."""
    action_items = payload.get("action_items", [])
    orders_dict = payload.get("orders_dict", {})
    gateway_dict = payload.get("gateway_dict", {})

    dispatched = {}
    for item in action_items:
        o_id = item.get("order_id")
        if o_id:
            dispatched[o_id] = _generate_erp_payload(item, orders_dict, gateway_dict)

    return {
        "status": "success",
        "dispatched_count": len(dispatched),
        "dispatched_map": dispatched
    }


@app.post("/api/export-csv")
@app.post("/export-csv")
def export_audit_csv(payload: Dict[str, Any] = Body(...)):
    """Generates the audit trail and ERP ticket CSV."""
    action_items = payload.get("action_items", [])
    dispatched_map = payload.get("dispatched_map", {})

    output = io.StringIO()
    fieldnames = [
        "OrderID", "MismatchType", "Action", "Owner", "Urgency",
        "ERPStatus", "JournalEntryID", "BusinessJustification"
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for item in action_items:
        o_id = item.get("order_id", "")
        is_disp = o_id in dispatched_map
        je_id = dispatched_map[o_id]["journal_entry_id"] if is_disp else "PENDING"
        a_clean = str(item.get("action", "")).replace("-", " ").replace("_", " ")
        t_clean = str(item.get("type", "")).replace("-", " ")
        j_clean = str(item.get("justification", "")).replace(" - ", ": ").replace("-", " ")

        writer.writerow({
            "OrderID": o_id,
            "MismatchType": t_clean,
            "Action": a_clean,
            "Owner": item.get("owner", ""),
            "Urgency": item.get("urgency", ""),
            "ERPStatus": f"POSTED ({je_id})" if is_disp else "PENDING",
            "JournalEntryID": je_id,
            "BusinessJustification": j_clean
        })

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=controller_audit_tickets_erp.csv"}
    )


# ---------------------------------------------------------------------------
# STATIC FRONTEND SERVING (For local development parity with Vercel)
# ---------------------------------------------------------------------------
from fastapi.responses import FileResponse

PUBLIC_DIR = os.path.join(BASE_DIR, "public")

@app.get("/")
def serve_index():
    index_file = os.path.join(PUBLIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Autonomous AI Finance Controller API Operational"}

@app.get("/{file_path:path}")
def serve_static(file_path: str):
    # Only serve if not an API route and file exists in public/
    target_path = os.path.join(PUBLIC_DIR, file_path)
    if os.path.isfile(target_path):
        return FileResponse(target_path)
    index_file = os.path.join(PUBLIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="File not found")
