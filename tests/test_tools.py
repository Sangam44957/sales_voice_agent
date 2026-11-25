import json
import sqlite3

import pytest

from app import config, db, rag, tools
from app.tools import compute_score, run_tool


def book(session, slot=1, name="Asha", phone="9876543210"):
    return run_tool(session, "book_appointment", {"slot_id": slot, "name": name, "phone": phone})


def test_double_booking_blocked(fresh_db):
    assert book("s1")["booked"] is True
    r = book("s2", name="Ravi")
    assert r["booked"] is False


def test_unique_constraint_is_the_safety_net(fresh_db):
    book("s1")
    with db.connect() as c:
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO appointments (slot_id, lead_id) VALUES (1, 1)")


def test_lead_upsert_keeps_old_fields(fresh_db):
    run_tool("s1", "save_lead", {"name": "Asha", "interest": "data science"})
    run_tool("s1", "save_lead", {"budget": "60000"})
    with db.connect() as c:
        rows = c.execute("SELECT * FROM leads").fetchall()
    assert len(rows) == 1 and rows[0]["name"] == "Asha" and rows[0]["budget"] == "60000"
    assert rows[0]["crm_id"].startswith("local-")


def test_score_rubric():
    full = {"interest": "ds", "budget": "50k", "timeline": "next month", "phone": "9876543210"}
    assert compute_score(full, booked=True, sentiment="positive", asked_pricing=True) == 100
    assert compute_score(full, booked=False, sentiment="negative", asked_pricing=False) == 50
    assert compute_score({}, False, "negative", False) == 0
    assert compute_score({"timeline": "in 8 months"}, False, "neutral", False) == 0


def test_score_updates_after_booking(fresh_db):
    run_tool("s1", "save_lead", {"interest": "ds", "phone": "9876543210"})
    before = run_tool("s1", "save_lead", {})["score"]
    assert book("s1")["score"] == before + 20
    with db.connect() as c:
        assert c.execute("SELECT stage FROM leads").fetchone()["stage"] == "booked"


@pytest.mark.parametrize("name,args", [
    ("book_appointment", {"slot_id": "1; DROP TABLE slots", "name": "x", "phone": "9876543210"}),
    ("book_appointment", {"slot_id": 1, "name": "x", "phone": "abc"}),
    ("book_appointment", {"slot_id": 1, "name": "x", "phone": "9876543210", "session_id": "s2"}),
    ("save_lead", {"phone": "12"}),
    ("check_slots", {"date": "tomorrow'; --"}),
    ("search_knowledge", {"query": ""}),
    ("delete_everything", {}),
])
def test_tool_argument_validation(fresh_db, name, args):
    assert "error" in run_tool("s1", name, json.dumps(args))
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) n FROM slots").fetchone()["n"] == 3  # nothing was damaged


def test_malformed_json_args(fresh_db):
    assert "error" in run_tool("s1", "save_lead", "{not json")


def test_tools_ignore_llm_supplied_session(fresh_db):
    """A tool can only act on the session passed by the server, never one named by the model."""
    run_tool("s1", "save_lead", {"name": "A"})
    run_tool("s1", "save_lead", {"name": "B", "session_id": "s2"})  # rejected (extra field)
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) n FROM leads WHERE session_id='s2'").fetchone()["n"] == 0


def test_check_slots_hides_booked(fresh_db):
    book("s1")
    ids = [s["id"] for s in run_tool("s1", "check_slots", {})["slots"]]
    assert 1 not in ids and ids == [2, 3]


# ---------- RAG (downloads the embedding model on first run) ----------
@pytest.fixture(scope="module")
def indexed():
    assert rag.ingest() > 0


def test_rag_english_fee(indexed):
    hits = rag.search("How much is the data science course fee?")
    assert hits and "60,000" in " ".join(h["text"] for h in hits)


def test_rag_hindi_fee(indexed):
    hits = rag.search("डेटा साइंस कोर्स की फीस कितनी है?")
    assert hits and "60,000" in " ".join(h["text"] for h in hits)


def test_rag_miss(indexed):
    assert rag.search("What is the capital of Australia?") == []
    assert run_tool("s1", "search_knowledge", {"query": "best pizza topping"})["found"] is False


def test_chunking_overlap():
    text = "\n\n".join(f"paragraph {i} " + "x" * 300 for i in range(8))
    chunks = rag.chunk_text(text, size=700, overlap=100)
    assert len(chunks) > 1 and chunks[1].startswith(chunks[0][-100:])


def test_purge_removes_old_sessions_and_frees_slot(fresh_db):
    import sys
    sys.path.insert(0, str(config.ROOT / "scripts"))
    import purge
    book("s1")
    assert purge.purge(days=-1) == 2  # cutoff in the future -> everything is "old"
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) n FROM leads").fetchone()["n"] == 0
        assert c.execute("SELECT is_booked FROM slots WHERE id=1").fetchone()["is_booked"] == 0
