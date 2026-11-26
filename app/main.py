"""FastAPI Bidirectional Voice Bridge & Live Dashboard API for BolKhata AI (Phase 2).

Endpoints:
- GET  /                                -> Serves /static/index.html
- GET  /health                          -> Cloud Run health check (also /api/health)
- GET  /api/dashboard                   -> Customers/khata, low-stock items, daily summary, & recovery metrics
- POST /api/reminders/{reminder_id}/paid -> Marks a payment reminder as paid and settles ledger balance
- WS   /ws/{session_id}                 -> Full-duplex audio + JSON telemetry bridge to ADK Runner.run_live()
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.db import get_db
from app.tools import (
    get_customer_balance,
    get_daily_summary,
    get_low_stock_items,
    list_overdue_customers,
    mark_reminder_paid,
)

# Ensure Google GenAI environment variables are exported before ADK initializes
os.environ.setdefault(
    "GOOGLE_GENAI_USE_VERTEXAI",
    "TRUE" if config.GOOGLE_GENAI_USE_VERTEXAI else "FALSE",
)
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", config.GOOGLE_CLOUD_PROJECT)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", config.GOOGLE_CLOUD_LOCATION)

logger = logging.getLogger("bolkhata.main")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="BolKhata AI",
    description="Hands-Free Code-Switched Voice AI Copilot for Indian Kirana Stores",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

APP_NAME = "bolkhata_ai"
_session_service: Any = None
_runner: Any = None


def _get_adk_runner() -> tuple[Any, Any]:
    """Lazy-initialize ADK InMemorySessionService and Runner so REST tests work even without ADK installed."""
    global _session_service, _runner
    if _runner is None or _session_service is None:
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from app.agent import root_agent

        _session_service = InMemorySessionService()
        _runner = Runner(
            app_name=APP_NAME,
            agent=root_agent,
            session_service=_session_service,
        )
    return _runner, _session_service


async def _ensure_adk_session(session_service: Any, user_id: str, session_id: str) -> Any:
    """Fetch or create an ADK session across sync/async InMemorySessionService versions."""
    get_fn = session_service.get_session
    res = get_fn(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    session = await res if inspect.isawaitable(res) else res
    if session is None:
        create_fn = session_service.create_session
        res = create_fn(app_name=APP_NAME, user_id=user_id, session_id=session_id)
        session = await res if inspect.isawaitable(res) else res
    return session


def _build_bidi_run_config() -> Any:
    """Construct RunConfig with BIDI streaming, AUDIO modality, session resumption, and context window compression."""
    from google.adk.agents.run_config import RunConfig, StreamingMode
    from google.genai import types

    kwargs: dict[str, Any] = {
        "streaming_mode": StreamingMode.BIDI,
        "response_modalities": ["AUDIO"],
    }

    # Enable transcription of both user voice input and agent voice output when supported
    for attr in ("input_audio_transcription", "output_audio_transcription"):
        if attr in RunConfig.model_fields:
            kwargs[attr] = types.AudioTranscriptionConfig()

    # Enable session resumption to avoid re-initializing sessions on transient drops
    if "session_resumption" in RunConfig.model_fields:
        kwargs["session_resumption"] = types.SessionResumptionConfig(transparent=True)

    # Enable context window compression to keep Gemini Live token/credit consumption low
    if "context_window_compression" in RunConfig.model_fields:
        kwargs["context_window_compression"] = types.ContextWindowCompressionConfig(
            trigger_tokens=16000,
            sliding_window=types.SlidingWindow(target_tokens=8000),
        )

    return RunConfig(**kwargs)


# ============================================================================
# REST & UI ENDPOINTS
# ============================================================================


@app.get("/")
def serve_index() -> FileResponse:
    """Serve the Vanilla HTML/CSS/JS frontend at root `/`."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="static/index.html not found")
    return FileResponse(index_path)


@app.get("/health")
@app.get("/api/health")
def health_check() -> dict[str, Any]:
    """Cloud Run readiness & configuration health check."""
    return {
        "status": "ok",
        "service": "bolkhata-ai",
        "store_name": config.STORE_NAME,
        "model": config.GEMINI_LIVE_MODEL,
        "use_mock_db": config.USE_MOCK_DB,
    }


def _compute_dashboard_payload() -> dict[str, Any]:
    """Assemble live store dashboard metrics: customers, low-stock items, daily summary, and collections recovery."""
    db = get_db()
    customers = sorted(
        db.list_docs("customers"),
        key=lambda c: float(c.get("balance", 0.0)),
        reverse=True,
    )
    transactions = sorted(
        db.list_docs("transactions"),
        key=lambda tx: tx.get("created_at", ""),
        reverse=True,
    )
    inventory = sorted(
        db.list_docs("inventory"),
        key=lambda item: float(item.get("quantity", 0.0)),
    )
    reminders = sorted(
        db.list_docs("reminders"),
        key=lambda rem: rem.get("sent_at", ""),
        reverse=True,
    )

    summary = get_daily_summary()
    low_stock = get_low_stock_items()
    overdue = list_overdue_customers(min_amount=1000.0)

    sent_count = len(reminders)
    paid_count = sum(1 for r in reminders if r.get("status") == "paid")
    total_reminder_amount = sum(float(r.get("amount", 0.0)) for r in reminders)
    recovered_amount = sum(
        float(r.get("amount", 0.0)) for r in reminders if r.get("status") == "paid"
    )
    recovery_pct = (
        round((paid_count / sent_count) * 100.0, 1) if sent_count > 0 else 0.0
    )
    amount_recovery_pct = (
        round((recovered_amount / total_reminder_amount) * 100.0, 1)
        if total_reminder_amount > 0
        else 0.0
    )

    return {
        "status": "ok",
        "store_name": config.STORE_NAME,
        "store_upi_id": config.STORE_UPI_ID,
        "daily_summary": {
            "total_credit_given": summary["total_credit_given"],
            "total_payments_collected": summary["total_payments_collected"],
            "total_outstanding_dues": summary["total_outstanding_dues"],
            "transaction_count": summary["transaction_count"],
            "customer_count": summary["customer_count"],
            "message": summary["message"],
        },
        "collections_recovery": {
            "sent_count": sent_count,
            "paid_count": paid_count,
            "pending_count": max(0, sent_count - paid_count),
            "recovery_pct": recovery_pct,
            "amount_recovery_pct": amount_recovery_pct,
            "total_reminder_amount": round(total_reminder_amount, 2),
            "recovered_amount": round(recovered_amount, 2),
        },
        "customers": customers,
        "overdue_customers": overdue["customers"],
        "low_stock_items": low_stock["items"],
        "inventory": inventory,
        "recent_transactions": transactions[:15],
        "reminders": reminders,
    }


@app.get("/api/dashboard")
@app.get("/api/state")
def get_dashboard() -> dict[str, Any]:
    """Return full live dashboard state for the kirana store UI."""
    return _compute_dashboard_payload()


@app.post("/api/reminders/{reminder_id}/paid")
def mark_reminder_paid_endpoint(reminder_id: str) -> dict[str, Any]:
    """Mark a pilot payment reminder as paid and return updated recovery metrics & dashboard snapshot."""
    result = mark_reminder_paid(reminder_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("message"))
    dashboard = _compute_dashboard_payload()
    return {
        **result,
        "collections_recovery": dashboard["collections_recovery"],
        "daily_summary": dashboard["daily_summary"],
    }


@app.get("/api/customers/{customer_name}")
def customer_balance_endpoint(customer_name: str) -> dict[str, Any]:
    """Lookup customer balance and recent transactions."""
    return get_customer_balance(customer_name)


# ============================================================================
# BIDIRECTIONAL VOICE BRIDGE (`/ws/{session_id}`)
# ============================================================================


def _serialize_safe(obj: Any) -> Any:
    """Convert arbitrary SDK objects into JSON-safe primitives."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _serialize_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_serialize_safe(item) for item in obj]
    if hasattr(obj, "model_dump"):
        return _serialize_safe(obj.model_dump())
    return str(obj)


@app.websocket("/ws/{session_id}")
async def voice_bridge_websocket(websocket: WebSocket, session_id: str) -> None:
    """Full-duplex WebSocket bridge between browser 16kHz PCM audio and Google ADK `Runner.run_live()`."""
    await websocket.accept()
    user_id = f"shopkeeper_{session_id}"

    # Shared state between upstream and downstream coroutines for latency measurement
    latency_state: dict[str, float | None] = {
        "speech_end_ts": None,
        "awaiting_first_audio": False,
    }

    try:
        from google.adk.agents.live_request_queue import LiveRequestQueue
        from google.genai import types

        runner, session_service = _get_adk_runner()
        await _ensure_adk_session(session_service, user_id=user_id, session_id=session_id)
        run_config = _build_bidi_run_config()
    except Exception as init_err:
        logger.exception("Failed to initialize ADK Live Runner for session %s", session_id)
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"ADK initialization error: {init_err}",
                }
            )
            await websocket.close(code=1011)
        except Exception:
            pass
        return

    live_request_queue = LiveRequestQueue()

    async def upstream_task() -> None:
        """Receive raw 16kHz 16-bit PCM audio bytes or JSON control events from the browser."""
        try:
            while True:
                message = await websocket.receive()
                msg_type = message.get("type")

                if msg_type == "websocket.disconnect":
                    break

                # 1. Raw binary 16kHz 16-bit mono PCM audio frame
                if message.get("bytes") is not None:
                    pcm_bytes: bytes = message["bytes"]
                    if pcm_bytes:
                        audio_blob = types.Blob(
                            data=pcm_bytes,
                            mime_type="audio/pcm;rate=16000",
                        )
                        live_request_queue.send_realtime(audio_blob)
                    continue

                # 2. JSON control events (`speech_end`, `reset_session`, `text`, `audio_b64`)
                raw_text = message.get("text")
                if not raw_text:
                    continue

                try:
                    payload = json.loads(raw_text)
                except json.JSONDecodeError:
                    continue

                event_type = payload.get("type", "")

                if event_type == "speech_end":
                    client_ts = payload.get("timestamp_ms")
                    latency_state["speech_end_ts"] = time.perf_counter()
                    latency_state["client_speech_end_ms"] = (
                        float(client_ts) if client_ts is not None else None
                    )
                    latency_state["awaiting_first_audio"] = 1.0
                    if hasattr(live_request_queue, "send_activity_end"):
                        live_request_queue.send_activity_end()

                elif event_type == "speech_start":
                    latency_state["awaiting_first_audio"] = None
                    if hasattr(live_request_queue, "send_activity_start"):
                        live_request_queue.send_activity_start()

                elif event_type == "reset_session":
                    latency_state["speech_end_ts"] = None
                    latency_state["awaiting_first_audio"] = None
                    await _ensure_adk_session(
                        session_service,
                        user_id=user_id,
                        session_id=session_id,
                    )
                    await websocket.send_json(
                        {
                            "type": "session_reset",
                            "session_id": session_id,
                            "message": "Session reset successfully.",
                        }
                    )

                elif event_type == "text":
                    user_text = str(payload.get("text", "")).strip()
                    if user_text:
                        latency_state["speech_end_ts"] = time.perf_counter()
                        latency_state["awaiting_first_audio"] = 1.0
                        content = types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=user_text)],
                        )
                        live_request_queue.send_content(content)

                elif event_type == "audio":
                    b64_data = payload.get("data")
                    if b64_data:
                        pcm_bytes = base64.b64decode(b64_data)
                        audio_blob = types.Blob(
                            data=pcm_bytes,
                            mime_type=payload.get("mime_type", "audio/pcm;rate=16000"),
                        )
                        live_request_queue.send_realtime(audio_blob)

        except WebSocketDisconnect:
            logger.info("Client disconnected upstream on session %s", session_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Upstream task stopped for session %s: %s", session_id, exc)
        finally:
            live_request_queue.close()

    async def downstream_task() -> None:
        """Stream agent audio bytes and JSON telemetry events from ADK `Runner.run_live()` to the browser."""
        try:
            live_events = runner.run_live(
                user_id=user_id,
                session_id=session_id,
                live_request_queue=live_request_queue,
                run_config=run_config,
            )

            async for event in live_events:
                author = getattr(event, "author", None) or "bolkhata_root"

                # 1. Barge-in / interruption notification
                if getattr(event, "interrupted", False):
                    await websocket.send_json(
                        {
                            "type": "interrupted",
                            "author": author,
                        }
                    )

                # 2. Input & output audio transcriptions (if emitted as dedicated event fields)
                input_tx = getattr(event, "input_transcription", None)
                if input_tx and getattr(input_tx, "text", None):
                    await websocket.send_json(
                        {
                            "type": "transcript",
                            "role": "user",
                            "author": "user",
                            "text": input_tx.text,
                            "finished": bool(getattr(input_tx, "finished", False)),
                        }
                    )

                output_tx = getattr(event, "output_transcription", None)
                if output_tx and getattr(output_tx, "text", None):
                    await websocket.send_json(
                        {
                            "type": "transcript",
                            "role": "agent",
                            "author": author,
                            "text": output_tx.text,
                            "finished": bool(getattr(output_tx, "finished", False)),
                        }
                    )

                # 3. Inspect content parts for audio bytes, text transcripts, tool calls, and tool results
                content = getattr(event, "content", None)
                parts = getattr(content, "parts", None) or []
                role = getattr(content, "role", "model") or "model"

                for part in parts:
                    # 3a. Raw audio bytes from Gemini Live
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data and getattr(inline_data, "data", None):
                        mime_type = getattr(inline_data, "mime_type", "") or ""
                        raw_data = inline_data.data
                        if isinstance(raw_data, str):
                            raw_data = base64.b64decode(raw_data)

                        if mime_type.startswith("audio/") or isinstance(raw_data, (bytes, bytearray)):
                            # Emit latency metric on first audio byte after speech_end
                            if (
                                latency_state.get("awaiting_first_audio")
                                and latency_state.get("speech_end_ts") is not None
                            ):
                                elapsed_ms = round(
                                    (time.perf_counter() - float(latency_state["speech_end_ts"]))
                                    * 1000.0,
                                    1,
                                )
                                latency_state["awaiting_first_audio"] = None
                                await websocket.send_json(
                                    {
                                        "type": "latency_metric",
                                        "latency_ms": elapsed_ms,
                                        "author": author,
                                    }
                                )

                            await websocket.send_bytes(bytes(raw_data))
                            continue

                    # 3b. Text transcript part
                    part_text = getattr(part, "text", None)
                    if part_text:
                        await websocket.send_json(
                            {
                                "type": "transcript",
                                "role": "user" if role == "user" else "agent",
                                "author": author,
                                "text": part_text,
                                "partial": bool(getattr(event, "partial", False)),
                            }
                        )

                    # 3c. ADK Tool Call trace
                    fn_call = getattr(part, "function_call", None)
                    if fn_call:
                        await websocket.send_json(
                            {
                                "type": "tool_call",
                                "author": author,
                                "name": getattr(fn_call, "name", ""),
                                "id": getattr(fn_call, "id", None),
                                "args": _serialize_safe(getattr(fn_call, "args", {})),
                            }
                        )

                    # 3d. ADK Tool Result trace
                    fn_resp = getattr(part, "function_response", None)
                    if fn_resp:
                        await websocket.send_json(
                            {
                                "type": "tool_result",
                                "author": author,
                                "name": getattr(fn_resp, "name", ""),
                                "id": getattr(fn_resp, "id", None),
                                "result": _serialize_safe(getattr(fn_resp, "response", {})),
                            }
                        )

                # 4. Turn complete signal
                if getattr(event, "turn_complete", False):
                    await websocket.send_json(
                        {
                            "type": "turn_complete",
                            "author": author,
                        }
                    )

        except WebSocketDisconnect:
            logger.info("Client disconnected downstream on session %s", session_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Downstream task error for session %s: %s", session_id, exc)
            try:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": str(exc),
                    }
                )
            except Exception:
                pass
        finally:
            live_request_queue.close()

    # Run upstream and downstream concurrently via asyncio.gather()
    up_future = asyncio.create_task(upstream_task())
    down_future = asyncio.create_task(downstream_task())

    def _cancel_peer(completed_task: asyncio.Task) -> None:
        peer = down_future if completed_task is up_future else up_future
        if not peer.done():
            peer.cancel()

    up_future.add_done_callback(_cancel_peer)
    down_future.add_done_callback(_cancel_peer)

    try:
        await asyncio.gather(up_future, down_future, return_exceptions=True)
    except Exception as exc:
        logger.debug("Session %s cleanup exception: %s", session_id, exc)
    finally:
        live_request_queue.close()
        try:
            await websocket.close()
        except Exception:
            pass
