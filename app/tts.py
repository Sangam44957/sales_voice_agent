"""Text-to-speech via edge-tts; the voice map is built from the live voice list, never assumed."""
import asyncio
import logging

import edge_tts

log = logging.getLogger(__name__)
LOCALES = {"en": ["en-IN", "en-US"], "hi": ["hi-IN"], "pa": ["pa-IN"]}  # preference order per language
_VOICES: list[dict] | None = None


class TTSError(Exception):
    """TTS failed after retry; UI falls back to browser speech."""


def pick_voice(voices: list[dict], language: str) -> str | None:
    """Choose a voice for `language`; falls back to Hindi, then English if none exists (e.g. Punjabi)."""
    for lang in (language, "hi", "en"):
        for locale in LOCALES.get(lang, []):
            matches = [v for v in voices if v["Locale"] == locale]
            matches.sort(key=lambda v: v.get("Gender") != "Female")  # female first, stable
            if matches:
                return matches[0]["ShortName"]
    return None


async def _voices() -> list[dict]:
    global _VOICES
    if _VOICES is None:
        _VOICES = await asyncio.wait_for(edge_tts.list_voices(), timeout=10)
    return _VOICES


async def synthesize(text: str, language: str = "en") -> bytes:
    """Return mp3 bytes for `text`. Raises TTSError after one retry."""
    for attempt in (1, 2):
        try:
            voice = pick_voice(await _voices(), language)
            if not voice:
                raise TTSError("no voice available")
            async def run() -> bytes:
                data = b""
                async for chunk in edge_tts.Communicate(text, voice).stream():
                    if chunk["type"] == "audio":
                        data += chunk["data"]
                return data
            audio = await asyncio.wait_for(run(), timeout=15)
            if audio:
                return audio
        except Exception as e:
            log.warning("TTS attempt %s failed: %s", attempt, type(e).__name__)
    raise TTSError("TTS failed after retry")
