# Running live captions

Host page: `/live` (behind the normal sign-in). Guest link: `/watch/<session>?t=<token>`,
shown on the host page. No sign-in for guests. A link works for 12 h (the live stream stops
at session end; the transcript stays readable), and "New link" revokes every older link.

## Speech recognition — `MEETINGOS_LIVE_ASR`

| Value | What it does |
|---|---|
| `local` (default) | faster-whisper on this machine, utterance by utterance (cut at ~0.7 s pauses). Install: `uv pip install -r backend/requirements-local.txt`. Model: `MEETINGOS_LIVE_WHISPER_MODEL` (default: the batch model). Captions lag a few seconds; no partials. |
| `stub` | Emits "Test caption N." every 3 s of audio. For UI work and tests; no model. |

Cloud streaming (Google Chirp 3, Azure) is not built yet; it needs an account and key.

## Translation — `MEETINGOS_LIVE_TRANSLATOR`

| Value | What it does |
|---|---|
| `google` (default when `GOOGLE_TRANSLATE_API_KEY` is set) | Cloud Translation v2, one request per target language. |
| `llm` (default otherwise) | The configured LLM provider (`ANTHROPIC_API_KEY` / OpenAI-compatible), one call per sentence for all open languages, with the last 3 sentences as context. |

Only languages a viewer has open are translated; a language stays warm 60 s after its
last viewer leaves. Every outbound call goes through the egress log.

## Try it without keys or a microphone

```bash
MEETINGOS_LIVE_ASR=stub .venv/bin/python -m backend.main --data-dir /tmp/live-demo
cd web && bun run dev      # open http://localhost:5173/live
```

Translations show "Translation unavailable" until a translator key is set.

## Limits

- One server process: sessions live in memory. A restart marks running sessions
  `interrupted` and analyses what was captured.
- Behind a reverse proxy, allow WebSocket upgrade on `/api/live/sessions/*/audio`
  and disable buffering for `/api/live/view/*/events` (SSE).
