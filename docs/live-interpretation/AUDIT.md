# MeetingOS Live — Audit (Phase 0 + 1)

Status: for approval · 2026-11-26 · base commit `d4a7c08`

Covers the spec's EXISTING_SYSTEM_AUDIT, UPSTREAM_REPOSITORY_AUDIT, CODE_REUSE_MATRIX, LANGUAGE_CAPABILITY_MATRIX and the license matrix. Full per-repo notes, pinned SHAs and file paths live outside the repo in `~/Desktop/Projects/MeetingOS-upstream-audit/findings-*.md`. The shallow clones are kept there too; nothing from them was installed or run.

## 1. What MeetingOS already has

| Area | State | Relevance to Live |
|---|---|---|
| Stack | Python 3.13 FastAPI + SQLAlchemy/SQLite, React 18 + Vite + Tailwind 4 + Radix + react-query + zustand + i18next (en/ru/kk). Single uvicorn process, port 8470. | The Live code goes into the same process (modular monolith). No new service is needed for v1. |
| Transcript model | `TranscriptSegment` has `sequence`, `start_ms/end_ms`, `language`, **`is_final`** ("False while streaming a live meeting"), `speaker_id`. `MeetingSource.LIVE` and `MeetingStatus.RECORDING` exist. | Live finals are written as ordinary segments. No second transcript table is needed. |
| Intelligence | `meetings/ingestion.py::_try_extract(meeting_id)` and `_try_segment` run on stored segments. Evidence/Citation provenance model. | After a session ends, extraction runs once on the source transcript, unchanged. |
| ASR | Batch only: `TranscriptionProvider.transcribe(audio_path)` (`transcription/base.py`). whisper_cloud and faster_whisper providers. No streaming. | Streaming needs a new interface. The batch interface stays for uploads. |
| LLM | `LLMProvider.generate/extract/generate_stream` (`ai/base.py`), Anthropic / OpenAI / OpenAI-compatible, `retry_with_backoff`. | It can serve as the LLM translation adapter with no new dependency. |
| Egress audit | `meetings/egress_log.py`: records every cloud call (provider, host, char counts, no content) for the Privacy page. | Every ASR, translation and TTS call goes through it. This is where provider routing policy is enforced. |
| Auth | One shared API key: bearer for agents, HttpOnly cookie for the browser (`auth.py`). **`ApiKeyMiddleware` only guards `scope["type"]=="http"`, so WebSocket routes are unauthenticated today.** No user accounts. Per-org route scoping and per-user tokens are roadmap v0.4. | Guest links, RBAC and org isolation for live sessions are new work. WebSocket auth must be explicit. |
| Consent | `Meeting.consent_confirmed_at` is required on upload. | Reuse it: a live session cannot start without consent confirmed. |
| Streaming infra | Only NDJSON `StreamingResponse` for the copilot. No WebSocket, SSE or WebRTC. | New. |
| Voicebox | TTS, voice cloning, captures and the desktop build were **deleted on purpose** in `aaec867` / `ff6479f`. They ran on local torch models, and `requirements.txt` forbids torch. | Nothing reusable remains. The spec's "reuse Voicebox TTS" does not apply. |
| Roadmap | v0.3 (measured quality) is current. **"Not planned": live meeting bots, desktop app.** | The spec's Cicada/desktop and Zoom/Teams sections reverse that decision. See decision D4. |
| Tests | 354 backend pytest, 4 Playwright suites, ruff, Biome, CI on main. | Live must keep all of them green. |
| Keys | No `.env`. No provider key configured. | Phase 2 cloud experiments are blocked until one exists. |

## 2. Upstream verdicts

| Repo | Pinned | License (verified) | Verdict | Why |
|---|---|---|---|---|
| Sebzdead/livetranslate | a9ba615 | MIT | **VENDOR AND ADAPT** 3 modules | `asr/base.py` (ResilientASR: reconnect, 2 s ring-buffer replay, failover), `segmenter.py` (partial/final → gapless sentences), `translate.py` (glossary prompt, retry, batch catch-up), and vendor wire notes. The app itself is sync, threaded, single-session and has no auth, so it is not a backbone. |
| kizuna-ai-lab/sokuji-bridge | 8c92ee3 | **No LICENSE file**, archived | REJECT | Cannot be reused legally. Local models only (NLLB is CC-BY-NC), GPU, 1 test, empty API stubs. |
| kizuna-ai-lab/sokuji | b8f1260 | AGPL-3.0 | REFERENCE ONLY | Copy nothing. Its permissive deps can be used directly: `@ricky0123/vad-web` (ISC), `onnxruntime-web` (MIT). |
| pipecat-ai/pipecat | d214403 | BSD-2 | Not now | Models one conversation, not N languages fanned out to N viewers. Revisit only if voice interpretation needs its TTS/transport plumbing. |
| QuentinFuxa/WhisperLiveKit | edcbaef / PyPI 0.2.28 | Apache-2.0 | **USE AS SERVICE (optional, later)** | Self-hosted streaming ASR in its own venv (pulls torch). WS `/asr`, partial = `buffer_transcription`, final = `lines`. Default diarizer Sortformer has an unverified NVIDIA license. Never use its NLLB option (non-commercial). |
| livekit/livekit + SDKs | v1.13.11 | Apache-2.0 | USE AS SERVICE, **Phase 6 only** | Not needed for captions. Needed when translated audio goes to many listeners. |
| livekit-examples/gemini-live-translate | 4fe4eac | MIT | VENDOR AND ADAPT, Phase 6 | `router.py` (speaker × target-lang reconciliation) and the `tx:<speaker>:<lang>` track-naming pattern. Preview model. |
| livekit-examples/live-translated-captioning | 10da3a9 | **No LICENSE** | REFERENCE ONLY | Cannot be copied. Old agents 0.x API. |
| wquguru/cicada | be9785d | Apache-2.0 (app) | REFERENCE ONLY | Native per-OS apps with no library product. BlackHole (GPL-3.0) and VB-Cable (proprietary) are downloaded at install. Speaker-ID weights WeSpeaker are CC BY 4.0 with VoxCeleb data terms unverified. At most `SystemAudioTap.swift` as reference. |
| openai-cookbook realtime_translation_guide | dfd760b | MIT | REFERENCE ONLY | Speech-to-speech output in 13 languages only, with no kk/uz/ky/tg/tk/mn/ar/tr/fa. |
| Azure-Samples/realtime-translation | 53161c2 | MIT | REFERENCE ONLY | Tied to ACS, Cosmos and Bicep. Generic `frontend/utils/{websocket,micro,wav}.ts` could be copied with attribution if needed. |
| JacobLinCool/open-realtime-translate | 3bbf77c | **No LICENSE** | REFERENCE ONLY | Cannot be copied. Python <3.13. |
| Leapfreak/EveryTongue | 3bc8789 | GPL-3.0 | REFERENCE ONLY | GPL, NLLB non-commercial, default admin PIN 1234. |
| didi/meetdot | — | 404 | EXCLUDED | The repo is gone. Only a 2021 fork with 0 stars exists. |

**Backbone decision: LiveTranslate vs Sokuji Bridge → neither.** A thin async layer in-house (~800–1200 lines of backend), with LiveTranslate's three MIT modules ported into it, is less code and less risk than adapting either repo. Sokuji Bridge is legally unusable. LiveTranslate's runtime cannot host multiple tenants or run async.

## 3. File-level reuse matrix (selected only)

| Source file | Target | Class | Change |
|---|---|---|---|
| livetranslate `src/livetranslate/asr/base.py` | `backend/live/asr/resilient.py` | VENDOR AND ADAPT | threads → asyncio; ring buffer kept |
| livetranslate `src/livetranslate/segmenter.py` | `backend/live/segmenter.py` | VENDOR AND ADAPT | port as is, emits `transcript.final` |
| livetranslate `src/livetranslate/translate.py` | `backend/live/translate/llm.py` | VENDOR AND ADAPT | uses `ai/base.LLMProvider`; one call → all active targets |
| livetranslate `docs/vendor-notes.md` + `asr/*.py` | reference for ASR adapters | REFERENCE ONLY | — |
| MeetingOS `ai/base.py`, `meetings/egress_log.py`, `meetings/ingestion.py::_try_extract` | used as is | ALREADY IMPLEMENTED | — |
| `@ricky0123/vad-web` (npm, ISC) | browser VAD, only if needed | USE AS DEPENDENCY | optional; provider-side VAD first |
| `google-cloud-speech`, `google-cloud-translate` (Apache-2.0) | ASR / translation adapters | USE AS DEPENDENCY | pending D2 |
| `whisperlivekit` (PyPI) | optional self-hosted ASR | USE AS SERVICE | separate venv, later |
| `livekit-api` / `livekit-client` | translated audio distribution | USE AS DEPENDENCY | Phase 6 only |

Each vendored file keeps the MIT header and gets an entry in `THIRD_PARTY_NOTICES.md` (repo, SHA, files, changes). Today the only notice is the Voicebox copyright line in `LICENSE`. `THIRD_PARTY_NOTICES.md` is new.

## 4. Language coverage (priority set; "unv" = docs don't confirm)

| Lang | Streaming STT | Translation | TTS |
|---|---|---|---|
| kk | Google Chirp 3, Azure, ElevenLabs | Google, Azure | Gemini Flash TTS, Azure |
| ru, en, zh, de, tr, ja, ko, hi, ar | all major | all | all major |
| uz | Azure, Google (unv) | Google, Azure | Gemini Flash TTS, Azure |
| ky | Google Chirp 3 | Google, Azure | Gemini Flash TTS |
| tg | Google Chirp 3 | Google, Azure | Gemini Flash TTS only |
| mn | Google, Azure | Google, Azure | Gemini Flash TTS, Azure |
| fa | Azure, Google (unv) | Google, Azure | Gemini Flash TTS, Azure |
| tk | **none verified** | Google, Azure | **none verified** |

Captions in 130+ target languages are realistic, since Google and Azure translation each cover 130+. Spoken interpretation reaches about 50+ only on paper, and only the rows above are checked. Turkmen speakers get captions only, not audio. A language counts as "supported" in the registry only after our own eval passes (see PLAN §5). A vendor's language list is not enough.
