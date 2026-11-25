"""Create demo appointment slots for the next 3 days (idempotent)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db  # noqa: E402


def seed(days: int = 3) -> int:
    """Insert 10:00/12:00/15:00/17:00 slots for the next `days` days; returns rows added."""
    db.init_db()
    base = datetime.now().replace(minute=0, second=0, microsecond=0)
    added = 0
    with db.connect() as c:
        for d in range(1, days + 1):
            for hour in (10, 12, 15, 17):
                t = (base + timedelta(days=d)).replace(hour=hour).strftime("%Y-%m-%d %H:%M")
                added += c.execute("INSERT OR IGNORE INTO slots (start_time) VALUES (?)", (t,)).rowcount
    return added


if __name__ == "__main__":
    print(f"seeded {seed()} slots")
