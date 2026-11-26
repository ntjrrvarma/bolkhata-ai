"""Smoke test and pytest suite verifying all 8 BolKhata AI ADK tools against `USE_MOCK_DB=true`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["USE_MOCK_DB"] = "true"

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.tools import (
    get_customer_balance,
    get_daily_summary,
    get_low_stock_items,
    list_overdue_customers,
    mark_reminder_paid,
    record_khata_entry,
    send_payment_reminder,
    update_stock,
)
from scripts.seed_db import seed_database


def run_all_tool_tests() -> None:
    """Seed mock database and verify all 8 tools + HITL guardrail."""
    print("1. Seeding mock database...")
    seed_database()

    # Tool 1: get_customer_balance
    print("\n2. Testing get_customer_balance('Ramesh')...")
    res_bal = get_customer_balance("Ramesh")
    assert res_bal["status"] == "ok", res_bal
    assert res_bal["balance"] == 1450.0, res_bal
    print("   PASS ->", res_bal["message"])

    # Guardrail verification: record_khata_entry without voice confirmation must block
    print("\n3. Testing HITL guardrail on record_khata_entry(confirmed_by_voice=False)...")
    res_blocked = record_khata_entry(
        customer_name="Ramesh Kumar",
        amount=250.0,
        items="5kg Atta",
        tx_type="credit",
        confirmed_by_voice=False,
    )
    assert res_blocked["status"] == "confirmation_required", res_blocked
    print("   PASS (Blocked unconfirmed write) ->", res_blocked["message"])

    # Tool 2: record_khata_entry (confirmed credit + payment)
    print("\n4. Testing record_khata_entry(confirmed_by_voice=True)...")
    res_credit = record_khata_entry(
        customer_name="Ramesh Kumar",
        amount=250.0,
        items="1x Aashirvaad Atta 5kg",
        tx_type="credit",
        confirmed_by_voice=True,
    )
    assert res_credit["status"] == "recorded", res_credit
    assert res_credit["new_balance"] == 1700.0, res_credit
    print("   PASS ->", res_credit["message"])

    # Tool 3: get_daily_summary
    print("\n5. Testing get_daily_summary()...")
    res_summary = get_daily_summary()
    assert res_summary["status"] == "ok", res_summary
    assert res_summary["total_outstanding_dues"] > 0, res_summary
    print("   PASS ->", res_summary["message"])

    # Tool 4: update_stock
    print("\n6. Testing update_stock('Aashirvaad Atta', delta=-2)...")
    res_stock = update_stock("Aashirvaad Atta", delta=-2)
    assert res_stock["status"] == "updated", res_stock
    assert res_stock["new_quantity"] == 12.0, res_stock
    print("   PASS ->", res_stock["message"])

    # Tool 5: get_low_stock_items
    print("\n7. Testing get_low_stock_items()...")
    res_low = get_low_stock_items()
    assert res_low["status"] == "ok", res_low
    assert res_low["low_stock_count"] == 3, res_low
    print("   PASS ->", res_low["message"])

    # Tool 6: list_overdue_customers
    print("\n8. Testing list_overdue_customers(min_amount=1000)...")
    res_overdue = list_overdue_customers(min_amount=1000)
    assert res_overdue["status"] == "ok", res_overdue
    assert res_overdue["overdue_count"] == 3, res_overdue
    print("   PASS ->", res_overdue["message"])

    # Tool 7: send_payment_reminder
    print("\n9. Testing send_payment_reminder('Ramesh Kumar', language='hinglish')...")
    res_rem = send_payment_reminder("Ramesh Kumar", language="hinglish")
    assert res_rem["status"] == "sent", res_rem
    assert res_rem["whatsapp_url"].startswith("https://wa.me/"), res_rem
    reminder_id = res_rem["reminder_id"]
    print("   PASS ->", res_rem["message"])
    print("   WhatsApp URL ->", res_rem["whatsapp_url"])

    # Tool 8: mark_reminder_paid
    print(f"\n10. Testing mark_reminder_paid('{reminder_id}')...")
    res_paid = mark_reminder_paid(reminder_id)
    assert res_paid["status"] == "paid", res_paid
    assert res_paid["new_customer_balance"] == 0.0, res_paid
    print("   PASS ->", res_paid["message"])

    # Re-seed clean state so mock_db.json is ready for interactive `adk web` testing
    print("\n11. Resetting mock DB to clean seeded state for interactive session...")
    seed_database()
    print("\nAll 8 BolKhata AI tools + HITL guardrail verified successfully!")


def test_all_bolkhata_tools() -> None:
    """Pytest entrypoint."""
    run_all_tool_tests()


if __name__ == "__main__":
    run_all_tool_tests()
