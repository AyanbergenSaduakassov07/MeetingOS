# MeetingOS Live — Architecture (Phase 3)

Status: for approval · 2026-11-26. Covers the spec's ARCHITECTURE, EVENT_CONTRACTS, PROVIDER_ARCHITECTURE, DATA_MODEL, SECURITY_AND_PRIVACY and UI_UX_SPECIFICATION. Decisions marked **D1–D7** are open until you approve them (see PLAN §1).

## 1. Shape

```text
Host browser                                Participants (browser, phone via QR)
  mic / tab audio                             captions ?lang=xx
  AudioWorklet → PCM16 16 kHz                 EventSource (SSE), Last-Event-ID replay
        │  WebSocket (binary)                        ▲
        ▼                                            │
┌──────────── backend/live (inside the existing FastAPI process) ────────────┐
│ LiveSession (one per meeting, in memory, state row in SQLite)              │
│   SourceStream ──► StreamingASR adapter ──► Segmenter ──► transcript.final │
│   (one per mic)      (ResilientASR wrap)      (sentences)      │           │
│                                                                ▼           │
│   persist TranscriptSegment(is_final=True)        Translator (one call per │
│                                                    sentence → all ACTIVE   │
│   EventLog: monotonic seq, bounded ring buffer     target langs at once)   │
│        │                                                       │           │
│        └──── fan-out: SSE per subscriber, filtered by lang ◄───┘           │
│   LanguageChannel refcount: lang active while ≥1 subscriber (+60 s grace)  │
└────────────────────────────────────────────────────────────────────────────┘
        │ on session end
        ▼
existing pipeline: _try_segment → _try_extract (once, on the source transcript)
```

Rules from the spec that this shape meets: one orchestration layer, one meeting identity (`Meeting`), one authoritative transcript (`TranscriptSegment`), one auth system, one event envelope, no new database, no new service in v1. Recognition runs once per source stream. Translation runs once per sentence and covers all active languages. Fan-out is in-process.

**Why SSE for viewers, not WebSocket:** viewers only receive. With `EventSource`, the browser reconnects by itself and sends `Last-Event-ID`. That `id` is our sequence number, so late joins and reconnects replay from the ring buffer, and from SQLite when the buffer has rolled over, with no client logic. SSE is plain HTTP, so it sits behind the existing middleware and proxies. Only the host's upstream audio needs a WebSocket.

**Why not LiveKit in v1:** text fan-out to 100 viewers is trivial in-process. LiveKit (SFU, per-language audio tracks) arrives with voice interpretation in Phase 6. The event envelope stays the same.

**Scale limit, stated:** one process with in-memory session state matches today's single-worker SQLite deployment. Running several workers would need Redis pub/sub for fan-out. That stays out of scope until a customer needs it.

## 2. Pipelines

- **A, cascaded (default):** ASR → segmenter → translate finals → captions → (Phase 6) TTS per language channel.
- **Partials:** the speaker's own-language partial text is shown live, marked provisional. **Partials are not translated in v1.** Translating every partial into N languages multiplies cost by about 5–10×, and the result flickers. Final translated captions are targeted at ≤3 s after the end of the utterance. Revisit after measuring (see PLAN §5).
- **B, direct speech-to-speech:** deferred. OpenAI covers 13 output languages and none of the Central Asian ones. Gemini Live Translate is a preview model. If it is added, the source transcript must still come from pipeline A's ASR.

## 3. Event envelope (one contract, Python dataclass mirrored as a TS type)

```json
{ "v": 1, "seq": 1042, "type": "transcript.final",
  "session_id": "…", "meeting_id": "…", "org_id": "…",
  "segment_id": "…", "revision": 0, "stream_id": "mic-1",
  "speaker": "Speaker 1", "lang": "kk", "target_lang": null,
  "start_ms": 81230, "end_ms": 84410, "text": "…",
  "provider": "google-chirp3", "ts": "2026-…Z" }
```

v1 event types (8, out of the spec's 35): `session.state` (started, paused, ended, degraded), `transcript.partial`, `transcript.final`, `translation.final`, `translation.failed`, `participant.count`, `provider.status`, and `transcript.corrected` (host edits; the revision number increments). Phase 6 adds `interpretation.audio.*`. Join, leave and language change are HTTP calls, not broadcast events.

Synchronization rules (each one gets a test):
- `seq` is a per-session monotonic integer, assigned only by the EventLog under one asyncio lock. Clients render in `seq` order and drop events with `seq ≤ last`. That one rule handles duplicates and out-of-order delivery.
- A partial never touches the DB. A final is written once, with `segment_id` as the idempotency key, so a retried provider final with the same id is a no-op.
- `translation.final` carries `segment_id` + `revision` of the source it translated. A translation that arrives after a correction with an older revision is dropped. Late translations still attach to the right segment, because they are keyed by id, not by arrival time.
- Queues are bounded: per-session audio queue (drop oldest frames and emit `provider.status: lagging`), translation queue (coalesce; on overflow skip partial work, never finals), per-subscriber SSE queue (a slow client is disconnected and reconnects with Last-Event-ID).
- On restart, the state row says `live`, so the session shows `degraded` and the host is asked to resume. Finals already written are kept. Audio during the gap is lost, and that is stated.

## 4. Provider interfaces (`backend/live/`)

```python
class StreamingASR(Protocol):            # one instance per source stream
    async def start(self, *, languages: list[str] | None) -> None   # None = auto LID
    async def send(self, pcm16: bytes) -> None
    def events(self) -> AsyncIterator[AsrEvent]                      # partial | final, lang, start/end
    async def close(self) -> None

class Translator(Protocol):
    async def translate(self, text: str, *, source: str, targets: list[str],
                        context: list[str], glossary: Glossary | None) -> dict[str, str]
```

- `ResilientASR` (ported from LiveTranslate) wraps any `StreamingASR`: reconnect with a 2 s replay buffer, then fail over to the next adapter allowed by org policy, emitting `provider.status`.
- Adapters in v1: **one** ASR (D2, recommended Google Chirp 3 streaming, which has auto LID and kk/ky/tg) and **one** translator (D3). Each one is a single file. Each call goes through `egress_log`.
- Policy: `Organization.settings["live"]["providers"]` is an allowlist. If no allowed adapter can serve a language, the UI says so ("captions unavailable for Turkmen with your approved providers"). The system never silently routes elsewhere.

## 5. Language registry

`backend/live/languages.json`: one entry per BCP-47 tag with `name`, `native`, `dir` (ltr/rtl), and per-provider codes for `asr`, `translate`, `tts`, `auto_detect`, plus `verified` (`none` | `vendor_listed` | `eval_passed`). Served at `GET /api/live/languages`. The UI builds every language picker from it. No other hardcoded list. Static JSON, no table: it changes when a provider changes, and that is a code review.

## 6. Data model (additive migrations only, using the existing `migrations.py` `_ensure_column` / create-table pattern)

| Change | Purpose |
|---|---|
| Reuse `Meeting` (`source=live`, `status=recording` → `processing` → `completed`), `TranscriptSegment` (`is_final`, `language`, `sequence`), `Speaker` | one meeting identity, one transcript |
| New `live_sessions` (id, meeting_id, org_id, state, started_at, ended_at, source_mode, glossary JSON, keep_audio bool) | session state that survives restart |
| New `live_join_tokens` (id, session_id, token_hash, role=`viewer`, expires_at, revoked_at, created_at) | guest access |
| New `segment_translations` (segment_id FK, target_lang, revision, text, provider, created_at; unique(segment_id, target_lang, revision)) | finalized translations, each pointing at its source segment |

No new user, participant, organization or speaker tables. Participant language preference lives in the browser (localStorage plus the `?lang=` param), because guests have no account. Glossary for v1 is a JSON list on the session, picked from `Organization.settings["glossaries"]`. A glossary table can come later if orgs share many glossaries. Audio is optionally appended to a WAV at `recording_path`, so the existing player and audio-jump citations work after the meeting. Retention follows `Organization.retention_days`.

## 7. Security and privacy

- **WebSocket ingest:** auth checked inside the handler (cookie or bearer, same `auth.is_authenticated`) because the middleware skips WebSockets. Add a test that an unauthenticated WebSocket gets close code 4401.
- **Guest links:** 32-byte random token, only its SHA-256 stored, scoped to one session, viewer role (captions only, no audio upload, no transcript history beyond this session), default expiry at session end + 1 h, revocable by the host. A QR code encodes `/live/<session>?t=<token>`. Rate limit on token checks.
- **Org isolation:** every live route resolves the session → `org_id` and checks it against the caller. Until v0.4 user accounts exist, the API-key holder is the host for the default org. Live sessions do not make org scoping worse than today, but they cannot make it better than v0.4 allows. Stated as a limitation.
- Provider keys stay server-side. Browsers never talk to a provider directly.
- Consent: starting a session requires the same consent confirmation as upload. The guest page shows a "this meeting is transcribed and translated by <providers>" notice.
- No telemetry added. Test fixtures use synthetic audio only (`scripts/make_messy_meeting.py`, FLEURS clips), never real meetings sent to cloud providers.

## 8. UI (inside the existing shell and design system: Radix, Tailwind, i18n)

- **Host** (`/meetings/:id/live`): start/stop, source picker (mic or tab audio via `getDisplayMedia`), detected-language chip with override, active languages and viewer count, provider health dot, live caption preview, QR/link dialog, "presentation mode" button.
- **Participant** (`/live/:sessionId`, guest-reachable, phone-first): searchable language picker with native names, caption stream (provisional partials greyed out, finals solid), "show original" toggle, connection state, font size control. RTL handled with `dir` from the registry.
- **Presentation** (`/live/:sessionId/present?langs=en,ru`): full-screen, high contrast, 1–2 languages side by side, large type, nothing else.
- Physical conference mode is these three views, not a separate subsystem.
