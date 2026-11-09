# MeetingOS

**Meeting memory for small teams.** Upload a recording and MeetingOS transcribes it, pulls out decisions, action items, risks and commitments, and ties each one to the exact moment in the audio where it was said. Then you can ask questions across every meeting and document your team has, and every answer cites its source.

<p align="center">
  <img src="web/tests/screenshots/meeting-light-en.png" alt="Meeting report: decisions with timestamped quotes and an audio player" width="820" />
</p>

> Status: **v0.2, alpha.** The pipeline, UI and API work end to end. Extraction quality has only been measured on seeded data so far; see the [roadmap](docs/ROADMAP.md).

## What it does

- **Evidence-first extraction.** Every decision, action item, risk and commitment carries a quote and a timestamp. Click it and the player jumps there. If an item has no supporting quote, it is flagged as unverified rather than shown as fact.
- **Commitments tracker.** "I'll send the contract by Friday" turns into an owner, a due date and an overdue flag, collected across all meetings.
- **Org copilot.** Ask "what did we decide about the venue?" and get an answer built only from retrieved transcript and document excerpts, with citations. When the meetings never covered it, the copilot says so instead of guessing.
- **Decision timeline.** Shows how a decision changed from meeting to meeting, and flags when two meetings contradict each other.
- **Documents alongside meetings.** Contracts and notes go into the same searchable index. Documents marked sensitive are redacted before indexing.
- **Bilingual.** Interface in English and Russian. Transcripts and quotes stay in the language they were spoken in.
- **MCP server.** Claude Code, Cursor or any other MCP client can list meetings, read commitments and ask the copilot.

## Privacy model

Meeting audio is personal data, so these behaviors are built in:

| Control | Behavior |
|---|---|
| Consent | An upload is rejected unless the uploader confirms that everyone in the recording agreed. The confirmation is stored with the meeting. |
| Access | `MEETINGOS_API_KEY` protects the API, the MCP endpoint and the docs. The server refuses to listen on a public interface without a key. |
| Egress | Audio and transcripts are sent only to allowlisted inference hosts, and every outbound call is logged. To keep everything on your machine, point it at a local model (`OPENAI_COMPATIBLE_BASE_URL`). |
| Redaction | Optional masking of emails, phone numbers and ID numbers before text reaches a cloud model. Sensitive documents are always redacted. |
| Retention | `just purge` deletes meetings older than the organization's retention period. |

The full review is in [docs/security/](docs/security/v0.1-llm-and-privacy-review.md).

## Quick start

Requirements: Python 3.13, [uv](https://docs.astral.sh/uv/), [bun](https://bun.sh), [just](https://just.systems) and ffmpeg.

```bash
just setup        # venv, deps, .env from .env.example
$EDITOR .env      # add one AI provider key, e.g. ANTHROPIC_API_KEY + OPENAI_API_KEY for Whisper
just dev          # API on :8470, UI on http://localhost:5173
```

Docker (this path requires a key, because it binds 0.0.0.0 inside the container):

```bash
echo "MEETINGOS_API_KEY=$(just gen-key)" >> .env
docker compose up --build   # http://127.0.0.1:8470
```

## Providers

| Job | Options (`.env`) |
|---|---|
| Language model | `AI_PROVIDER=anthropic` (default, `claude-opus-5-5`), `openai`, `openai_compatible` (Ollama, vLLM, OpenRouter) |
| Transcription | `TRANSCRIPTION_PROVIDER=whisper_cloud` (default), `assemblyai`, `pyannote_local` |
| Embeddings | OpenAI or an OpenAI-compatible endpoint |

## Connect an agent (MCP)

The server exposes Streamable HTTP MCP at `/mcp`. This repo ships a `.mcp.json`, so Claude Code picks it up automatically inside the checkout. To add it anywhere else:

```bash
claude mcp add --transport http meetingos http://127.0.0.1:8470/mcp \
  --header "Authorization: Bearer $MEETINGOS_API_KEY"
```

| Tool | Returns |
|---|---|
| `list_meetings` | Recent meetings with status and language |
| `list_commitments` | Open commitments, optionally only overdue ones |
| `ask` | A cited answer from the org copilot |

All three tools are read-only, so an agent can query your meetings but cannot change or delete them.

## Development

```bash
just check        # ruff + pytest + TypeScript typecheck
just seed-demo dir=/tmp/demo  # demo org + meeting, no API keys
just test-web     # Playwright browser tests (needs the dev stack running)
just eval-stub    # extraction scorer smoke test, no API calls
just --list       # everything else
```

```
backend/
  routes/        HTTP edge: meetings, copilot, commitments, decisions, documents, privacy
  meetings/      pipeline: ingestion, extraction, verification, redaction, retention
  memory/        corpus index (SQLite + FTS5 + embeddings), retrieval, org copilot
  ai/            LLM providers behind one interface
  transcription/ speech-to-text providers
  mcp_server/    MCP tools
  eval/          frozen extraction cases and scorer
web/             React + Vite + Tailwind UI, Playwright tests in web/tests
docs/            roadmap, security review
```

API reference: `http://127.0.0.1:8470/docs` while the server is running.

## License

MIT. The backend scaffolding started from [Voicebox](https://github.com/jamiepine/voicebox) (MIT); its license notice is kept in [LICENSE](LICENSE).
