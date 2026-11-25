"""Retrieval: chunking, local multilingual embeddings (fastembed) and Chroma search."""
import logging
from functools import lru_cache

import chromadb

from app import config

log = logging.getLogger(__name__)
COLLECTION = "knowledge_base"


@lru_cache(maxsize=1)
def _embedder():
    """Load the ONNX embedding model once (downloads ~220MB on first use)."""
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=config.EMBED_MODEL)


def embed(texts: list[str]) -> list[list[float]]:
    """Embed texts into vectors."""
    return [v.tolist() for v in _embedder().embed(texts)]


def _collection():
    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    # cosine space so similarity = 1 - distance
    return client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """Split on paragraphs, pack up to `size` chars, carry `overlap` chars into the next chunk."""
    size, overlap = size or config.CHUNK_CHARS, overlap if overlap is not None else config.CHUNK_OVERLAP
    chunks, cur = [], ""
    for para in (p.strip() for p in text.split("\n\n") if p.strip()):
        if cur and len(cur) + len(para) + 2 > size:
            chunks.append(cur)
            cur = cur[-overlap:] + "\n\n" + para if overlap else para  # overlap keeps context across the cut
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        chunks.append(cur)
    return chunks


def ingest(kb_dir=None) -> int:
    """Rebuild the index from kb/*.md; returns number of chunks."""
    kb_dir = kb_dir or config.KB_DIR
    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    try:
        client.delete_collection(COLLECTION)
    except Exception:  # collection did not exist yet
        pass
    col = client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    docs, metas, ids = [], [], []
    for path in sorted(kb_dir.glob("*.md")):
        for i, ch in enumerate(chunk_text(path.read_text(encoding="utf-8"))):
            docs.append(ch)
            metas.append({"source": path.name})
            ids.append(f"{path.stem}-{i}")
    if docs:
        col.add(ids=ids, documents=docs, metadatas=metas, embeddings=embed(docs))
    return len(docs)


def search(query: str, top_k: int | None = None, threshold: float | None = None) -> list[dict]:
    """Return up to top_k chunks with similarity >= threshold (empty list = nothing relevant)."""
    top_k, threshold = top_k or config.RAG_TOP_K, config.RAG_THRESHOLD if threshold is None else threshold
    col = _collection()
    if col.count() == 0:
        return []
    res = col.query(query_embeddings=embed([query]), n_results=top_k)
    out = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        sim = 1 - dist
        if sim >= threshold:
            out.append({"text": doc, "source": meta["source"], "score": round(sim, 3)})
    return out
