"""Stage 0 smoke test: keys, Groq models/tool-calling, edge-tts voices, embeddings, optional STT."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, tts  # noqa: E402


def check(name: str, fn) -> None:
    try:
        print(f"PASS {name}: {fn()}")
    except Exception as e:
        print(f"FAIL {name}: {type(e).__name__}: {str(e)[:200]}")


def groq_models() -> str:
    from groq import Groq
    ids = sorted(m.id for m in Groq(api_key=config.GROQ_API_KEY).models.list().data)
    return f"configured LLM_MODEL={config.LLM_MODEL} listed={config.LLM_MODEL in ids}; all={ids}"


def tool_call() -> str:
    from groq import Groq
    tool = {"type": "function", "function": {"name": "ping", "description": "Call to ping", "parameters": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}}}
    m = Groq(api_key=config.GROQ_API_KEY).chat.completions.create(
        model=config.LLM_MODEL, messages=[{"role": "user", "content": "Call the ping tool with x=hi"}], tools=[tool], tool_choice="auto").choices[0].message
    return f"tool_calls={[(t.function.name, t.function.arguments) for t in (m.tool_calls or [])]}"


def voices() -> str:
    vs = asyncio.run(tts._voices())
    return {l: tts.pick_voice(vs, l) for l in ("en", "hi", "pa")} | {"pa_native": any(v["Locale"] == "pa-IN" for v in vs)}


def embeddings() -> str:
    import numpy as np
    from app import rag
    a, b = rag.embed(["What is the fee for data science?", "डेटा साइंस की फीस क्या है?"])
    return f"cosine={float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))):.3f}"


def stt_sample() -> str:
    files = sorted((Path(__file__).parent / "sample").glob("*.*")) if (Path(__file__).parent / "sample").exists() else []
    if not files:
        return "skipped (no scripts/sample file)"
    from app import stt
    t = stt.transcribe(files[0].read_bytes(), files[0].name)
    return json.dumps({"text": t.text, "lang": t.language}, ensure_ascii=False)


if __name__ == "__main__":
    print("GROQ_API_KEY:", "set" if config.GROQ_API_KEY else "MISSING")
    if config.GROQ_API_KEY:
        check("groq models", groq_models)
        check("groq tool call", tool_call)
    check("edge-tts voices", voices)
    check("embeddings", embeddings)
    if config.GROQ_API_KEY:
        check("stt sample", stt_sample)
