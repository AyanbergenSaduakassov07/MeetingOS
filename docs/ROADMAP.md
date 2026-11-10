# Roadmap

Target: **v1.0 is a version a small team (a student club, a 5–20 person startup) can self-host and trust with real meetings.** Every milestone ends with something you can demo.

## v0.2: Foundation (released)

Goal: make the codebase our own and close the gaps that blocked any real use.

- [x] Remove the code inherited from the voice-studio starting point (TTS, model downloads, captures, desktop build)
- [x] One name, one port (8470), one version across backend, web, Docker and just
- [x] API-key auth: bearer token for agents, HttpOnly session cookie for the browser
- [x] Server refuses to bind a public interface without a key
- [x] Consent required on upload, stored with the meeting
- [x] Real MCP tools: `list_meetings`, `list_commitments`, `ask`
- [x] Dockerfile and compose that actually build (web bundle plus API, non-root user, loopback port)
- [x] Login screen, consent dialog, sign-out
- [x] README, `.env.example`, security policy
- [x] Playwright web tests in CI, against a seeded demo dataset (`just seed-demo`)
- [x] Tag `v0.2.0`

## v0.3: Measured quality (current)

Goal: know how good the extraction is on real meetings, not on seeded data.

- [x] Messy synthetic recording (`scripts/make_messy_meeting.py`: pauses, sighs, fast speech, overlap, a Russian aside) run end to end through local transcription. Found and fixed: dropped Russian line, timestamps ~8 s early after long pauses, an empty report shown as "no decisions" when extraction had no key
- [x] First real-recording run (2026-11-10): AMI ES2002a (EN), a Russian government session, a Russian interview, a Kazakh FLEURS clip, all auto-detected, local `large-v3-turbo`. Found and fixed: SQLite "database is locked" when two meetings overlap (write transaction held across LLM calls), long meetings silently cut to the first 120 segments, RU items written in English, verbatim duplicate items, copilot dead when embeddings 402, meetings stuck forever after a restart, 500 on binary bodies to JSON routes
- [ ] Extraction quality on AMI is still poor against its ground truth (see the audit notes in the v0.3 PR); trivial items outrank the real decisions
- [ ] Speaker diarization on the default path (every real meeting showed 0 speakers, so commitments have no owner)
- [ ] Record 5–10 real meetings (with consent), English and Russian, and annotate the decisions, actions and commitments by hand
- [ ] Add them to `backend/eval` as frozen cases; report precision and recall per item type
- [ ] Embeddings provider that works on the free path (local `bge-m3` via an OpenAI-compatible server), so cross-language retrieval is measured with real vectors instead of the stub
- [ ] `just eval-ci` gates PRs on a regression threshold
- [ ] Publish the numbers in the README, including where it fails

## v0.4: Teams

Goal: more than one person, more than one team, on one install.

- [ ] User accounts (email + password or magic link), roles from the existing `UserRole`
- [ ] Every route scoped to the caller's organization, not just the copilot and MCP
- [ ] Per-user API tokens for agents, revocable
- [ ] Audit log of who listened to or exported what
- [ ] Local-only mode: faster-whisper transcription (done: `TRANSCRIPTION_PROVIDER=faster_whisper`) plus an Ollama model, so no audio leaves the machine

## v1.0: Ship

- [ ] Hosted demo with seeded, consented sample meetings
- [ ] Two-minute demo video
- [ ] Backup and restore for the data directory
- [ ] Upgrade path: migrations tested from v0.2 data
- [ ] Docs site: setup, providers, MCP, privacy model

## Not planned

- Live meeting bots that join Zoom or Meet calls (consent is much harder to get right)
- A desktop app. It is a web app; run it locally or on a server.
