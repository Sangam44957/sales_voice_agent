"""Build the vector index from kb/*.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import rag  # noqa: E402

if __name__ == "__main__":
    print(f"indexed {rag.ingest()} chunks")
