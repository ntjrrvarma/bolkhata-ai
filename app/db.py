"""Unified data access layer supporting Google Cloud Firestore and local JSON mock mode.

Collections:
- customers: {id, name, phone, balance, last_tx_at, language, notes}
- transactions: {id, customer_id, customer_name, amount, tx_type, items, confirmed_by_voice, created_at}
- inventory: {id, item_name, unit, quantity, reorder_level, price_per_unit, updated_at}
- reminders: {id, customer_id, customer_name, phone, amount, language, message, channel, whatsapp_url, status, sent_at, paid_at}
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import config

COLLECTIONS = ("customers", "transactions", "inventory", "reminders")


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def normalize_key(text: str) -> str:
    """Normalize a customer or item name into a stable slug ID."""
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in text.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or uuid.uuid4().hex[:8]


class DatabaseManager:
    """Abstraction over Google Cloud Firestore with a thread-safe JSON mock fallback."""

    def __init__(self, use_mock: bool | None = None, mock_path: Path | None = None) -> None:
        self.use_mock = config.USE_MOCK_DB if use_mock is None else use_mock
        self.mock_path = mock_path or config.MOCK_DB_PATH
        self._lock = threading.RLock()
        self._firestore_client = None

        if not self.use_mock:
            from google.cloud import firestore  # lazy import for fast local tests

            self._firestore_client = firestore.Client(
                project=config.GOOGLE_CLOUD_PROJECT,
                database=config.FIRESTORE_DATABASE,
            )
        else:
            self._ensure_mock_file()

    def _ensure_mock_file(self) -> None:
        with self._lock:
            self.mock_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.mock_path.exists():
                empty_payload = {col: {} for col in COLLECTIONS}
                self.mock_path.write_text(
                    json.dumps(empty_payload, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

    def _read_mock(self) -> dict[str, dict[str, dict[str, Any]]]:
        with self._lock:
            self._ensure_mock_file()
            raw = self.mock_path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
            for col in COLLECTIONS:
                data.setdefault(col, {})
            return data

    def _write_mock(self, data: dict[str, dict[str, dict[str, Any]]]) -> None:
        with self._lock:
            self.mock_path.parent.mkdir(parents=True, exist_ok=True)
            self.mock_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def reset_collection(self, collection: str) -> None:
        """Clear all documents in a collection."""
        if self.use_mock:
            data = self._read_mock()
            data[collection] = {}
            self._write_mock(data)
            return

        assert self._firestore_client is not None
        docs = self._firestore_client.collection(collection).stream()
        for doc in docs:
            doc.reference.delete()

    def set_doc(self, collection: str, doc_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Create or overwrite a document in `collection`."""
        record = {"id": doc_id, **payload}
        if self.use_mock:
            data = self._read_mock()
            data.setdefault(collection, {})[doc_id] = record
            self._write_mock(data)
            return record

        assert self._firestore_client is not None
        self._firestore_client.collection(collection).document(doc_id).set(record)
        return record

    def get_doc(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        """Fetch a single document by ID."""
        if self.use_mock:
            data = self._read_mock()
            doc = data.get(collection, {}).get(doc_id)
            return dict(doc) if doc else None

        assert self._firestore_client is not None
        snap = self._firestore_client.collection(collection).document(doc_id).get()
        if not snap.exists:
            return None
        doc_dict = snap.to_dict() or {}
        doc_dict.setdefault("id", snap.id)
        return doc_dict

    def list_docs(self, collection: str) -> list[dict[str, Any]]:
        """Return all documents in `collection`."""
        if self.use_mock:
            data = self._read_mock()
            return [dict(v) for v in data.get(collection, {}).values()]

        assert self._firestore_client is not None
        docs = self._firestore_client.collection(collection).stream()
        result: list[dict[str, Any]] = []
        for snap in docs:
            item = snap.to_dict() or {}
            item.setdefault("id", snap.id)
            result.append(item)
        return result

    def find_customer(self, customer_name: str) -> dict[str, Any] | None:
        """Case-insensitive lookup by exact ID, exact name, or partial token match."""
        slug = normalize_key(customer_name)
        direct = self.get_doc("customers", slug)
        if direct:
            return direct

        target = customer_name.strip().lower()
        customers = self.list_docs("customers")
        for cust in customers:
            if cust.get("name", "").strip().lower() == target:
                return cust
        for cust in customers:
            name_lower = cust.get("name", "").strip().lower()
            if target in name_lower or name_lower in target:
                return cust
        return None

    def find_inventory_item(self, item_name: str) -> dict[str, Any] | None:
        """Case-insensitive lookup of an inventory item by ID or partial name."""
        slug = normalize_key(item_name)
        direct = self.get_doc("inventory", slug)
        if direct:
            return direct

        target = item_name.strip().lower()
        items = self.list_docs("inventory")
        for item in items:
            if item.get("item_name", "").strip().lower() == target:
                return item
        for item in items:
            name_lower = item.get("item_name", "").strip().lower()
            if target in name_lower or name_lower in target:
                return item
        return None


_db_instance: DatabaseManager | None = None


def get_db() -> DatabaseManager:
    """Return the singleton DatabaseManager instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager()
    return _db_instance
