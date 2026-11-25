"""Agent tools: Pydantic-validated arguments, scoped to the current session, plus the scoring rubric."""
import json
import logging
import re
import sqlite3
import unicodedata
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app import config, db, rag
from app.crm import crm

log = logging.getLogger(__name__)
PHONE_RE = re.compile(r"^\+?\d{7,15}$")
SOON_RE = re.compile(r"asap|immediate|right away|\bnow\b|today|tomorrow|(this|next) (week|month)|\b(1|one) month|few (days|weeks)|\b([1-9]|[12]\d|30) days|\b[1-4] weeks", re.I)


class _Args(BaseModel):
    # extra=forbid: an LLM (or injected caller) cannot smuggle in session_id or other fields
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchArgs(_Args):
    query: str = Field(min_length=2, max_length=300)


class SlotsArgs(_Args):
    date: str | None = Field(default=None, description="YYYY-MM-DD, optional")

    @field_validator("date")
    @classmethod
    def _iso(cls, v: str | None) -> str | None:
        if v:
            datetime.strptime(v, "%Y-%m-%d")
        return v


class BookArgs(_Args):
    slot_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=80)
    phone: str

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = "".join(str(unicodedata.digit(c)) if c.isdigit() else c for c in v)  # Devanagari/Gurmukhi digits -> 0-9
        v = re.sub(r"[\s-]", "", v)
        if not PHONE_RE.match(v):
            raise ValueError("phone must be 7-15 digits")
        return v


class LeadArgs(_Args):
    name: str | None = Field(default=None, max_length=80)
    phone: str | None = None
    interest: str | None = Field(default=None, max_length=200)
    budget: str | None = Field(default=None, max_length=100)
    timeline: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return BookArgs._phone.__func__(BookArgs, v)  # reuse the same rule


# ---------- scoring (architecture 8.3): deterministic, never from the LLM ----------
def compute_score(lead: dict, booked: bool, sentiment: str, asked_pricing: bool) -> int:
    """Explainable rubric: +20 interest, +20 budget, +20 timeline<=1 month, +10 phone, +10 pricing, +20 booked, -20 negative."""
    s = 0
    s += 20 if lead.get("interest") else 0
    s += 20 if lead.get("budget") else 0
    s += 20 if lead.get("timeline") and SOON_RE.search(lead["timeline"]) else 0
    s += 10 if lead.get("phone") else 0
    s += 10 if asked_pricing else 0
    s += 20 if booked else 0
    s -= 20 if sentiment == "negative" else 0
    return max(0, min(100, s))


def refresh_score(session_id: str) -> int:
    """Recompute and store the score/stage for the session's lead; 0 if no lead yet."""
    with db.connect() as c:
        lead = c.execute("SELECT * FROM leads WHERE session_id=?", (session_id,)).fetchone()
        if not lead:
            return 0
        booked = c.execute("SELECT 1 FROM appointments WHERE lead_id=?", (lead["id"],)).fetchone() is not None
        last = c.execute("SELECT sentiment FROM messages WHERE session_id=? AND role='assistant' AND sentiment<>'' ORDER BY id DESC LIMIT 1", (session_id,)).fetchone()
        asked = c.execute("SELECT 1 FROM messages WHERE session_id=? AND intent IN ('pricing_question','ready_to_book','enrolment_question') LIMIT 1", (session_id,)).fetchone()
        score = compute_score(dict(lead), booked, last["sentiment"] if last else "neutral", asked is not None)
        stage = "booked" if booked else "qualified" if score >= 50 else "new"
        c.execute("UPDATE leads SET score=?, stage=?, updated_at=? WHERE id=?", (score, stage, db.now(), lead["id"]))
        return score


def _upsert_lead(c: sqlite3.Connection, session_id: str, fields: dict) -> int:
    """Insert or update the session's single lead; None fields never overwrite existing data."""
    row = c.execute("SELECT id FROM leads WHERE session_id=?", (session_id,)).fetchone()
    fields = {k: v for k, v in fields.items() if v is not None}
    if row is None:
        c.execute("INSERT INTO leads (session_id, updated_at) VALUES (?,?)", (session_id, db.now()))
        row = c.execute("SELECT id FROM leads WHERE session_id=?", (session_id,)).fetchone()
    for k, v in fields.items():  # keys come from a fixed Pydantic model, values are bound parameters
        c.execute(f"UPDATE leads SET {k}=?, updated_at=? WHERE id=?", (v, db.now(), row["id"]))
    return row["id"]


# ---------- tools ----------
def search_knowledge(session_id: str, a: SearchArgs) -> dict:
    hits = rag.search(a.query)
    if not hits:
        return {"found": False, "message": "No relevant information in the knowledge base. Offer a human callback."}
    return {"found": True, "results": [{"source": h["source"], "text": h["text"]} for h in hits]}


def check_slots(session_id: str, a: SlotsArgs) -> dict:
    sql, params = "SELECT id, start_time FROM slots WHERE is_booked=0 AND start_time>?", [datetime.now().strftime("%Y-%m-%d %H:%M")]
    if a.date:
        sql, params = sql + " AND start_time LIKE ?", params + [a.date + "%"]
    with db.connect() as c:
        rows = c.execute(sql + " ORDER BY start_time LIMIT 5", params).fetchall()
    return {"slots": [dict(r) for r in rows]} if rows else {"slots": [], "message": "No free slots."}


def save_lead(session_id: str, a: LeadArgs) -> dict:
    with db.connect() as c:
        lead_id = _upsert_lead(c, session_id, a.model_dump())
    score = refresh_score(session_id)
    with db.connect() as c:
        lead = dict(c.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
        c.execute("UPDATE leads SET crm_id=? WHERE id=?", (crm.upsert_lead(lead), lead_id))
    log.info("lead saved session=%s score=%s", session_id[:8], score)
    return {"saved": True, "score": score}


def fill_missing_lead(session_id: str, a: LeadArgs) -> None:
    """Backfill only EMPTY lead fields (used at end of call from the transcript); never overwrites what the agent saved."""
    with db.connect() as c:
        row = c.execute("SELECT * FROM leads WHERE session_id=?", (session_id,)).fetchone()
        have = dict(row) if row else {}
        gaps = {k: v for k, v in a.model_dump().items() if v and not have.get(k)}
        if gaps:
            _upsert_lead(c, session_id, gaps)
    refresh_score(session_id)


def book_appointment(session_id: str, a: BookArgs) -> dict:
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")  # take the write lock so check+insert is atomic
        try:
            lead_id = _upsert_lead(c, session_id, {"name": a.name, "phone": a.phone})
            if c.execute("SELECT 1 FROM appointments WHERE lead_id=?", (lead_id,)).fetchone():
                c.execute("ROLLBACK")
                return {"booked": False, "error": "This caller already has an appointment."}
            slot = c.execute("SELECT id, start_time FROM slots WHERE id=? AND is_booked=0", (a.slot_id,)).fetchone()
            if slot is None:
                c.execute("ROLLBACK")
                return {"booked": False, "error": "Slot not available. Call check_slots again."}
            # UNIQUE(slot_id) is the real safety net even if the check above were bypassed
            c.execute("INSERT INTO appointments (slot_id, lead_id, created_at) VALUES (?,?,?)", (a.slot_id, lead_id, db.now()))
            c.execute("UPDATE slots SET is_booked=1 WHERE id=?", (a.slot_id,))
            c.execute("COMMIT")
        except sqlite3.IntegrityError:
            c.execute("ROLLBACK")
            return {"booked": False, "error": "Slot just taken. Call check_slots again."}
    score = refresh_score(session_id)
    log.info("appointment booked session=%s slot=%s", session_id[:8], a.slot_id)
    return {"booked": True, "time": slot["start_time"], "score": score}


REGISTRY = {
    "search_knowledge": (SearchArgs, search_knowledge, "Search the knowledge base for courses, fees, admissions and policies. Use before stating any fact."),
    "check_slots": (SlotsArgs, check_slots, "List free counselling appointment slots. Always call before proposing times."),
    "save_lead": (LeadArgs, save_lead, "Save the caller's details. Call it every time the caller states ANY of name, course interest, budget, timeline or phone; include every field known so far. Never invent values."),
    "book_appointment": (BookArgs, book_appointment, "Book a slot AFTER the caller has confirmed the time, with their name and phone."),
}


def tool_schemas() -> list[dict]:
    """OpenAI/Groq-style tool definitions generated from the Pydantic models."""
    out = []
    for name, (model, _fn, desc) in REGISTRY.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
        out.append({"type": "function", "function": {"name": name, "description": desc, "parameters": schema}})
    return out


def run_tool(session_id: str, name: str, raw_args: str | dict | None) -> dict:
    """Validate then execute a tool call; LLM output is untrusted, so every failure becomes an error dict."""
    if name not in REGISTRY:
        return {"error": f"Unknown tool '{name}'."}
    model, fn, _ = REGISTRY[name]
    try:
        data = json.loads(raw_args) if isinstance(raw_args, str) and raw_args.strip() else (raw_args or {})
        args = model.model_validate(data)
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as e:
        log.warning("tool %s rejected: %s", name, type(e).__name__)
        return {"error": "Invalid arguments. Fix them and retry.", "detail": str(e)[:200]}
    try:
        return fn(session_id, args)
    except Exception:  # never leak a stack trace to the model or client
        log.exception("tool %s failed", name)
        return {"error": "Tool failed internally."}
