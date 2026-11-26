# MeetingOS Live — Implementation Plan

Status: **awaiting approval** · 2026-11-26. Covers the spec's IMPLEMENTATION_PLAN, TASK_DEPENDENCY_GRAPH, CLAUDE/CODEX prompts, TEST_AND_EVALUATION_PLAN, RISK_REGISTER and ACCEPTANCE_CRITERIA. Read with [AUDIT.md](AUDIT.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Decisions to approve

| # | Decision | Recommendation | Why |
|---|---|---|---|
| D1 | Scope of the first release | **Captions only (Phases 4–5).** Voice interpretation (Phase 6) starts after captions are measured on real use. | Captions alone deliver the core value. Voice adds LiveKit, TTS, echo control and the hardest sync problems. |
| D2 | Streaming ASR vendor | **Google Cloud Speech v2, Chirp 3** (auto LID; kk, ky, tg). Azure Speech is the fallback adapter if residency or a contract requires it. | Broadest verified Central-Asian coverage with one vendor. Turkmen is not covered by anyone. |
| D3 | Translator | **Google Cloud Translation** (same credential as D2, 130+ targets). The LLM translator ported from LiveTranslate, with glossary and context, follows in Phase 8. | One vendor, one key. NMT is fast enough for ≤3 s finals. The free LLM path is weak on Kazakh (roadmap v0.3). |
| D4 | Desktop app / Cicada / Zoom-Teams bots | **Keep them "Not planned"** as the roadmap says. Ship browser tab-audio capture (`getDisplayMedia`), which works with Zoom, Meet and Teams **running in a browser tab**. Never claim an official integration. | Cicada has no library product, and its drivers are GPL or proprietary. Bots and desktop builds reverse a decision you already made, for consent reasons. |
| D5 | Partials | Source-language partials shown live. **Only finals are translated.** | 5–10× lower translation cost, no flicker. Measure, then revisit. |
| D6 | Documents | Three docs (this set) instead of 17. | The other 14 would mostly repeat each other. |
| D7 | Two agents | Claude writes the frozen contracts (T1) first. Codex then takes bounded tasks in its own worktree. Claude reviews every Codex merge. No parallel edits to shared files. | Parallel work before contracts freeze is wasted. |

## 2. Phase 2 — compatibility experiments (gate before Phase 4)

| Id | Experiment | Needs | Pass |
|---|---|---|---|
| E1 | Stream 5 FLEURS clips (kk, ru, en, zh, ar) and the messy kk/ru mix through the chosen ASR with a ~60-line script in the audit folder | **Google key** (D2) | Partials arrive; final ≤1.5 s after end of speech (P50); LID correct on ≥4/5; kk/ru switch detected |
| E2 | Translate 50 sentences kk→ru/en/zh/ar/de, numbers and names included | same key | P95 ≤800 ms per sentence for all 5 targets; every number preserved |
| E3 | Browser AudioWorklet → FastAPI WebSocket → WAV, in Chrome and Safari (desktop + iPhone) | none | WAV plays back clean at 16 kHz; reconnect resumes |
| E4 | Turkmen: check whether any approved vendor streams tk | docs/key | If none: registry marks tk captions-only via translation, ASR unavailable |

E3 can run now. E1, E2 and E4 are **blocked until a Google Cloud key is in `.env`**. If the key is not available, swap D2 for whichever vendor you can get (Azure or ElevenLabs Scribe v2 Realtime). The interfaces don't change.

## 3. Tasks (dependency order)

Owner: **C** = Claude Code (main checkout or `agent/live-*` worktree), **X** = Codex (own worktree `../MeetingOS-<task>`, branch `agent/<task>`).

| Id | Task | Owner | Files (allowed scope) | Depends | Validated by |
|---|---|---|---|---|---|
| **Phase 4: end-to-end captions, one host, one viewer** |||||
| T1 | Freeze contracts: event envelope, `StreamingASR` / `Translator` protocols, `languages.json` (priority set, `verified` flags from AUDIT §4) | C | `backend/live/{__init__,events,protocols}.py`, `backend/live/languages.json`, `web/src/lib/live/events.ts` | approval | unit tests on envelope round-trip; review |
| T2 | Migrations + models: `live_sessions`, `live_join_tokens`, `segment_translations` | C | `backend/database/{models,migrations}.py`, tests | T1 | migration test from a v0.2 data dir; existing 354 tests green |
| T3 | `EventLog` (seq, ring buffer, DB fallback) + `LiveSession` + `LanguageChannel` refcount + SSE route | C | `backend/live/{session,eventlog}.py`, `backend/routes/live.py` | T1, T2 | sync tests §5.1 |
| T4 | Google Chirp 3 `StreamingASR` adapter + async `ResilientASR` port (LiveTranslate `asr/base.py`, MIT header kept) + `StubASR` replaying a recorded fixture | X | `backend/live/asr/*`, `backend/tests/live/test_asr_*.py`, `requirements.txt` (+google-cloud-speech) | T1 | contract tests against the fixture; E1 script passes with a key |
| T5 | Segmenter port (LiveTranslate `segmenter.py`) + Google Translation adapter | X | `backend/live/segmenter.py`, `backend/live/translate/*`, tests | T1 | unit tests; E2 numbers check |
| T6 | Host ingest WebSocket with explicit auth + AudioWorklet capture (mic and tab) | C | `backend/routes/live.py`, `web/src/lib/live/capture.ts`, `web/public/pcm-worklet.js` | T3, E3 | unauth WS closes 4401; E3 |
| T7 | Host page + participant page (design system, i18n en/ru/kk) | C | `web/src/routes/Live*.tsx`, `web/src/components/live/*`, locales | T3, T6 | Playwright with `StubASR` |
| T8 | Session end: write WAV to `recording_path`, status → processing, call `_try_segment` / `_try_extract` once | C | `backend/live/session.py`, `backend/meetings/ingestion.py` (call only) | T3, T4 | test: ended session produces Evidence citing live segments |
| **Phase 5: many participants** |||||
| T9 | Guest join tokens (hashed, expiring, revocable), QR dialog, guest-reachable route, rate limit | C | `backend/live/access.py`, `backend/auth.py` (allow-list `/live/*` with token), UI dialog | T2, T7 | tests §5.2 |
| T10 | Presentation view (full-screen, 1–2 languages, font size, RTL) | C | `web/src/routes/LivePresent.tsx` | T7 | Playwright screenshot, ar RTL |
| T11 | Failure-mode suite: reconnect + Last-Event-ID, late join, duplicate and out-of-order finals, stale translation revision, slow subscriber, provider drop + failover, server restart; 100-viewer SSE load test | X | `backend/tests/live/test_sync_*.py`, `scripts/live_load.py` | T3–T5 | all green; memory flat over 60 min synthetic session |
| **Checkpoint A:** Opus code review of `backend/live` + UI; E1/E2 numbers recorded; you approve Phase 6 or stop at captions |||||
| **Phase 6: voice interpretation (separate approval)** — TTS per (segment, lang) once, LiveKit self-hosted for per-language audio tracks (`gemini-live-translate` `router.py` pattern, MIT), barge-in drops queued audio of superseded revisions, original/translated volume mix. Detailed tasks are written at Checkpoint A, using measured latency. |||||
| **Phase 8: intelligence + glossary** — LLM translator port (LiveTranslate `translate.py`) with org glossaries; host corrections → `transcript.corrected`, revision++; translated summaries reuse the existing "summary in the reader's language". |||||
| **Phase 7 (desktop):** dropped per D4. **Phases 9–10:** hardening + docs, folded into Checkpoint A and the release PR. |||||

## 4. Agent briefs

Each brief starts from the frozen T1 contracts. The full text of each brief is generated at hand-off from the table row plus this template:

```
Task <Id>: <title>
Repo: ~/Desktop/Projects/MeetingOS, worktree ../MeetingOS-<id>, branch agent/<id>
Read first: docs/live-interpretation/ARCHITECTURE.md §<n>; backend/live/protocols.py; backend/live/events.py
Upstream: <file at SHA> (MIT; keep header; add THIRD_PARTY_NOTICES.md entry)
Allowed files: <from table>. Anything else: stop and ask.
Constraints: async only; no torch; every provider call via meetings/egress_log; no secrets in code;
             parameterized SQL; logging not print; functions <50 lines.
Done when: <validated-by column> + `just check` green. Do not merge; report the branch.
```

## 5. Tests and evaluation

**5.1 Synchronization (T3, T11).** One test per rule in ARCHITECTURE §3: duplicate final (same `segment_id`) is a no-op; out-of-order `seq` dropped client-side (TS unit test); translation with stale `revision` dropped; reconnect with `Last-Event-ID` gets exactly the missed events; late join after ring-buffer rollover loads from SQLite; bounded queues never grow past their limit; restart → `degraded`, finals kept.

**5.2 Security (T6, T9).** Unauthenticated WebSocket rejected; expired, revoked or wrong-session token rejected; a viewer token cannot open ingest; a session from org A is unreachable with org B's context; no provider key appears in any response; token check rate-limited.

**5.3 Multilingual eval** (`backend/eval`, new task `live`). Cases: FLEURS clips (kk, ru, en, zh, ar, de, ja, uz, ky, tg, mn), the synthetic messy kk/ru meeting, and a numbers/names/dates script read aloud (synthetic `say`). Metrics: WER (en/de) or CER (zh/ja) against FLEURS references; numeric-token preservation (exact match); LID accuracy; final latency P50/P95/P99, split into ASR / translate / fan-out from event timestamps. **kk and ru translations reviewed by a human** on 30 sentences each before either is marked `eval_passed`. LLM-as-judge is never the only grader.

**5.4 Regression.** The 354 existing tests, 4 Playwright suites, ruff and Biome stay green on every merge.

## 6. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| No provider key, so the experiments can't run | high (now) | blocks Phase 4 | E3 runs now; ask for a key first |
| Kazakh ASR quality is poor in streaming (batch large-v3-turbo got ~1 word in 6 wrong) | medium | core market | E1 measures it before anything else is built; Azure as second opinion |
| Live speaker attribution: one room mic = one stream; cloud streaming diarization is unverified | high | captions show "Speaker ?" | v1 labels per source stream; host can rename; diarization after the meeting via the existing batch path |
| Auth model too thin for enterprise (one shared key) | certain | sales blocker, not a tech blocker | live sessions use scoped guest tokens; real RBAC is v0.4 |
| Restart drops live audio | low | gap in the transcript | state row + `degraded` + resume; stated in the UI |
| Vendor preview models change (Gemini Live Translate, Chirp versions) | medium | breakage | adapters pinned; one-file swap |
| Turkmen not covered by any vendor | certain | one priority language | captions from translation only; ASR via optional WhisperLiveKit later |
| Scope creep from the 35-event, 17-doc spec | high | months lost | D1, D5, D6 |

## 7. Acceptance (first release = Phases 4–5)

1. Host starts a live session on an existing meeting with consent; mic or browser-tab audio is ingested.
2. Speech appears as provisional source text and finalizes; language is auto-detected or overridden.
3. Three or more target languages run at once; each viewer picks their own language; channels with no viewers stop translating.
4. Each final translation is stored against its source segment and revision; the source transcript is never replaced.
5. Reconnect, late join, duplicates, stale revisions and a provider drop pass the T11 suite.
6. A guest joins by QR or link without an account; expired or revoked links fail; a viewer cannot upload audio.
7. After the session ends, the existing extraction runs once and every item cites live source segments.
8. 100 simulated viewers on one session: final-caption P95 ≤3 s, memory flat over 60 min.
9. Only `eval_passed` languages are labelled supported in the UI; the others say what is missing.
10. `THIRD_PARTY_NOTICES.md` lists every vendored file; all existing tests stay green.
