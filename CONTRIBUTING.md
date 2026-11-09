# Contributing

## Setup

```bash
just setup   # Python 3.13 venv via uv, bun workspaces, .env
just dev     # API :8470 + UI :5173
```

## Before a PR

```bash
just check   # ruff, pytest, TypeScript typecheck
bun run lint # biome
```

- **Tests.** New logic gets a test. A bug fix gets a regression test that fails before the fix and passes after.
- **SQL.** Parameterized queries only: go through SQLAlchemy, never build SQL with f-strings.
- **Routes stay thin.** Business logic lives in `backend/meetings/` or `backend/memory/`, not in `backend/routes/`.
- **Logging.** Use `logging`, not `print`, and never log transcript text or keys.
- **i18n.** UI strings go in both `web/src/i18n/locales/en` and `ru`. Meeting content (titles, quotes) is never translated.
- **Prompts and extraction.** Run `just eval` before and after, and put both numbers in the PR.

## Commits

Use short imperative subjects (`Add consent check to upload`), one logical change per commit.
