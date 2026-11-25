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


_GURMUKHI_SPECIAL = {"\u0A70": "\u0902", "\u0A72": "\u0907", "\u0A73": "\u0909", "\u0A59": "\u0916\u093C", "\u0A5A": "\u0917\u093C",
                     "\u0A5B": "\u091C\u093C", "\u0A5C": "\u0921\u093C", "\u0A5E": "\u092B\u093C", "\u0A71": ""}


def gurmukhi_to_devanagari(text: str) -> str:
    """Gurmukhi and Devanagari share the same letter layout (offset 0x100), so speech can use a Hindi voice when no Punjabi voice exists."""
    out = []
    for ch in text:
        if ch in _GURMUKHI_SPECIAL:
            out.append(_GURMUKHI_SPECIAL[ch])
        elif "\u0A01" <= ch <= "\u0A4D":
            out.append(chr(ord(ch) - 0x100))
        elif ch == "\u0A66" or "\u0A66" <= ch <= "\u0A6F":  # digits
            out.append(chr(ord(ch) - 0x100))
        else:
            out.append(ch)
    return "".join(out)


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
            spoken = gurmukhi_to_devanagari(text) if language == "pa" and not voice.startswith("pa-") else text
            async def run() -> bytes:
                data = b""
                async for chunk in edge_tts.Communicate(spoken, voice).stream():
                    if chunk["type"] == "audio":
                        data += chunk["data"]
                return data
            audio = await asyncio.wait_for(run(), timeout=15)
            if audio:
                return audio
        except Exception as e:
            log.warning("TTS attempt %s failed: %s", attempt, type(e).__name__)
    raise TTSError("TTS failed after retry")
