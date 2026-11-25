"""All settings, thresholds and logging setup live here (env-driven via .env)."""
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


GROQ_API_KEY = _env("GROQ_API_KEY", "")
LLM_MODEL = _env("GROQ_LLM_MODEL", "openai/gpt-oss-120b")
LLM_FALLBACK_MODEL = _env("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")  # used on the retry: separate per-model rate limit
LLM_REASONING = _env("GROQ_REASONING_EFFORT", "low")  # only sent to gpt-oss models
STT_MODEL = _env("GROQ_STT_MODEL", "whisper-large-v3-turbo")
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

DB_PATH = _env("DB_PATH", str(ROOT / "agent.db"))
CHROMA_DIR = _env("CHROMA_DIR", str(ROOT / "chroma_data"))
KB_DIR = ROOT / "kb"

BUSINESS_NAME = _env("BUSINESS_NAME", "BrightPath Academy")
CRM_WEBHOOK_URL = _env("CRM_WEBHOOK_URL", "")  # empty = local table only
ALLOWED_ORIGINS = _env("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")

# RAG tuning (the likely live-coding knobs)
RAG_TOP_K = int(_env("RAG_TOP_K", "4"))
RAG_THRESHOLD = float(_env("RAG_THRESHOLD", "0.35"))  # min cosine similarity
CHUNK_CHARS = int(_env("CHUNK_CHARS", "1200"))  # ~300 tokens
CHUNK_OVERLAP = int(_env("CHUNK_OVERLAP", "200"))  # ~50 tokens

# Agent limits
MAX_TOOL_ITERATIONS = 4
MAX_TURNS = int(_env("MAX_TURNS", "30"))
MAX_CALL_SECONDS = int(_env("MAX_CALL_SECONDS", "1200"))
HISTORY_LIMIT = 12  # messages kept verbatim before older ones are summarised
LLM_TIMEOUT = float(_env("LLM_TIMEOUT", "20"))

# Abuse / upload limits
MAX_AUDIO_BYTES = int(_env("MAX_AUDIO_BYTES", str(5 * 1024 * 1024)))
ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4"}
RATE_IP_PER_MIN = int(_env("RATE_IP_PER_MIN", "60"))
RATE_SESSION_PER_MIN = int(_env("RATE_SESSION_PER_MIN", "20"))

# Data retention: scripts/purge.py deletes sessions older than this many days
RETENTION_DAYS = int(_env("RETENTION_DAYS", "30"))

CONSENT_GREETING = (
    f"Hello, this is the AI assistant for {BUSINESS_NAME}. "
    "This call is handled by an AI and your details are saved to arrange follow-up; "
    "by continuing you agree to this. How can I help you today?"
)

_PHONE = re.compile(r"\+?\d[\d\s-]{6,}\d")


class PIIFilter(logging.Filter):
    """Masks phone-number-like strings in every log line (names are never logged)."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = _PHONE.sub(lambda m: "***" + re.sub(r"\D", "", m.group())[-2:], record.getMessage())
        record.msg, record.args = msg, ()
        return True


def setup_logging() -> None:
    """Configure root logging once, with PII masking."""
    handler = logging.StreamHandler()
    handler.addFilter(PIIFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    if not any(isinstance(h.filters[0] if h.filters else None, PIIFilter) for h in root.handlers):
        root.handlers = [handler]
    root.setLevel(logging.INFO)
