"""Google ADK Tool Functions for BolKhata AI.

All 8 tool functions return structured dictionaries with clear status fields and
Hinglish-friendly summaries so the Gemini Live voice agent can respond crisply.
"""

from __future__ import annotations

import urllib.parse
import uuid
from typing import Any

from app import config
from app.db import get_db, normalize_key, utc_now_iso


# ============================================================================
# 1. KHATA & LEDGER TOOLS
# ============================================================================


def get_customer_balance(customer_name: str) -> dict[str, Any]:
    """Fetch a customer's current khata (udhaar/credit) balance and recent transaction details.

    Args:
        customer_name: Name of the customer (e.g., "Ramesh", "Priya", "Suresh").

    Returns:
        A dict containing customer profile, current rupee balance, and recent transactions.
    """
    db = get_db()
    customer = db.find_customer(customer_name)
    if not customer:
        return {
            "status": "not_found",
            "customer_name": customer_name,
            "balance": 0.0,
            "message": f"No customer record found for '{customer_name}'.",
        }

    cust_id = customer["id"]
    all_tx = db.list_docs("transactions")
    cust_tx = sorted(
        [tx for tx in all_tx if tx.get("customer_id") == cust_id],
        key=lambda x: x.get("created_at", ""),
        reverse=True,
    )[:5]

    return {
        "status": "ok",
        "customer_id": cust_id,
        "customer_name": customer["name"],
        "phone": customer.get("phone", ""),
        "balance": float(customer.get("balance", 0.0)),
        "last_tx_at": customer.get("last_tx_at"),
        "recent_transactions": cust_tx,
        "message": (
            f"{customer['name']} ka current khata balance ₹{float(customer.get('balance', 0.0)):.0f} baki hai."
        ),
    }


def record_khata_entry(
    customer_name: str,
    amount: float,
    items: str,
    tx_type: str = "credit",
    confirmed_by_voice: bool = True,
) -> dict[str, Any]:
    """Record a new credit (udhaar) or payment (jama) entry in a customer's khata ledger.

    IMPORTANT GUARDRAIL: The agent MUST verbally confirm the customer name, items,
    and exact rupee amount with the user before calling this tool with `confirmed_by_voice=True`.

    Args:
        customer_name: Customer's name (e.g., "Ramesh Kumar"). Creating a new customer if not found.
        amount: Positive rupee amount of the transaction (e.g., 450.0).
        items: Comma-separated description of items or payment note (e.g., "5kg Atta, 1L Oil").
        tx_type: Either "credit" (udhaar added to balance) or "payment" (jama subtracted from balance).
        confirmed_by_voice: Must be True after explicit user confirmation ("haan", "yes", "theek hai").

    Returns:
        A dict with transaction ID, previous balance, updated balance, and confirmation status.
    """
    if not confirmed_by_voice:
        return {
            "status": "confirmation_required",
            "message": (
                "Guardrail blocked ledger write: Please ask the shopkeeper to verbally confirm "
                f"{customer_name}, items ({items}), and amount ₹{amount:.0f} before recording."
            ),
        }

    if amount <= 0:
        return {
            "status": "error",
            "message": "Transaction amount must be greater than zero.",
        }

    normalized_type = tx_type.strip().lower()
    if normalized_type in ("udhaar", "debit", "due", "credit"):
        normalized_type = "credit"
    elif normalized_type in ("payment", "jama", "paid", "received"):
        normalized_type = "payment"
    else:
        return {
            "status": "error",
            "message": f"Invalid tx_type '{tx_type}'. Use 'credit' (udhaar) or 'payment' (jama).",
        }

    db = get_db()
    now = utc_now_iso()
    customer = db.find_customer(customer_name)

    if customer is None:
        cust_id = normalize_key(customer_name)
        customer = {
            "id": cust_id,
            "name": customer_name.strip().title(),
            "phone": "+919800000000",
            "balance": 0.0,
            "language": "hinglish",
            "last_tx_at": now,
        }
    else:
        cust_id = customer["id"]

    previous_balance = float(customer.get("balance", 0.0))
    delta = float(amount) if normalized_type == "credit" else -float(amount)
    new_balance = round(previous_balance + delta, 2)

    customer["balance"] = new_balance
    customer["last_tx_at"] = now
    db.set_doc("customers", cust_id, customer)

    tx_id = f"tx_{uuid.uuid4().hex[:8]}"
    tx_record = {
        "id": tx_id,
        "customer_id": cust_id,
        "customer_name": customer["name"],
        "amount": round(float(amount), 2),
        "tx_type": normalized_type,
        "items": items.strip(),
        "previous_balance": previous_balance,
        "new_balance": new_balance,
        "confirmed_by_voice": True,
        "created_at": now,
    }
    db.set_doc("transactions", tx_id, tx_record)

    action_hi = "udhaar likh diya" if normalized_type == "credit" else "jama kar liya"
    return {
        "status": "recorded",
        "transaction": tx_record,
        "previous_balance": previous_balance,
        "new_balance": new_balance,
        "message": (
            f"{customer['name']} ke khate mein ₹{amount:.0f} ({items}) {action_hi}. "
            f"Ab total balance ₹{new_balance:.0f} hai."
        ),
    }


def get_daily_summary() -> dict[str, Any]:
    """Calculate overall store khata ledger metrics: total credit given, payments collected, and net outstanding.

    Returns:
        A dict with total credit (udhaar), total payment (jama), total outstanding across all customers,
        and recent transaction counts.
    """
    db = get_db()
    transactions = db.list_docs("transactions")
    customers = db.list_docs("customers")
    reminders = db.list_docs("reminders")

    total_credit = sum(
        float(tx.get("amount", 0.0))
        for tx in transactions
        if tx.get("tx_type") == "credit"
    )
    total_payment = sum(
        float(tx.get("amount", 0.0))
        for tx in transactions
        if tx.get("tx_type") == "payment"
    )
    total_outstanding = sum(
        max(0.0, float(c.get("balance", 0.0))) for c in customers
    )
    paid_reminders = [r for r in reminders if r.get("status") == "paid"]
    recovered_via_reminders = sum(float(r.get("amount", 0.0)) for r in paid_reminders)

    return {
        "status": "ok",
        "total_credit_given": round(total_credit, 2),
        "total_payments_collected": round(total_payment, 2),
        "total_outstanding_dues": round(total_outstanding, 2),
        "transaction_count": len(transactions),
        "customer_count": len(customers),
        "reminders_sent": len(reminders),
        "reminders_paid": len(paid_reminders),
        "recovered_via_reminders": round(recovered_via_reminders, 2),
        "message": (
            f"Aaj tak kul udhaar ₹{total_credit:.0f}, vasooli ₹{total_payment:.0f}, "
            f"aur market mein baki udhaar ₹{total_outstanding:.0f} hai."
        ),
    }


# ============================================================================
# 2. INVENTORY & REORDER TOOLS
# ============================================================================


def update_stock(item_name: str, delta: float) -> dict[str, Any]:
    """Increment or decrement the stock quantity of a kirana inventory item.

    Args:
        item_name: Name of the item (e.g., "Atta", "Basmati Rice", "Cooking Oil", "Toor Dal").
        delta: Positive number to add stock (restock) or negative number to deduct stock (sale).

    Returns:
        A dict with previous quantity, new quantity, reorder threshold, and low-stock alert flag.
    """
    db = get_db()
    now = utc_now_iso()
    item = db.find_inventory_item(item_name)

    if item is None:
        item_id = normalize_key(item_name)
        item = {
            "id": item_id,
            "item_name": item_name.strip().title(),
            "unit": "units",
            "quantity": 0.0,
            "reorder_level": 5.0,
            "price_per_unit": 50.0,
            "updated_at": now,
        }
    else:
        item_id = item["id"]

    prev_qty = float(item.get("quantity", 0.0))
    new_qty = round(max(0.0, prev_qty + float(delta)), 2)
    reorder_level = float(item.get("reorder_level", 5.0))
    is_low_stock = new_qty <= reorder_level

    item["quantity"] = new_qty
    item["updated_at"] = now
    db.set_doc("inventory", item_id, item)

    return {
        "status": "updated",
        "item_id": item_id,
        "item_name": item["item_name"],
        "unit": item.get("unit", "units"),
        "previous_quantity": prev_qty,
        "new_quantity": new_qty,
        "reorder_level": reorder_level,
        "is_low_stock": is_low_stock,
        "message": (
            f"{item['item_name']} ka stock update ho gaya: ab {new_qty:g} {item.get('unit', 'units')} bacha hai."
            + (" (Low stock alert!)" if is_low_stock else "")
        ),
    }


def get_low_stock_items() -> dict[str, Any]:
    """List all kirana inventory items whose current stock quantity is at or below their reorder level.

    Returns:
        A dict with the count and list of low-stock items requiring restock.
    """
    db = get_db()
    all_items = db.list_docs("inventory")
    low_items = [
        item
        for item in all_items
        if float(item.get("quantity", 0.0)) <= float(item.get("reorder_level", 0.0))
    ]
    low_items.sort(key=lambda x: float(x.get("quantity", 0.0)))

    names_summary = ", ".join(
        f"{i['item_name']} ({i['quantity']:g} {i.get('unit', '')})" for i in low_items
    )
    return {
        "status": "ok",
        "low_stock_count": len(low_items),
        "items": low_items,
        "message": (
            f"{len(low_items)} items low stock mein hain: {names_summary}."
            if low_items
            else "Sabhi items ka stock barabar hai, koi low stock nahi hai."
        ),
    }


# ============================================================================
# 3. COLLECTIONS & RECOVERY TOOLS
# ============================================================================


def list_overdue_customers(min_amount: float = 1000.0) -> dict[str, Any]:
    """List customers with outstanding khata dues greater than or equal to `min_amount`.

    Args:
        min_amount: Minimum rupee balance threshold to filter overdue customers (default 1000.0).

    Returns:
        A dict with total overdue amount and sorted list of overdue customers.
    """
    db = get_db()
    customers = db.list_docs("customers")
    overdue = [
        c for c in customers if float(c.get("balance", 0.0)) >= float(min_amount)
    ]
    overdue.sort(key=lambda x: float(x.get("balance", 0.0)), reverse=True)

    total_overdue = sum(float(c.get("balance", 0.0)) for c in overdue)
    summary = ", ".join(
        f"{c['name']} (₹{float(c['balance']):.0f})" for c in overdue
    )
    return {
        "status": "ok",
        "min_amount": float(min_amount),
        "overdue_count": len(overdue),
        "total_overdue_amount": round(total_overdue, 2),
        "customers": overdue,
        "message": (
            f"₹{min_amount:.0f} se upar {len(overdue)} grahak hain: {summary}."
            if overdue
            else f"₹{min_amount:.0f} se upar kisi ka udhaar baki nahi hai."
        ),
    }


def _build_reminder_text(customer_name: str, amount: float, language: str) -> str:
    lang = language.strip().lower()
    store = config.STORE_NAME
    upi = config.STORE_UPI_ID

    if lang == "hindi":
        return (
            f"नमस्ते {customer_name} जी, {store} में आपका ₹{amount:.0f} का खाता बकाया है। "
            f"कृपया UPI ({upi}) या दुकान पर भुगतान करें। धन्यवाद!"
        )
    if lang == "english":
        return (
            f"Hello {customer_name}, your khata balance of ₹{amount:.0f} is due at {store}. "
            f"Please pay via UPI ({upi}) or at the counter. Thank you!"
        )
    return (
        f"Namaste {customer_name} ji, {store} par aapka ₹{amount:.0f} ka khata balance baki hai. "
        f"Kripya UPI ({upi}) se payment kar dein. Dhanyavaad!"
    )


def send_payment_reminder(
    customer_name: str, language: str = "hinglish"
) -> dict[str, Any]:
    """Send a polite WhatsApp payment reminder to a customer and record it in the `reminders` collection.

    Uses Twilio WhatsApp Sandbox if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are configured;
    otherwise generates an instant WhatsApp Click-to-Chat URL (`https://wa.me/...`).

    Args:
        customer_name: Name of the customer to remind.
        language: Language of the reminder message ("hinglish", "hindi", or "english").

    Returns:
        A dict containing reminder_id, message text, delivery channel, WhatsApp link, and status.
    """
    db = get_db()
    customer = db.find_customer(customer_name)
    if not customer:
        return {
            "status": "not_found",
            "message": f"Customer '{customer_name}' not found.",
        }

    balance = float(customer.get("balance", 0.0))
    if balance <= 0:
        return {
            "status": "no_dues",
            "customer_name": customer["name"],
            "balance": balance,
            "message": f"{customer['name']} ka koi udhaar baki nahi hai (balance ₹{balance:.0f}).",
        }

    phone = customer.get("phone", "+919800000000")
    digits_only = "".join(ch for ch in phone if ch.isdigit())
    message_body = _build_reminder_text(customer["name"], balance, language)
    encoded_msg = urllib.parse.quote(message_body)
    whatsapp_url = f"https://wa.me/{digits_only}?text={encoded_msg}"

    channel = "whatsapp_click_to_chat"
    twilio_sid: str | None = None

    if config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN:
        try:
            from twilio.rest import Client

            client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
            msg = client.messages.create(
                from_=config.TWILIO_WHATSAPP_FROM,
                to=f"whatsapp:+{digits_only}",
                body=message_body,
            )
            channel = "twilio_whatsapp"
            twilio_sid = msg.sid
        except Exception as exc:  # Fallback cleanly to Click-to-Chat URL
            channel = f"whatsapp_click_to_chat (twilio_fallback: {type(exc).__name__})"

    reminder_id = f"rem_{uuid.uuid4().hex[:8]}"
    now = utc_now_iso()
    reminder_doc = {
        "id": reminder_id,
        "customer_id": customer["id"],
        "customer_name": customer["name"],
        "phone": phone,
        "amount": round(balance, 2),
        "language": language.strip().lower(),
        "message": message_body,
        "channel": channel,
        "twilio_sid": twilio_sid,
        "whatsapp_url": whatsapp_url,
        "status": "sent",
        "sent_at": now,
        "paid_at": None,
    }
    db.set_doc("reminders", reminder_id, reminder_doc)

    return {
        "status": "sent",
        "reminder_id": reminder_id,
        "reminder": reminder_doc,
        "whatsapp_url": whatsapp_url,
        "message": (
            f"{customer['name']} ko ₹{balance:.0f} ka WhatsApp payment reminder bhej diya gaya hai."
        ),
    }


def mark_reminder_paid(reminder_id: str) -> dict[str, Any]:
    """Mark a previously sent payment reminder as paid and settle the amount in the customer's khata ledger.

    Args:
        reminder_id: Unique ID of the reminder (e.g., "rem_001") or customer name to match latest sent reminder.

    Returns:
        A dict with updated reminder status, customer's new balance, and updated recovery metrics.
    """
    db = get_db()
    reminder = db.get_doc("reminders", reminder_id)

    # Also allow matching by customer name if the shopkeeper says "mark Suresh's reminder paid"
    if reminder is None:
        all_reminders = db.list_docs("reminders")
        target = reminder_id.strip().lower()
        matching = [
            r
            for r in all_reminders
            if r.get("status") == "sent"
            and (
                r.get("id", "").lower() == target
                or target in r.get("customer_name", "").lower()
            )
        ]
        if matching:
            matching.sort(key=lambda x: x.get("sent_at", ""), reverse=True)
            reminder = matching[0]

    if reminder is None:
        return {
            "status": "not_found",
            "reminder_id": reminder_id,
            "message": f"No sent reminder found matching '{reminder_id}'.",
        }

    if reminder.get("status") == "paid":
        return {
            "status": "already_paid",
            "reminder_id": reminder["id"],
            "message": f"Reminder {reminder['id']} for {reminder['customer_name']} is already marked paid.",
        }

    now = utc_now_iso()
    amount = float(reminder.get("amount", 0.0))
    customer_name = reminder.get("customer_name", "")

    reminder["status"] = "paid"
    reminder["paid_at"] = now
    db.set_doc("reminders", reminder["id"], reminder)

    # Settle corresponding payment in customer's ledger
    ledger_result = record_khata_entry(
        customer_name=customer_name,
        amount=amount,
        items=f"WhatsApp Reminder Settlement ({reminder['id']})",
        tx_type="payment",
        confirmed_by_voice=True,
    )

    all_reminders = db.list_docs("reminders")
    paid_count = sum(1 for r in all_reminders if r.get("status") == "paid")
    total_recovered = sum(
        float(r.get("amount", 0.0))
        for r in all_reminders
        if r.get("status") == "paid"
    )

    return {
        "status": "paid",
        "reminder_id": reminder["id"],
        "customer_name": customer_name,
        "settled_amount": amount,
        "new_customer_balance": ledger_result.get("new_balance", 0.0),
        "recovery_metrics": {
            "total_reminders": len(all_reminders),
            "paid_reminders": paid_count,
            "total_recovered_rupees": round(total_recovered, 2),
        },
        "message": (
            f"{customer_name} ka ₹{amount:.0f} reminder paid mark ho gaya aur khata balance update ho gaya!"
        ),
    }
