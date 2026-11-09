# Security

MeetingOS stores meeting audio and transcripts, which are personal data about everyone in the room. Please report problems privately.

## Reporting

Use GitHub's **private vulnerability reporting** (Security tab → *Report a vulnerability*). Don't open a public issue. Include steps to reproduce and the impact. Expect an acknowledgement within a few days.

Only the latest `main` is supported.

## Deployment checklist

- Set `MEETINGOS_API_KEY` (`just gen-key`). The server refuses a non-loopback bind without one.
- Put TLS in front of it (Caddy, nginx, a tunnel). The session cookie is marked `Secure` only over HTTPS.
- Keep `.env` out of git and out of images; `.dockerignore` already excludes it.
- Decide where audio may go: `MEETINGOS_ALLOWED_INFERENCE_HOSTS` controls this, and a local model (`OPENAI_COMPATIBLE_BASE_URL`) keeps it on your network.
- Set a retention period and schedule `just purge --commit`.

## Known limits (v0.2)

- One API key per deployment, so everyone with the key sees every meeting. Per-user accounts and per-org scoping on every route are planned for v0.4 ([roadmap](docs/ROADMAP.md)).
- Redaction is pattern-based. It masks emails, phone numbers and ID numbers, but not names, so it is a mitigation, not anonymization.
- Copilot answers come from retrieved meeting and document text, which is untrusted input. The model is given no tools, so an injected instruction has nothing to act on, but it can still distort an answer. Check the citations.

The detailed review is in [docs/security/v0.1-llm-and-privacy-review.md](docs/security/v0.1-llm-and-privacy-review.md).
