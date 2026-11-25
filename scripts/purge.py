"""Delete sessions (and their messages, leads, appointments, summaries) older than RETENTION_DAYS."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, db  # noqa: E402


def purge(days: int | None = None) -> int:
    """Remove old calls; frees booked slots. Returns number of sessions deleted."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.RETENTION_DAYS if days is None else days)).isoformat(timespec="seconds")
    with db.connect() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM sessions WHERE started_at < ?", (cutoff,))]
        for sid in ids:
            c.execute("UPDATE slots SET is_booked=0 WHERE id IN (SELECT a.slot_id FROM appointments a JOIN leads l ON l.id=a.lead_id WHERE l.session_id=?)", (sid,))
            c.execute("DELETE FROM appointments WHERE lead_id IN (SELECT id FROM leads WHERE session_id=?)", (sid,))
            for t in ("call_summaries", "messages", "leads"):
                c.execute(f"DELETE FROM {t} WHERE session_id=?", (sid,))  # t is from a fixed tuple, not user input
            c.execute("DELETE FROM sessions WHERE id=?", (sid,))
    return len(ids)


if __name__ == "__main__":
    print(f"purged {purge()} sessions older than {config.RETENTION_DAYS} days")
