# Project: AI Sales Voice Agent (interview prototype, one developer, ~10 hours total)

Source of truth: architecture.md. Read ONLY sections 4-10 and 12. Ignore 13-21 (interview talking points, not code).

## Scope
- Build only what is marked ✅ or 🟡. Never build 📐 items.
- Turn-based push-to-talk (HTTP), not streaming. FastAPI + sqlite3 + Chroma.
- STT: Groq Whisper (whisper-large-v3-turbo, response_format=verbose_json).
- LLM: Groq chat with tool calling. Look up a CURRENT tool-calling-capable model ID
  from Groq's models list / docs instead of assuming one; read the key from .env (GROQ_API_KEY).
- Do NOT combine response_format/structured-output with tool calling. Ask for JSON in the prompt,
  parse defensively with a fallback (architecture.md 4.4).
- Embeddings: fastembed + paraphrase-multilingual-MiniLM-L12-v2. Do NOT install torch or sentence-transformers.
- TTS: edge-tts. Build the language->voice map from `edge-tts --list-voices`; fallback Hindi, then English.
- Lead score is computed in code (architecture.md 8.3), never by the LLM.

## Code rules
- Small files (<150 lines), plain readable Python, type hints, comment the WHY of non-obvious lines.
- No extra abstractions, frameworks, or build steps. Plain HTML/JS for the UI.
- The developer must explain and modify every line in a live interview. If something is clever, simplify it.

## Working rules (token budget is limited)
- Work one stage at a time, then STOP and wait.
- Keep replies under 10 lines. Do not paste code back into chat. Do not re-read files you just wrote.
- Run the code to prove it works, show only the key output.
- Ask me before guessing on anything ambiguous.
