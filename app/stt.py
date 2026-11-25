"""Speech-to-text via Groq Whisper; returns text plus a normalised 2-letter language code."""
import logging
from dataclasses import dataclass

from app import config

log = logging.getLogger(__name__)
# Whisper's verbose_json returns language NAMES ("hindi"); we normalise to ISO codes in one place.
LANG_MAP = {"english": "en", "hindi": "hi", "punjabi": "pa", "panjabi": "pa", "urdu": "ur"}


@dataclass
class Transcript:
    text: str
    language: str


class STTError(Exception):
    """STT provider failed after retry."""


def normalise_language(raw: str | None, default: str = "en") -> str:
    """'hindi' | 'hi' | 'Hindi' -> 'hi'."""
    raw = (raw or "").strip().lower()
    return LANG_MAP.get(raw, raw[:2] if len(raw) in (2, 3) else default)


def transcribe(audio: bytes, filename: str = "audio.webm", language: str | None = None) -> Transcript:
    """Send audio to Whisper. `language` pins the language (skips auto-detect) when the user chose one."""
    from groq import Groq

    if not config.GROQ_API_KEY:
        raise STTError("GROQ_API_KEY missing")
    client = Groq(api_key=config.GROQ_API_KEY, timeout=config.LLM_TIMEOUT)
    kwargs = {"file": (filename, audio), "model": config.STT_MODEL, "response_format": "verbose_json"}
    if language:
        kwargs["language"] = language
    for attempt in (1, 2):
        try:
            r = client.audio.transcriptions.create(**kwargs)
            return Transcript(text=(r.text or "").strip(), language=normalise_language(getattr(r, "language", None), language or "en"))
        except Exception as e:
            log.warning("STT attempt %s failed: %s", attempt, type(e).__name__)
    raise STTError("STT failed after retry")
