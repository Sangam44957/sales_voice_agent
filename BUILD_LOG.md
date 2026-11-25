# BUILD_LOG

Last updated after Stage 4. **No `GROQ_API_KEY` was available during the build**, so everything that calls Groq (LLM, STT) was verified only with mocks. Run `scripts/smoke_test.py` and one live conversation once the key is in `.env` (see section 5).

## 1. Status checklist

| Feature | Status | Verified by |
|---|---|---|
| Text agent loop with tool calling | 🟡 code complete; live Groq call not run | `tests/test_agent.py::test_end_to_end_booking_with_mocked_llm`, `test_tool_loop_is_capped` |
| STT (Groq Whisper, language normalised) | 🟡 code complete; live call not run | `tests/test_api.py::test_voice_fallback_and_language_normalisation`, `test_stt_failure_asks_to_repeat` (mocked) |
| TTS (edge-tts, voice map from live list) | ✅ | live run: `scripts/smoke_test.py` voices check and a real mp3 returned by `POST /api/session` |
| Contextual memory (history + rolling summary + lead context) | ✅ (mocked LLM) | `test_rolling_summary`; lead facts re-injected each turn by `_lead_context` |
| Multilingual | 🟡 Hindi/English RAG + voices verified; Punjabi has no edge-tts voice (falls back to Hindi voice); STT language not tested live | `test_rag_hindi_fee`, smoke test voices (`pa_native: False`) |
| Lead qualification + deterministic score | ✅ | `test_score_rubric`, `test_score_updates_after_booking`, `test_lead_upsert_keeps_old_fields` |
| Sentiment analysis (per-turn, from LLM JSON) | 🟡 parsing verified; real model output not seen | `test_parse_output_variants`, `test_json_parse_fallback` |
| RAG (Chroma + fastembed, threshold) | ✅ | `test_rag_english_fee`, `test_rag_hindi_fee`, `test_rag_miss`, `test_chunking_overlap` |
| Appointment booking (no double booking) | ✅ | `test_double_booking_blocked`, `test_unique_constraint_is_the_safety_net` |
| CRM integration | 🟡 adapter + local table + optional webhook; webhook never exercised against a real CRM | `test_lead_upsert_keeps_old_fields` (checks `crm_id`) |
| Call summary and insights | 🟡 stored and shown; LLM-generated summary only mocked/fallback-tested | `test_end_to_end_booking_with_mocked_llm`, `test_full_flow_text` |
| Web UI (push-to-talk + text box) and dashboard | 🟡 served and API-tested; mic recording **not tested in a browser** | `curl` of `/web/dashboard.html` = 200; `tests/test_api.py` |
| Scalability design | 📐 documented in README, not built | README "Scalability" |
| Docker | ⬜ not done (optional) | none |

## 2. Security and quality controls

| Control | Where | How | Verified by |
|---|---|---|---|
| Secrets from env only | `config.py`, `.gitignore` | `.env` loaded by python-dotenv, git-ignored; key never logged/returned | code review; `git check-ignore .env` |
| Parameterised SQL | `db.py`, `tools.py`, `main.py` | all values bound with `?`; the only f-strings interpolate fixed column/table names from code | `test_tool_argument_validation` (SQL-ish inputs rejected, tables intact) |
| Input + tool-arg validation | `tools.py` Pydantic models (`extra=forbid`) | bad types/phones/dates/extra fields rejected before running | `test_tool_argument_validation`, `test_malformed_json_args` |
| Audio limits | `security.check_audio` | content-type allow-list, 5MB max, min size | `test_audio_limits` |
| Rate limiting (per IP, per session) | `security.RateLimiter` | sliding window, in-memory | `test_rate_limit_and_headers` |
| Max turns / duration / tool rounds | `agent.run_turn`, `config.py` | limits return a goodbye; 4 tool rounds then a forced text answer | `test_turn_limit`, `test_tool_loop_is_capped` |
| Tools scoped to session | `tools.run_tool` | session id is passed by the server, never by the model | `test_tools_ignore_llm_supplied_session` |
| Booking race | `tools.book_appointment` | `BEGIN IMMEDIATE` + `UNIQUE(slot_id)` | `test_double_booking_blocked`, `test_unique_constraint_is_the_safety_net` |
| CORS + security headers | `main.py`, `security.SecurityHeaders` | origin allow-list from config; nosniff, frame deny, CSP, etc. | `test_rate_limit_and_headers` (headers) |
| No stack traces to clients | `main.unhandled`, `tools.run_tool` | generic error body; details only in logs | `test_unknown_session_and_errors_hide_traces`, `test_llm_failure_gives_graceful_reply` |
| PII masking in logs | `config.PIIFilter` | phone-like numbers masked; names never logged | code review only (no dedicated test) |
| Consent notice | `config.CONSENT_GREETING` | spoken/shown at call start | seen in `POST /api/session` output |
| Retention | `config.RETENTION_DAYS`, `scripts/purge.py` | deletes old sessions and related rows, frees slots | `test_purge_removes_old_sessions_and_frees_slot` |
| Prompt-injection stance | `agent.SYSTEM_PROMPT` + validation | prompt forbids rule changes/leaks; injected tool abuse is rejected | `test_injection_stance` (mocked; **the model's actual refusal behaviour is untested**) |
| XSS in UI | `web/*.html` | all text inserted via `textContent` | code review |

## 3. What was built per module

- `config.py`: env settings, thresholds, consent text, PII log filter. Change knobs here.
- `db.py`: schema (architecture §6 plus `messages.intent`), connection helper, message writer.
- `tools.py`: four tools with Pydantic args, scoring rubric, `refresh_score`, `run_tool` dispatcher and JSON schemas.
- `rag.py`: paragraph chunking with overlap, fastembed embeddings, Chroma cosine search with a threshold.
- `crm.py`: `CRMAdapter` protocol and `LocalCRM` (optional webhook).
- `agent.py`: prompt, tool loop (4 rounds), defensive JSON parsing, rolling summary, end-of-call summary.
- `stt.py` / `tts.py`: Groq Whisper wrapper and edge-tts wrapper, each with timeout, one retry and typed errors.
- `security.py`: rate limiter, upload checks, headers. `main.py`: routes and Pydantic response models.
- `web/index.html`, `web/dashboard.html`: call UI and dashboard. `scripts/`: seed, ingest, smoke test, CLI chat, purge.

## 4. Deviations and fixes

- `CLAUDE.md` says stop after each stage; the master prompt overrides it, so all stages ran in one go.
- Scoring lives in `tools.py` (architecture §20 says `agent.py`) because `save_lead` and `book_appointment` call it.
- Added `messages.intent` so "asked about pricing/enrolment" can feed the score; added `app/security.py` (not in the §12 layout) to keep `main.py` small.
- Chroma rejected the collection name `kb` (min 3 chars); renamed to `knowledge_base`.
- Port 8000 was already in use on this machine; tested on 8010.
- Default LLM `llama-3.3-70b-versatile` is an assumption: not checked against Groq's live model list (needs the key). `smoke_test.py` prints whether it is listed.
- Docker skipped; the master prompt allows that if everything else comes first.

## 5. Known limitations (honest)

- **Live Groq paths untested** (LLM tool calling, Whisper, real JSON output). First live run may need prompt/schema tweaks.
- Mic recording and playback not tested in a real browser.
- Punjabi: no edge-tts Punjabi voice (Hindi voice used); Whisper Punjabi accuracy is weaker; Hinglish may confuse detection (use the language pin).
- Turn-based, not streaming. In-memory sessions and rate limits (lost on restart, single process). SQLite and local Chroma. CRM webhook is a stub.
- Dashboard and `/api/leads` have no authentication (PII exposed); fine for a local demo only.
- Timeline scoring uses a keyword regex, not real date understanding. Budget "matches offering" is simplified to "budget given".

## 6. Designed, not implemented

Streaming (WebRTC/WebSocket, VAD, barge-in); telephony (Twilio/Exotel into the same agent core); long-term customer memory in Postgres keyed by phone; real CRM/calendar adapters (HubSpot, Google Calendar); async queue for summaries and CRM sync; Redis session store; hybrid BM25 + reranker RAG; multi-tenant KBs; auth/RBAC; scale-out for 1,00,000 users (README).

## 7. Run instructions

```bash
cd ~/sales-voice-agent
echo 'GROQ_API_KEY=your_key' > .env
.venv/bin/python scripts/seed_slots.py && .venv/bin/python scripts/ingest.py
.venv/bin/python scripts/smoke_test.py      # first check with the key
.venv/bin/python -m pytest -q
.venv/bin/uvicorn app.main:app --port 8010  # http://localhost:8010 (Chrome); dashboard at /web/dashboard.html
```
