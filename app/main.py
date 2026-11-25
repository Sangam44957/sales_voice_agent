"""FastAPI routes (architecture section 7). Never returns a stack trace to the client."""
import base64
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import agent, config, db, security, stt, tts

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.setup_logging()
    db.init_db()
    yield


app = FastAPI(title="AI Sales Voice Agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])
app.add_middleware(security.SecurityHeaders)


class StartIn(BaseModel):
    language: str | None = None


class SpokenOut(BaseModel):
    reply: str
    language: str
    audio_b64: str | None = None  # None -> UI falls back to browser speech synthesis
    audio_mime: str = "audio/mpeg"


class SessionOut(SpokenOut):
    session_id: str


class TurnOut(SpokenOut):
    transcript: str
    sentiment: str
    intent: str
    score: int
    sources: list[str]
    tools_used: list[str]
    limit_reached: bool = False


class EndOut(BaseModel):
    session_id: str
    summary: str | None
    insights: dict
    overall_sentiment: str
    final_score: int


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")  # full detail goes to the log only
    return JSONResponse({"error": "Something went wrong. Please try again."}, status_code=500)


async def _speak(text: str, lang: str) -> str | None:
    try:
        return base64.b64encode(await tts.synthesize(text, lang)).decode()
    except tts.TTSError:
        return None


def _session(session_id: str) -> agent.Session:
    s = agent.SESSIONS.get(session_id)
    if s is None:
        raise HTTPException(404, "Unknown or ended session.")
    return s


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/session", response_model=SessionOut)
async def start(request: Request, body: StartIn | None = None) -> SessionOut:
    security.ip_limiter.check(request.client.host)
    lang = body.language if body and body.language in agent.LANGS else "en"
    s = agent.start_session(lang)
    return SessionOut(session_id=s.id, reply=config.CONSENT_GREETING, language="en", audio_b64=await _speak(config.CONSENT_GREETING, "en"))


@app.post("/api/turn", response_model=TurnOut)
async def turn(request: Request, session_id: str = Form(...), language: str | None = Form(None),
               text: str | None = Form(None, max_length=1000), audio: UploadFile | None = File(None)) -> TurnOut:
    security.ip_limiter.check(request.client.host)
    security.session_limiter.check(session_id)
    s = _session(session_id)
    pin = language if language in agent.LANGS else None  # only accept known language codes
    heard = (text or "").strip()
    if not heard and audio is not None:
        data = await audio.read(config.MAX_AUDIO_BYTES + 1)
        security.check_audio(audio.content_type, len(data))
        try:
            t = await run_in_threadpool(stt.transcribe, data, audio.filename or "audio.webm", pin)
            heard, s.language = t.text, (pin or t.language)
        except stt.STTError:
            heard = ""
    if not heard:  # empty/failed STT: ask to repeat, don't call the LLM
        return TurnOut(reply=agent.REPEAT_REPLY, language=s.language, audio_b64=await _speak(agent.REPEAT_REPLY, s.language),
                       transcript="", sentiment="neutral", intent="other", score=0, sources=[], tools_used=[])
    r = await run_in_threadpool(agent.run_turn, session_id, heard, pin)
    return TurnOut(**{k: r[k] for k in ("reply", "language", "sentiment", "intent", "score", "sources", "tools_used", "limit_reached")},
                   transcript=heard, audio_b64=await _speak(r["reply"], r["language"]))


@app.post("/api/end_call", response_model=EndOut)
async def end_call(request: Request, session_id: str = Form(...)) -> EndOut:
    security.ip_limiter.check(request.client.host)
    _session(session_id)
    return EndOut(**await run_in_threadpool(agent.summarize, session_id))


def _rows(sql: str) -> list[dict]:
    with db.connect() as c:
        return [dict(r) for r in c.execute(sql).fetchall()]


@app.get("/api/leads")
def leads() -> list[dict]:
    return _rows("SELECT l.id, l.name, l.phone, l.interest, l.budget, l.timeline, l.score, l.stage, l.crm_id, l.updated_at, s.start_time AS appointment "
                 "FROM leads l LEFT JOIN appointments a ON a.lead_id=l.id LEFT JOIN slots s ON s.id=a.slot_id ORDER BY l.updated_at DESC")


@app.get("/api/calls")
def calls() -> list[dict]:
    return _rows("SELECT se.id, se.started_at, se.language, se.status, l.name, c.summary, c.insights_json, c.overall_sentiment, c.final_score "
                 "FROM sessions se LEFT JOIN leads l ON l.session_id=se.id LEFT JOIN call_summaries c ON c.session_id=se.id ORDER BY se.started_at DESC LIMIT 100")


@app.get("/api/slots")
def slots() -> list[dict]:
    return _rows("SELECT id, start_time, is_booked FROM slots ORDER BY start_time")


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse("/web/index.html")


app.mount("/web", StaticFiles(directory=config.ROOT / "web"), name="web")
