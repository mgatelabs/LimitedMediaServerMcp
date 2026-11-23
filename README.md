# MediaServerMCP

A single-instance **Model Context Protocol (MCP) server** in Python that gives a local AI agent authenticated access to a self-hosted [Limited Media Server](https://github.com/mgatelabs/LimitedMediaServer). It exposes 71 tools spanning auth, media browsing, file navigation, folder stacks, volume (book/chapter/image) management, background processes, plugins, and item-level search/chapter/image cursors.

Built on [FastMCP](https://github.com/modelcontextprotocol/python-sdk) (the `mcp` package) and the [LimitedMediaServerClient](https://github.com/mgatelabs/LimitedMediaServerClient) library.

## Requirements

- Python 3.11+
- A running Limited Media Server reachable at the configured URL
- Same-machine deployment: the MCP server **must run on the same machine as the AI agent** — scratch tools exchange local filesystem paths and remote deployment is not supported

## Setup

```
mcp_media_server/
├── mcp_server.py        # entry point — registers all 71 tools
├── cursor_store.py      # single active search cursor + chapter/image list cursors
├── file_session.py      # in-memory file browsing context
├── folder_stack.py      # server-side folder stack for tree traversal
├── scratch.py           # scratch directory init/purge/reserve
├── config_example.json  # copy to config.json and edit
├── requirements.txt
└── .gitignore
```

```powershell
cd mcp_media_server
pip install -r requirements.txt
```

`requirements.txt` installs `LimitedMediaServerClient` from its GitHub release tag — that repo must be reachable (it is public).

### Configure

Copy `mcp_media_server/config_example.json` to `mcp_media_server/config.json` and fill in your values (read once at startup — restart the server after changes):

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

Individual `MEDIASERVER_*` environment variables override the corresponding `config.json` fields, so the file can be omitted entirely when env vars are used (e.g. `MEDIASERVER_HOST`, `MEDIASERVER_PORT`, `MEDIASERVER_USERNAME`, `MEDIASERVER_PASSWORD`, …). See [`docs/08-configuration.md`](docs/08-configuration.md).

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
    "lms": {
      "type": "local",
      "command": ["python", "mcp_server.py"],
      "cwd": "C:/path/to/mcp_media_server",
      "enabled": true
    }
  }
}
```

Notes:
- `cwd` must point at the `mcp_media_server` directory — `config.json` is resolved relative to it
- `python mcp_server.py` runs the stdio transport (the default)
- No `environment` block needed — all connection and credential settings live in `mcp_media_server/config.json` (or `MEDIASERVER_*` env vars)
- Restart OpenCode (or the MCP server) after editing `config.json`

Other MCP-capable clients (Claude Desktop, Cursor, …) work the same way with their usual `mcpServers` shape — all settings come from `config.json`, no env vars required. See [`docs/13-client-integration.md`](docs/13-client-integration.md).

## Tools (71)

| Domain | Count | Tools |
|---|---|---|
| Auth | 3 | `auth_login`, `auth_renew`, `auth_get_session_info` |
| Media | 16 | `media_list`, `media_list_folders`, `media_list_files`, `media_get_folder`, `media_get_file`, `media_download_file`, `media_upload_file`, `media_migrate_file`, `media_get_preview`, `media_move_file`, `media_move_folder`, `media_create_folder`, `media_update_folder`, `media_update_file`, `media_set_folder_active`, `media_upload_preview` |
| File navigation | 5 | `files_open`, `files_current`, `files_next`, `files_prev`, `files_get_preview` |
| Folder stack | 5 | `folder_stack_create`, `folder_stack_push_children`, `folder_stack_pop`, `folder_stack_peek`, `folder_stack_close` |
| Scratch | 2 | `scratch_get_path`, `scratch_create_file` |
| Volume | 19 | `volume_list_books`, `volume_get_book`, `volume_get_name`, `volume_get_alt_name`, `volume_get_style`, `volume_get_tags`, `volume_get_rating`, `volume_get_active`, `volume_list_chapters`, `volume_list_images`, `volume_get_image`, `volume_update_title`, `volume_update_alt_name`, `volume_update_tags`, `volume_update_rating`, `volume_update_style`, `volume_list_tags`, `volume_guess_tags`, `volume_update_book` |
| Chapter/image cursors | 4 | `chapter_next`, `chapter_prev`, `image_next`, `image_prev` |
| Process | 6 | `process_list`, `process_get_status`, `process_get_log`, `process_cancel`, `process_stop_server`, `process_restart_server` |
| Plugin | 4 | `plugin_list_ai`, `plugin_describe`, `plugin_list`, `plugin_run` |
| Search cursor | 7 | `search_books`, `search_media`, `search_media_by_date`, `cursor_info`, `cursor_next`, `cursor_prev`, `cursor_close` |

Per-tool contracts (parameters, return shapes, behavior):

- Auth — [`docs/02-auth-tools.md`](docs/02-auth-tools.md) · Session & feature flags — [`docs/11-session-features.md`](docs/11-session-features.md)
- Media — [`docs/03-media-tools.md`](docs/03-media-tools.md)
- File navigation — [`docs/18-file-navigation.md`](docs/18-file-navigation.md)
- Folder stacks — [`docs/17-folder-stack-tools.md`](docs/17-folder-stack-tools.md)
- Volume — [`docs/04-volume-tools.md`](docs/04-volume-tools.md)
- Pagination — [`docs/07-pagination-tools.md`](docs/07-pagination-tools.md)
- Process — [`docs/09-process-tools.md`](docs/09-process-tools.md)
- Plugin — [`docs/10-plugin-tools.md`](docs/10-plugin-tools.md)

> The book-navigation tools (`book_*`) from earlier revisions were removed; image browsing is now done through the `volume_list_chapters` / `volume_list_images` / `volume_get_image` tools — the list calls point the chapter/image cursors so `chapter_id` and `filename` can be omitted — and file browsing through `files_*`.

## Smoke test

Run in order through the MCP client:

1. `auth_login` → `success: true`
2. `volume_list_books` with `limit=5` → up to 5 books
3. `volume_get_book` on a `book_id` → full details
4. `volume_list_chapters` → chapters list
5. `volume_list_images` on the first chapter → filenames
6. `volume_get_image` → image content
7. `media_list` with empty `folder_id` → root folders/files
8. `media_list_folders` on root → only folders
9. `volume_list_tags` → tag strings
10. `volume_update_title` → verify with `volume_get_book`
11. `search_books` → first item: `{ cursor_id, type: "v", index, content, total }`
12. `cursor_next` → next item; at the end of the fetched items: `{ status: "exhausted", offset, total }`
13. `search_books(offset=<offset from step 12>)` → continues stepping
14. `cursor_prev` → previous item; on the first item: `{ status: "at_start" }`
15. `volume_get_book` with no `book_id` → the book the cursor points at
16. `volume_get_style` with no `book_id` → just the style field of the cursor's book
17. `volume_list_chapters` with no `book_id` → chapters of the cursor's book; points the chapter cursor at chapter 1
18. `volume_list_images` with no `chapter_id` → files of the chapter cursor's chapter; points the image cursor at file 1
19. `image_next` → next file; at the end of the chapter: `{ status: "exhausted" }`
20. `volume_get_image` with no `chapter_id`/`filename` → the image the image cursor points at
21. `chapter_next` → next chapter; at the end of the book: `{ status: "exhausted" }`
22. `cursor_close` → `{ "closed": true }` (also drops the chapter/image cursors)
23. `search_media` on root → first item with `content.type` = `folder`/`file`
24. `files_open` on a folder_id → file context summary (first file)
25. `files_next` → next file; returns `done: true` at the end of the folder
26. `folder_stack_create` on root → `stack_id` + depth
27. `folder_stack_pop` → a subfolder id
28. `folder_stack_close` → `{ "closed": true }`

## Design notes (MVP scope)

- **In scope:** single-process stdio (or local streamable-http) MCP server; JWT Bearer auth with automatic re-login on 401/expiry; full mirror of the web-client API; all requests `multipart/form-data` POST.
- **Out of scope (post-MVP):** multiple simultaneous sessions / thread safety; SSE/WebSocket transport; progress-history tracking; bookmarks; duplicate scanning; hard-session/pin management.
- No threading — single instance, single thread; one shared `requests.Session`.
- Session token lives in memory only; never persisted to disk.
- Binary responses (images, downloads) arrive as image content / base64 / local scratch paths so the JSON transport stays clean.
- Errors propagate to the MCP framework as tool errors — never swallowed.

Full implementation reference: [`docs/05-implementation-guide.md`](docs/05-implementation-guide.md) · Document index: [`docs/00-overview.md`](docs/00-overview.md)

## Agent scripts

[`agents/`](agents/) contains reusable AI agent scripts (manhwa detection, media archiving, character tagging) that orchestrate these tools through the `lms` MCP server prefix.

## License

MIT — see [`LICENSE`](LICENSE).
