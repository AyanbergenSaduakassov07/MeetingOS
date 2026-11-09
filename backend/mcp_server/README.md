# MCP server

Read-only MeetingOS tools for AI agents. The server runs inside the API process and speaks Streamable HTTP at `/mcp`. It is protected by the same `MEETINGOS_API_KEY` bearer token as the REST API.

```bash
claude mcp add --transport http meetingos http://127.0.0.1:8470/mcp \
  --header "Authorization: Bearer $MEETINGOS_API_KEY"
```

| Tool | Arguments | Returns |
|---|---|---|
| `list_meetings` | `limit` (≤100), `status` | id, title, status, language, date |
| `list_commitments` | `overdue`, `limit` (≤200) | owner, text, due date, overdue flag, source meeting |
| `ask` | `question`, `answer_language` | answer, `not_discussed`, citations |

Tools resolve the organization from `MEETINGOS_ORG_ID`, or use the only organization in the database. If several organizations exist and none is pinned, the tools refuse to run.

To debug, run `npx @modelcontextprotocol/inspector` and point it at the URL above with the same header.

Code: `server.py` builds the FastMCP app and `tools.py` holds the tool bodies, which call the same services as the REST routes. Tests are in `backend/tests/test_mcp_tools.py`.
