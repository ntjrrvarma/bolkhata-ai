"""Seed realistic Indian kirana store data into Firestore or local JSON mock DB (`USE_MOCK_DB=true`)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db import COLLECTIONS, get_db, utc_now_iso


def seed_database() -> None:
    """Reset and populate customers, inventory, transactions, and reminders collections."""
    db = get_db()
    now = utc_now_iso()

    for col in COLLECTIONS:
        db.reset_collection(col)

    customers = [
        {
            "id": "ramesh_kumar",
            "name": "Ramesh Kumar",
            "phone": "+919876543210",
            "balance": 1450.0,
            "language": "hinglish",
            "last_tx_at": "2026-11-24T10:15:00+00:00",
            "notes": "Regular monthly ration customer, Lane 3",
        },
        {
            "id": "priya_sharma",
            "name": "Priya Sharma",
            "phone": "+919812345678",
            "balance": 420.0,
            "language": "hinglish",
            "last_tx_at": "2026-11-25T17:40:00+00:00",
            "notes": "Pays via UPI every weekend",
        },
        {
            "id": "suresh_yadav",
            "name": "Suresh Yadav",
            "phone": "+919823456789",
            "balance": 2380.0,
            "language": "hindi",
            "last_tx_at": "2026-11-18T12:30:00+00:00",
            "notes": "Chai stall owner near main chowk",
        },
        {
            "id": "anita_deshmukh",
            "name": "Anita Deshmukh",
            "phone": "+919834567890",
            "balance": 1150.0,
            "language": "english",
            "last_tx_at": "2026-11-20T09:05:00+00:00",
            "notes": "Apartment B-204",
        },
        {
            "id": "vikram_singh",
            "name": "Vikram Singh",
            "phone": "+919845678901",
            "balance": 0.0,
            "language": "hinglish",
            "last_tx_at": "2026-11-25T19:00:00+00:00",
            "notes": "Cleared dues yesterday",
        },
    ]

    for cust in customers:
        db.set_doc("customers", cust["id"], cust)

    inventory_items = [
        {
            "id": "aashirvaad_atta",
            "item_name": "Aashirvaad Atta (5kg)",
            "unit": "bags",
            "quantity": 14.0,
            "reorder_level": 5.0,
            "price_per_unit": 245.0,
            "updated_at": now,
        },
        {
            "id": "india_gate_basmati_rice",
            "item_name": "India Gate Basmati Rice",
            "unit": "kg",
            "quantity": 4.0,
            "reorder_level": 10.0,
            "price_per_unit": 120.0,
            "updated_at": now,
        },
        {
            "id": "fortune_cooking_oil",
            "item_name": "Fortune Sunflower Cooking Oil (1L)",
            "unit": "pouches",
            "quantity": 3.0,
            "reorder_level": 8.0,
            "price_per_unit": 155.0,
            "updated_at": now,
        },
        {
            "id": "tata_sampann_toor_dal",
            "item_name": "Tata Sampann Toor Dal",
            "unit": "kg",
            "quantity": 18.0,
            "reorder_level": 6.0,
            "price_per_unit": 165.0,
            "updated_at": now,
        },
        {
            "id": "amul_taaza_milk",
            "item_name": "Amul Taaza Milk (500ml)",
            "unit": "packets",
            "quantity": 6.0,
            "reorder_level": 12.0,
            "price_per_unit": 28.0,
            "updated_at": now,
        },
        {
            "id": "tata_tea_gold",
            "item_name": "Tata Tea Gold (500g)",
            "unit": "packs",
            "quantity": 11.0,
            "reorder_level": 5.0,
            "price_per_unit": 270.0,
            "updated_at": now,
        },
        {
            "id": "maggi_masala_noodles",
            "item_name": "Maggi Masala Noodles (4-pack)",
            "unit": "packs",
            "quantity": 22.0,
            "reorder_level": 8.0,
            "price_per_unit": 56.0,
            "updated_at": now,
        },
    ]

    for item in inventory_items:
        db.set_doc("inventory", item["id"], item)

    transactions = [
        {
            "id": "tx_seed001",
            "customer_id": "ramesh_kumar",
            "customer_name": "Ramesh Kumar",
            "amount": 1850.0,
            "tx_type": "credit",
            "items": "2x Aashirvaad Atta 5kg, 3L Cooking Oil, 5kg Basmati Rice",
            "previous_balance": 0.0,
            "new_balance": 1850.0,
            "confirmed_by_voice": True,
            "created_at": "2026-11-22T11:00:00+00:00",
        },
        {
            "id": "tx_seed002",
            "customer_id": "ramesh_kumar",
            "customer_name": "Ramesh Kumar",
            "amount": 400.0,
            "tx_type": "payment",
            "items": "Cash part-payment at counter",
            "previous_balance": 1850.0,
            "new_balance": 1450.0,
            "confirmed_by_voice": True,
            "created_at": "2026-11-24T10:15:00+00:00",
        },
        {
            "id": "tx_seed003",
            "customer_id": "priya_sharma",
            "customer_name": "Priya Sharma",
            "amount": 420.0,
            "tx_type": "credit",
            "items": "2kg Toor Dal, 3x Amul Milk",
            "previous_balance": 0.0,
            "new_balance": 420.0,
            "confirmed_by_voice": True,
            "created_at": "2026-11-25T17:40:00+00:00",
        },
        {
            "id": "tx_seed004",
            "customer_id": "suresh_yadav",
            "customer_name": "Suresh Yadav",
            "amount": 2380.0,
            "tx_type": "credit",
            "items": "5x Tata Tea Gold, 15kg Sugar, 12x Amul Milk",
            "previous_balance": 0.0,
            "new_balance": 2380.0,
            "confirmed_by_voice": True,
            "created_at": "2026-11-18T12:30:00+00:00",
        },
        {
            "id": "tx_seed005",
            "customer_id": "anita_deshmukh",
            "customer_name": "Anita Deshmukh",
            "amount": 1150.0,
            "tx_type": "credit",
            "items": "5kg Basmati Rice, 2L Fortune Cooking Oil, 2x Maggi 4-pack",
            "previous_balance": 0.0,
            "new_balance": 1150.0,
            "confirmed_by_voice": True,
            "created_at": "2026-11-20T09:05:00+00:00",
        },
    ]

    for tx in transactions:
        db.set_doc("transactions", tx["id"], tx)

    reminders = [
        {
            "id": "rem_seed001",
            "customer_id": "suresh_yadav",
            "customer_name": "Suresh Yadav",
            "phone": "+919823456789",
            "amount": 2380.0,
            "language": "hindi",
            "message": (
                "नमस्ते Suresh Yadav जी, Sharma Kirana & General Store में आपका ₹2380 का खाता बकाया है। "
                "कृपया UPI (sharmakirana@okaxis) या दुकान पर भुगतान करें। धन्यवाद!"
            ),
            "channel": "whatsapp_click_to_chat",
            "twilio_sid": None,
            "whatsapp_url": "https://wa.me/919823456789?text=Namaste",
            "status": "sent",
            "sent_at": "2026-11-25T09:00:00+00:00",
            "paid_at": None,
        }
    ]

    for rem in reminders:
        db.set_doc("reminders", rem["id"], rem)

    mode_str = f"MOCK JSON ({db.mock_path})" if db.use_mock else "Google Cloud Firestore"
    print(f"[BolKhata Seed] Successfully seeded database in {mode_str}:")
    print(f"  - Customers:    {len(customers)}")
    print(f"  - Inventory:    {len(inventory_items)} (3 items in low-stock state)")
    print(f"  - Transactions: {len(transactions)}")
    print(f"  - Reminders:    {len(reminders)}")


if __name__ == "__main__":
    seed_database()
