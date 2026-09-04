"""
=============================================================================
AUTOMATED CI RECONCILIATION AUDIT & SMOKE TEST SUITE
=============================================================================
"""

import sys
import os

# Add workspace root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from finance_controller import (
    generate_synthetic_data,
    load_reconciliation_data,
    run_deterministic_matcher,
    run_react_agent,
    CashPositionController,
    CashForecaster,
    compute_accuracy_metrics,
)


def test_reconciliation_pipeline():
    """Validates the 5-layer reconciliation pipeline and accuracy metrics."""
    print("-> 1. Generating synthetic datasets...")
    generate_synthetic_data(seed=42)
    dataset = load_reconciliation_data("orders.csv", "gateway.csv", "bank.csv", "ground_truth.csv")
    
    assert len(dataset["orders"]) >= 100, f"Expected at least 100 orders, got {len(dataset['orders'])}"
    assert len(dataset["gateway"]) >= 100, f"Expected at least 100 gateway records, got {len(dataset['gateway'])}"
    assert len(dataset["bank"]) > 0, "Bank records empty"

    print("-> 2. Executing Layer 1 deterministic matcher...")
    det_matches, unmatched_orders, unmatched_gateway, unmatched_bank = run_deterministic_matcher(
        dataset["orders"], dataset["gateway"], dataset["bank"]
    )
    assert len(det_matches) > 0, "Deterministic matcher produced 0 matches"

    print("-> 3. Executing Layer 1.5 ReAct cognitive loop...")
    ai_matches, exceptions = run_react_agent(unmatched_orders, unmatched_gateway, unmatched_bank)
    assert len(ai_matches) + len(exceptions) > 0, "ReAct agent produced no output"

    print("-> 4. Computing accuracy metrics against ground truth...")
    metrics = compute_accuracy_metrics(dataset["ground_truth_map"], det_matches, ai_matches, exceptions)
    print(f"   F1-Score: {metrics['f1']:.2f}%, Precision: {metrics['precision']:.2f}%, Recall: {metrics['recall']:.2f}%")
    assert metrics["f1"] >= 80.0, f"F1 score {metrics['f1']} below 80%"

    print("-> 5. Auditing Treasury & 7-Day Forward Forecast...")
    cash_ctrl = CashPositionController(opening_balance=500000.0)
    cash_stmt = cash_ctrl.update_from_reconciliation(det_matches, ai_matches, exceptions)
    assert "closing_balance" in cash_stmt
    assert "inflows" in cash_stmt

    forecaster = CashForecaster(reconciled_data={"all_orders": list(dataset["orders"].values()), "refunds_count": 0})
    forecast = forecaster.forecast_7day(
        current_balance=cash_stmt["closing_balance"],
        pending_float=cash_stmt["inflows"]["pending_settlements"]
    )
    assert len(forecast) == 7, f"Expected 7-day forecast, got {len(forecast)}"

    print("✅ All Automated Reconciliation CI Tests Passed Successfully!")


if __name__ == "__main__":
    test_reconciliation_pipeline()
