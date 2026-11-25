"""Point DB and Chroma at temp dirs BEFORE app modules are imported."""
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ["CHROMA_DIR"] = os.path.join(_tmp, "chroma")
os.environ["GROQ_API_KEY"] = "test-key-not-real"
os.environ["CRM_WEBHOOK_URL"] = ""

import pytest  # noqa: E402

from app import db  # noqa: E402


@pytest.fixture()
def fresh_db():
    """Empty DB with one session 's1' and slots seeded."""
    if os.path.exists(os.environ["DB_PATH"]):
        os.remove(os.environ["DB_PATH"])
    db.init_db()
    db.create_session("s1")
    db.create_session("s2")
    with db.connect() as c:
        for i in range(1, 4):
            c.execute("INSERT INTO slots (id, start_time) VALUES (?,?)", (i, f"2099-01-0{i} 10:00"))
    return db
