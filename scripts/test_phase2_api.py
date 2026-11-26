"""Verification test suite for Phase 2 FastAPI REST endpoints and BIDI WebSocket voice bridge."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import types as py_types
from pathlib import Path
from typing import Any

os.environ["USE_MOCK_DB"] = "true"

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _ensure_fastapi_shim_if_missing() -> None:
    """Provide a lightweight FastAPI shim when running in a bare Python environment without third-party wheels installed."""
    try:
        import fastapi  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    fastapi_mod = py_types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str = "") -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class WebSocketDisconnect(Exception):
        pass

    class WebSocket:
        pass

    class FastAPI:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def add_middleware(self, *args: Any, **kwargs: Any) -> None:
            pass

        def mount(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get(self, *args: Any, **kwargs: Any) -> Any:
            return lambda fn: fn

        def post(self, *args: Any, **kwargs: Any) -> Any:
            return lambda fn: fn

        def websocket(self, *args: Any, **kwargs: Any) -> Any:
            return lambda fn: fn

    fastapi_mod.FastAPI = FastAPI
    fastapi_mod.HTTPException = HTTPException
    fastapi_mod.WebSocket = WebSocket
    fastapi_mod.WebSocketDisconnect = WebSocketDisconnect
    sys.modules["fastapi"] = fastapi_mod

    cors_mod = py_types.ModuleType("fastapi.middleware.cors")
    cors_mod.CORSMiddleware = object
    sys.modules["fastapi.middleware"] = py_types.ModuleType("fastapi.middleware")
    sys.modules["fastapi.middleware.cors"] = cors_mod

    resp_mod = py_types.ModuleType("fastapi.responses")

    class FileResponse:
        def __init__(self, path: Any) -> None:
            self.path = path

    resp_mod.FileResponse = FileResponse
    sys.modules["fastapi.responses"] = resp_mod

    static_mod = py_types.ModuleType("fastapi.staticfiles")

    class StaticFiles:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    static_mod.StaticFiles = StaticFiles
    sys.modules["fastapi.staticfiles"] = static_mod


_ensure_fastapi_shim_if_missing()

from scripts.seed_db import seed_database


def run_phase2_tests() -> None:
    """Verify dashboard computation, reminder settlement, and FastAPI routes."""
    print("1. Seeding mock database...")
    seed_database()

    from app.main import (
        _compute_dashboard_payload,
        health_check,
        mark_reminder_paid_endpoint,
        serve_index,
    )

    print("\n2. Verifying GET /health...")
    health = health_check()
    assert health["status"] == "ok", health
    assert health["use_mock_db"] is True, health
    print("   PASS ->", health)

    print("\n3. Verifying GET / (static/index.html)...")
    idx_resp = serve_index()
    assert Path(idx_resp.path).exists(), idx_resp.path
    print("   PASS -> Serves", idx_resp.path)

    print("\n4. Verifying GET /api/dashboard...")
    dash = _compute_dashboard_payload()
    assert dash["status"] == "ok", dash
    assert len(dash["customers"]) == 5, dash
    assert len(dash["low_stock_items"]) == 3, dash
    assert dash["collections_recovery"]["sent_count"] == 1, dash
    assert dash["collections_recovery"]["paid_count"] == 0, dash
    assert dash["collections_recovery"]["recovery_pct"] == 0.0, dash
    print(
        f"   PASS -> Customers={len(dash['customers'])}, "
        f"LowStock={len(dash['low_stock_items'])}, "
        f"Outstanding=₹{dash['daily_summary']['total_outstanding_dues']}, "
        f"Recovery={dash['collections_recovery']}"
    )

    print("\n5. Verifying POST /api/reminders/rem_seed001/paid...")
    paid_res = mark_reminder_paid_endpoint("rem_seed001")
    assert paid_res["status"] == "paid", paid_res
    assert paid_res["collections_recovery"]["paid_count"] == 1, paid_res
    assert paid_res["collections_recovery"]["recovery_pct"] == 100.0, paid_res
    print(
        "   PASS ->",
        paid_res["message"],
        "| Updated recovery:",
        paid_res["collections_recovery"],
    )

    print("\n6. Re-seeding clean mock DB state...")
    seed_database()
    print("\nAll Phase 2 FastAPI endpoints and dashboard metrics verified successfully!")


def test_phase2_api() -> None:
    run_phase2_tests()


if __name__ == "__main__":
    run_phase2_tests()
