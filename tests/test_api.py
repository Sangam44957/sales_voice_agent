import io

import pytest
from fastapi.testclient import TestClient

from app import agent, main, security, tts


@pytest.fixture()
def client(fresh_db, monkeypatch):
    agent.SESSIONS.clear()
    security.ip_limiter.hits.clear()
    security.session_limiter.hits.clear()
    async def no_tts(text, lang):
        raise tts.TTSError("offline in tests")
    monkeypatch.setattr(tts, "synthesize", no_tts)
    monkeypatch.setattr(agent, "llm_call", lambda m, t=None: {"content": '{"reply":"Hi there","language":"en","sentiment":"positive","intent":"smalltalk"}', "tool_calls": []})
    with TestClient(main.app) as c:
        yield c


def test_full_flow_text(client):
    sid = client.post("/api/session").json()["session_id"]
    r = client.post("/api/turn", data={"session_id": sid, "text": "hello"}).json()
    assert r["reply"] == "Hi there" and r["audio_b64"] is None and r["sentiment"] == "positive"
    assert client.post("/api/end_call", data={"session_id": sid}).json()["session_id"] == sid
    assert {c["id"]: c["status"] for c in client.get("/api/calls").json()}[sid] == "ended"
    assert client.get("/health").json() == {"status": "ok"}


def test_unknown_session_and_errors_hide_traces(client):
    r = client.post("/api/turn", data={"session_id": "nope", "text": "x"})
    assert r.status_code == 404 and "Traceback" not in r.text


def test_audio_limits(client):
    sid = client.post("/api/session").json()["session_id"]
    bad_type = client.post("/api/turn", data={"session_id": sid}, files={"audio": ("a.exe", io.BytesIO(b"x" * 500), "application/x-msdownload")})
    assert bad_type.status_code == 415
    big = client.post("/api/turn", data={"session_id": sid}, files={"audio": ("a.webm", io.BytesIO(b"x" * (6 * 1024 * 1024)), "audio/webm")})
    assert big.status_code == 413


def test_rate_limit_and_headers(client):
    sid = client.post("/api/session").json()["session_id"]
    codes = [client.post("/api/turn", data={"session_id": sid, "text": "hi"}).status_code for _ in range(25)]
    assert 429 in codes
    h = client.get("/health").headers
    assert h["x-content-type-options"] == "nosniff" and "content-security-policy" in h


def test_stt_failure_asks_to_repeat(client, monkeypatch):
    from app import stt
    def fail(*a, **k):
        raise stt.STTError("down")
    monkeypatch.setattr(stt, "transcribe", fail)
    sid = client.post("/api/session").json()["session_id"]
    r = client.post("/api/turn", data={"session_id": sid}, files={"audio": ("a.webm", io.BytesIO(b"x" * 500), "audio/webm;codecs=opus")}).json()
    assert r["reply"] == agent.REPEAT_REPLY


def test_voice_fallback_and_language_normalisation():
    from app import stt
    voices = [{"ShortName": "hi-IN-SwaraNeural", "Locale": "hi-IN", "Gender": "Female"}, {"ShortName": "en-IN-X", "Locale": "en-IN", "Gender": "Male"}]
    assert tts.pick_voice(voices, "pa") == "hi-IN-SwaraNeural"  # Punjabi missing -> Hindi
    assert tts.pick_voice(voices, "en") == "en-IN-X"
    assert [stt.normalise_language(x) for x in ("hindi", "Punjabi", "en", None)] == ["hi", "pa", "en", "en"]
