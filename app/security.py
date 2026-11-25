"""Rate limiting, upload validation and security headers (in-memory: fine for one demo process)."""
import time
from collections import defaultdict, deque

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app import config


class RateLimiter:
    """Sliding-window limiter: at most `limit` hits per key in `window` seconds."""

    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit, self.window, self.hits = limit, window, defaultdict(deque)

    def check(self, key: str) -> None:
        q, now = self.hits[key], time.monotonic()
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(429, "Too many requests, slow down.")
        q.append(now)


ip_limiter = RateLimiter(config.RATE_IP_PER_MIN)
session_limiter = RateLimiter(config.RATE_SESSION_PER_MIN)


def check_audio(content_type: str | None, size: int) -> None:
    """Reject oversize or unexpected audio uploads."""
    base = (content_type or "").split(";")[0].strip().lower()  # 'audio/webm;codecs=opus' -> 'audio/webm'
    if base not in config.ALLOWED_AUDIO_TYPES:
        raise HTTPException(415, "Unsupported audio type.")
    if size > config.MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio too large.")
    if size < 200:
        raise HTTPException(400, "Audio too short.")


class SecurityHeaders(BaseHTTPMiddleware):
    """Add defensive headers to every response."""

    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers.update({
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "microphone=(self)",
            "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; media-src 'self' data: blob:; connect-src 'self'",
        })
        return resp
