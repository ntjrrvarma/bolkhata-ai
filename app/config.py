"""Environment configuration for BolKhata AI."""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _as_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


GOOGLE_CLOUD_PROJECT: str = os.getenv("GOOGLE_CLOUD_PROJECT", "bolkhata-demo")
GOOGLE_CLOUD_LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
GOOGLE_GENAI_USE_VERTEXAI: bool = _as_bool(os.getenv("GOOGLE_GENAI_USE_VERTEXAI"), True)
FIRESTORE_DATABASE: str = os.getenv("FIRESTORE_DATABASE", "(default)")

GEMINI_LIVE_MODEL: str = os.getenv(
    "GEMINI_LIVE_MODEL", "gemini-2.0-flash-live-preview-04-09"
)

USE_MOCK_DB: bool = _as_bool(os.getenv("USE_MOCK_DB"), True)
MOCK_DB_PATH: Path = BASE_DIR / os.getenv("MOCK_DB_PATH", "data/mock_db.json")

STORE_NAME: str = os.getenv("STORE_NAME", "Sharma Kirana & General Store")
STORE_UPI_ID: str = os.getenv("STORE_UPI_ID", "sharmakirana@okaxis")

TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_WHATSAPP_FROM: str = os.getenv(
    "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"
).strip()
