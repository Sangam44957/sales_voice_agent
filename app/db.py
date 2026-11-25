"""SQLite schema and connection helper (parameterised SQL only)."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT, language TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, session_id TEXT REFERENCES sessions(id), role TEXT, content TEXT,
  language TEXT, sentiment TEXT, intent TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY, session_id TEXT UNIQUE REFERENCES sessions(id), name TEXT, phone TEXT,
  interest TEXT, budget TEXT, timeline TEXT, score INTEGER DEFAULT 0, stage TEXT DEFAULT 'new',
  notes TEXT, crm_id TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS slots (
  id INTEGER PRIMARY KEY, start_time TEXT UNIQUE, is_booked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS appointments (
  id INTEGER PRIMARY KEY, slot_id INTEGER UNIQUE REFERENCES slots(id),
  lead_id INTEGER REFERENCES leads(id), created_at TEXT);
CREATE TABLE IF NOT EXISTS call_summaries (
  session_id TEXT PRIMARY KEY REFERENCES sessions(id), summary TEXT, insights_json TEXT,
  overall_sentiment TEXT, final_score INTEGER);
"""


def now() -> str:
    """UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection; commit on success, roll back on error, always close."""
    # isolation_level=None -> we control transactions explicitly (BEGIN IMMEDIATE in bookings)
    conn = sqlite3.connect(config.DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if missing."""
    with connect() as c:
        c.executescript(SCHEMA)


def create_session(session_id: str, language: str = "en") -> None:
    """Insert a new active session row."""
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO sessions VALUES (?,?,?,?,?)", (session_id, now(), None, language, "active"))


def add_message(session_id: str, role: str, content: str, language: str = "", sentiment: str = "", intent: str = "") -> None:
    """Append a message row for audit and the dashboard."""
    with connect() as c:
        c.execute(
            "INSERT INTO messages (session_id, role, content, language, sentiment, intent, created_at) VALUES (?,?,?,?,?,?,?)",
            (session_id, role, content, language, sentiment, intent, now()),
        )
