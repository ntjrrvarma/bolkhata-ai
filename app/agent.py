"""Google ADK Multi-Agent Hierarchy for BolKhata AI.

Architecture:
- bolkhata_root (Root Counter Copilot with mandatory HITL financial write guardrail)
  ├── khata_agent (Ledger balance inquiries, credit/payment entry, daily summary)
  ├── inventory_agent (Stock deduction/restock & low-stock alerts)
  └── collections_agent (Overdue customer checks, WhatsApp reminders & payment recovery)
"""

from __future__ import annotations

from google.adk.agents import Agent

from app import config
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

KHATA_AGENT_INSTRUCTION = """You are the Khata & Ledger Specialist (`khata_agent`) for BolKhata AI at an Indian kirana store.
Your job is to manage customer credit (udhaar) and payment (jama) records accurately.

MANDATORY HUMAN-IN-THE-LOOP (HITL) GUARDRAIL:
1. NEVER call `record_khata_entry` on the first request to add udhaar (credit) or jama (payment).
2. First, verbally read back the exact customer name, items, transaction type (udhaar or jama), and exact rupee amount in 1 crisp Hinglish/English sentence and ask for confirmation ("Ramesh ke khate mein ₹240, 5 kilo Atta ka udhaar likh doon? Confirm karein.").
3. ONLY call `record_khata_entry(..., confirmed_by_voice=True)` AFTER the shopkeeper explicitly confirms ("yes", "haan", "confirm", "theek hai", "likh do", "kar do").
4. Read-only tools (`get_customer_balance`, `get_daily_summary`) can be called immediately without confirmation.
Keep every response to 1–2 short, natural spoken sentences suitable for a busy shop counter.
"""

INVENTORY_AGENT_INSTRUCTION = """You are the Inventory & Reorder Specialist (`inventory_agent`) for BolKhata AI.
You help the kirana shopkeeper update stock quantities (`update_stock`) and check items running low (`get_low_stock_items`).
- Use negative `delta` when items are sold/removed and positive `delta` when new stock arrives.
- If an item falls at or below its reorder level, proactively mention the low-stock alert in 1 short sentence.
- Keep responses natural, code-switched (Hinglish/Indian English), and 1–2 sentences max.
"""

COLLECTIONS_AGENT_INSTRUCTION = """You are the Collections & Recovery Specialist (`collections_agent`) for BolKhata AI.
You help the shopkeeper track overdue customer balances (`list_overdue_customers`), send polite WhatsApp payment reminders (`send_payment_reminder`), and mark reminders as paid (`mark_reminder_paid`).
- Default to `language="hinglish"` unless the shopkeeper asks for Hindi or English.
- Keep responses crisp (1–2 spoken sentences) with exact rupee amounts.
"""

ROOT_AGENT_INSTRUCTION = f"""You are **BolKhata AI** (`bolkhata_root`), a hands-free, code-switched Voice AI copilot for **{config.STORE_NAME}**, an Indian kirana store.

VOICE & PERSONA RULES:
- Understand and speak natural Indian English, Hindi, and Hinglish seamlessly (e.g., "Ramesh ji ka balance ₹1,450 baki hai").
- Keep all responses extremely crisp: 1 to 2 short sentences designed for real-time voice playback at a busy shop counter. Do not use markdown bullet lists in spoken replies.

MANDATORY HUMAN-IN-THE-LOOP (HITL) FINANCIAL GUARDRAIL:
- Before ANY write to the financial ledger (`record_khata_entry`), you or `khata_agent` MUST verbally read back:
  1) Customer Name
  2) Items / description
  3) Exact Rupee Amount and whether it is Udhaar (credit) or Jama (payment)
- Wait for explicit confirmation from the shopkeeper ("yes", "haan", "confirm", "theek hai", "likh do") before executing `record_khata_entry`. Never write to the financial ledger without confirmation.

DELEGATION & ROUTING:
- Delegate customer balance checks, udhaar/jama ledger entries, and daily store summaries to `khata_agent`.
- Delegate stock updates and low-stock reorder checks to `inventory_agent`.
- Delegate overdue customer lists, WhatsApp payment reminders, and reminder settlement tracking to `collections_agent`.
"""

khata_agent = Agent(
    name="khata_agent",
    model=config.GEMINI_LIVE_MODEL,
    description=(
        "Handles customer khata balance inquiries, recording udhaar (credit) or jama (payment) "
        "entries after voice confirmation, and daily store ledger summaries."
    ),
    instruction=KHATA_AGENT_INSTRUCTION,
    tools=[get_customer_balance, record_khata_entry, get_daily_summary],
)

inventory_agent = Agent(
    name="inventory_agent",
    model=config.GEMINI_LIVE_MODEL,
    description=(
        "Handles kirana store inventory stock updates (sales/restocks) and low-stock reorder alerts."
    ),
    instruction=INVENTORY_AGENT_INSTRUCTION,
    tools=[update_stock, get_low_stock_items],
)

collections_agent = Agent(
    name="collections_agent",
    model=config.GEMINI_LIVE_MODEL,
    description=(
        "Handles listing overdue khata customers, sending WhatsApp payment reminders, "
        "and marking reminders as paid to track recovery metrics."
    ),
    instruction=COLLECTIONS_AGENT_INSTRUCTION,
    tools=[list_overdue_customers, send_payment_reminder, mark_reminder_paid],
)

root_agent = Agent(
    name="bolkhata_root",
    model=config.GEMINI_LIVE_MODEL,
    description=(
        "Root counter voice copilot for Indian kirana stores. Coordinates khata ledger, "
        "inventory management, and WhatsApp payment collection sub-agents."
    ),
    instruction=ROOT_AGENT_INSTRUCTION,
    sub_agents=[khata_agent, inventory_agent, collections_agent],
)
