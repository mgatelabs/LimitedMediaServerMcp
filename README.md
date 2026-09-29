# MediaServerMCP

A single-instance **Model Context Protocol (MCP) server** in Python that gives a local AI agent authenticated access to a local media/volume server. It exposes 56 tools that mirror the existing Angular web-client API calls (`auth.service.ts`, `media.service.ts`, `volume.service.ts`), including background process tracking, plugin execution, and cursor-based pagination.

Built on [FastMCP](https://github.com/modelcontextprotocol/python-sdk) (`mcp` package).

## Requirements

- Python 3.11+
- The local media server running and reachable at the configured URL
- Same-machine deployment: the MCP server **must run on the same machine as the AI agent** — scratch tools exchange local filesystem paths and remote deployment is not supported

## Setup

```
mcp_media_server/
├── mcp_server.py        # entry point — registers all 56 tools
├── config.py            # config loader (single source: config.json)
├── session.py           # in-memory session + feature-flag store
├── http_client.py       # authenticated HTTP wrapper (auto re-login on 401)
├── auth_client.py       # login / renew / session info
├── media_client.py      # folders, files, download, upload, move, preview
├── volume_client.py     # books, chapters, images, tags
├── book_session.py      # in-memory reading context for book navigation
├── process_client.py    # background task list/status/log/cancel
├── plugin_client.py     # plugin list/describe/run
├── cursor_store.py      # pagination cursors
├── scratch.py           # scratch directory init/purge/reserve
├── config.json          # YOU create this — not committed
├── requirements.txt
└── .gitignore
```

```powershell
cd mcp_media_server
pip install -r requirements.txt
```

### Configure

Create `mcp_media_server\config.json` (read once at startup — restart the server after changes):

```json
{
  "server": {
    "host": "localhost",
    "port": 8000,
    "https": false,
    "ssl_verify": true
  },
  "auth": {
    "username": "myuser",
    "password": "mypassword",
    "pin": "",
    "totp_token": ""
  },
  "scratch": {
    "path": "C:/temp/mcp_scratch",
    "max_age_days": 7
  }
}
```

| Section | Key fields |
|---|---|
| `server` | `host`, `port`, `https`, `ssl_verify` (`false` for self-signed certs) |
| `auth` | `username`, `password`, optional `pin`, optional `totp_token` |
| `scratch` | `path` (local dir, created at startup), `max_age_days` (purge on startup) |

Full schema and examples: [`docs/08-configuration.md`](docs/08-configuration.md).

> **Security:** never commit `config.json` — it is already in `.gitignore`.

## Run

```powershell
# stdio transport (default) — launched by the MCP client
python mcp_server.py

# streamable-http transport — separate process on the same machine
python mcp_server.py tcp
```

On startup the scratch directory is created and entries older than `max_age_days` are purged.

## Local OpenCode setup

Add a `mcp` block to your OpenCode config (e.g. `opencode.json`):

```json
{
  "mcp": {
    "media-server": {
      "type": "local",
      "command": ["python", "mcp_server.py"],
      "cwd": "H:\\Angular\\MediaServerMCP\\mcp_media_server",
      "enabled": true
    }
  }
}
```

Notes:
- `cwd` must point at the `mcp_media_server` directory — the modules use flat imports, and `config.json` is resolved relative to it
- `python mcp_server.py` runs the stdio transport (the default)
- No `environment` block needed — all connection and credential settings live in `mcp_media_server\config.json`
- Restart OpenCode (or the MCP server) after editing `config.json`

Other MCP-capable clients (Claude Desktop, Cursor, …) work the same way with their usual `mcpServers` shape — all settings come from `config.json`, no env vars. See [`docs/13-client-integration.md`](docs/13-client-integration.md).

## Tools (56)

| Domain | Count | Tools |
|---|---|---|
| Auth | 3 | `auth_login`, `auth_renew`, `auth_get_session_info` |
| Media | 16 | `media_list`, `media_list_folders`, `media_list_files`, `media_get_folder`, `media_get_file`, `media_download_file`, `media_upload_file`, `media_migrate_file`, `media_get_preview`, `media_move_file`, `media_move_folder`, `media_create_folder`, `media_update_folder`, `media_update_file`, `media_set_folder_active`, `media_upload_preview` |
| Scratch | 2 | `scratch_get_path`, `scratch_create_file` |
| Volume | 12 | `volume_list_books`, `volume_get_book`, `volume_list_chapters`, `volume_list_images`, `volume_get_image`, `volume_update_title`, `volume_update_alt_name`, `volume_update_tags`, `volume_update_rating`, `volume_list_tags`, `volume_guess_tags`, `volume_update_book` |
| Book nav | 7 | `book_select`, `book_get_context`, `book_next_chapter`, `book_prev_chapter`, `book_next_image`, `book_prev_image`, `book_update` |
| Process | 6 | `process_list`, `process_get_status`, `process_get_log`, `process_cancel`, `process_stop_server`, `process_restart_server` |
| Plugin | 4 | `plugin_list_ai`, `plugin_describe`, `plugin_list`, `plugin_run` |
| Pagination | 6 | `search_books`, `search_media`, `search_media_by_date`, `cursor_next`, `cursor_prev`, `cursor_close` |

Per-tool contracts (parameters, return shapes, behavior):

- Auth — [`docs/02-auth-tools.md`](docs/02-auth-tools.md) · Session & feature flags — [`docs/11-session-features.md`](docs/11-session-features.md)
- Media — [`docs/03-media-tools.md`](docs/03-media-tools.md)
- Volume — [`docs/04-volume-tools.md`](docs/04-volume-tools.md)
- Book navigation — [`docs/14-book-navigation.md`](docs/14-book-navigation.md)
- Pagination — [`docs/07-pagination-tools.md`](docs/07-pagination-tools.md)
- Process — [`docs/09-process-tools.md`](docs/09-process-tools.md)
- Plugin — [`docs/10-plugin-tools.md`](docs/10-plugin-tools.md)

## Smoke test

Run in order through the MCP client:

1. `auth_login` → `success: true`
2. `volume_list_books` with `limit=5` → up to 5 books
3. `volume_get_book` on a `book_id` → full details
4. `volume_list_chapters` → chapters list
5. `volume_list_images` → filenames
6. `volume_get_image` → image content
7. `media_list` with empty `folder_id` → root folders/files
8. `media_list_folders` on root → only folders
9. `volume_list_tags` → tag strings
10. `volume_update_title` → verify with `volume_get_book`
11. `search_books` → `cursor_id` + first 20 items
12. `cursor_next` → next page
13. `cursor_prev` → back to page 1
14. `cursor_close` → `{ "closed": true }`
15. `search_media` on root → mixed folders/files with `type` field
16. `book_select` on a `book_id` → reading context summary (chapter 1, image 1)
17. `book_next_image` → image content + updated position; auto-crosses chapter boundaries
18. `book_get_context` → current position without a network call

## Design notes (MVP scope)

- **In scope:** single-process stdio (or local TCP) MCP server; JWT Bearer auth with automatic re-login on 401/expiry; full mirror of the web-client API; all requests `multipart/form-data` POST.
- **Out of scope (post-MVP):** multiple simultaneous sessions / thread safety; SSE/WebSocket transport; progress-history tracking; bookmarks; duplicate scanning; hard-session/pin management.
- No threading — single instance, single thread; one shared `requests.Session`.
- Session token lives in memory only (`session.py`); never persisted to disk.
- Binary responses (images, downloads) arrive as base64 / local scratch paths so the JSON transport stays clean.
- Errors propagate to the MCP framework as tool errors — never swallowed.

Full implementation reference: [`docs/05-implementation-guide.md`](docs/05-implementation-guide.md) · Document index: [`docs/00-overview.md`](docs/00-overview.md)
