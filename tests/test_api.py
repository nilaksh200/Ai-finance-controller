"""
=============================================================================
AUTOMATED TEST SUITE FOR VERCEL SERVERLESS FASTAPI BACKEND
=============================================================================
Validates all API endpoints, status codes, schemas, and static file serving.
=============================================================================
"""

import sys
import os

# Add workspace root to path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi.testclient import TestClient
from api.index import app

client = TestClient(app)


def test_status_endpoint():
    """Verify system health and active engine status endpoint."""
    res = client.get("/api/status")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert data["status"] == "operational"
    assert "active_engine" in data
    print("✅ test_status_endpoint passed:", data["active_engine"])


def test_reconciliation_endpoint():
    """Verify 3-way continuous audit and reconciliation pipeline endpoint."""
    res = client.post("/api/reconcile", json={"opening_balance": 500000.0})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert data["status"] == "success"
    assert data["total_orders"] >= 100
    assert len(data["det_matches"]) > 0
    assert len(data["ai_matches"]) > 0
    assert "cash_stmt" in data
    assert "forecast_rows" in data
    assert len(data["forecast_rows"]) == 7
    assert "action_items" in data
    print(f"✅ test_reconciliation_endpoint passed: Reconciled {data['total_orders']} orders in {data['elapsed']*1000:.1f}ms")


def test_erp_dispatch_endpoints():
    """Verify single and batch ERP dispatch endpoints."""
    # First get reconciliation result
    res_rec = client.post("/api/reconcile", json={"opening_balance": 500000.0})
    rec_data = res_rec.json()
    action_items = rec_data.get("action_items", [])
    assert len(action_items) > 0, "Expected at least 1 action item"

    # Single dispatch
    sample_item = action_items[0]
    res_single = client.post("/api/dispatch-erp", json={
        "item": sample_item,
        "orders_dict": rec_data.get("orders_dict", {}),
        "gateway_dict": rec_data.get("gateway_dict", {}),
    })
    assert res_single.status_code == 200
    single_data = res_single.json()
    assert single_data["status"] == "success"
    assert "journal_entry" in single_data
    assert single_data["journal_entry"]["status"] == "POSTED_SUCCESSFULLY"
    print("✅ test_erp_dispatch_endpoints (single) passed:", single_data["journal_entry"]["journal_entry_id"])

    # Batch dispatch
    res_batch = client.post("/api/dispatch-all-erp", json={
        "action_items": action_items[:3],
        "orders_dict": rec_data.get("orders_dict", {}),
        "gateway_dict": rec_data.get("gateway_dict", {}),
    })
    assert res_batch.status_code == 200
    batch_data = res_batch.json()
    assert batch_data["dispatched_count"] == 3
    print("✅ test_erp_dispatch_endpoints (batch) passed: Dispatched", batch_data["dispatched_count"], "tickets")


def test_export_csv_endpoint():
    """Verify CSV export endpoint."""
    sample_items = [
        {
            "order_id": "ORD1101",
            "type": "refunded",
            "action": "ERP-JOURNAL-WRITEBACK",
            "owner": "Treasury",
            "urgency": "HIGH",
            "justification": "Customer refund processed"
        }
    ]
    res = client.post("/api/export-csv", json={"action_items": sample_items, "dispatched_map": {}})
    assert res.status_code == 200
    assert "text/csv" in res.headers.get("content-type", "")
    assert "ORD1101" in res.text
    print("✅ test_export_csv_endpoint passed")


def test_static_frontend_serving():
    """Verify static assets are properly served for local testing and Vercel parity."""
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert "Autonomous Payment" in res_index.text

    res_css = client.get("/style.css")
    assert res_css.status_code == 200
    assert "--font-main" in res_css.text

    res_js = client.get("/app.js")
    assert res_js.status_code == 200
    assert "handleRunPipeline" in res_js.text
    print("✅ test_static_frontend_serving passed")


if __name__ == "__main__":
    test_status_endpoint()
    test_reconciliation_endpoint()
    test_erp_dispatch_endpoints()
    test_export_csv_endpoint()
    test_static_frontend_serving()
    print("\n🎉 ALL FASTAPI VERCEL SERVERLESS TESTS PASSED SUCCESSFULLY!")
