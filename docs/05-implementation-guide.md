# MCP Server — Implementation Guide

This document is a step-by-step recipe for an AI (or developer) to build the MCP server from scratch.  Follow the steps in order.  Each step ends with a concrete verification checkpoint.

---

## Prerequisites

- Python 3.11+
- `pip install mcp requests python-dotenv`
- The local media server running and reachable at the URL you will configure

---

## Step 1 — Project scaffold

Create this directory structure:

```
mcp_media_server/
├── mcp_server.py
├── session.py
├── http_client.py
├── auth_client.py
├── media_client.py
├── volume_client.py
├── process_client.py
├── plugin_client.py
├── cursor_store.py
├── scratch.py
├── config.py
├── config.json        ← created by you, not committed
├── requirements.txt
└── .gitignore
```

**`requirements.txt`**
```
mcp
requests
```

**`.gitignore`**
```
config.json
__pycache__/
*.pyc
```

**`config.json` (template — fill in real values, see `08-configuration.md`)**
```json
{
  "server": {
    "host": "localhost",
    "port": 8000,
    "https": false,
    "ssl_verify": true
  },
  "auth": {
    "username": "your_user",
    "password": "your_password",
    "pin": "",
    "totp_token": ""
  },
  "scratch": {
    "path": "/tmp/mcp_scratch",
    "max_age_days": 7
  }
}
```

**Checkpoint:** `pip install -r requirements.txt` completes without error.

---

## Step 2 — `config.py`

```python
import json
import urllib3
from pathlib import Path

_cfg_path = Path(__file__).parent / "config.json"
with _cfg_path.open() as _f:
    _cfg = json.load(_f)

_server = _cfg["server"]
_auth   = _cfg["auth"]
_scratch = _cfg.get("scratch", {})

_scheme    = "https" if _server.get("https", False) else "http"
SERVER_URL = f"{_scheme}://{_server['host']}:{_server['port']}"
SSL_VERIFY = _server.get("ssl_verify", True)

USERNAME   = _auth["username"]
PASSWORD   = _auth["password"]
PIN        = _auth.get("pin", "")
TOTP_TOKEN = _auth.get("totp_token", "")

SCRATCH_PATH         = Path(_scratch["path"]).expanduser().resolve()
SCRATCH_MAX_AGE_DAYS = int(_scratch.get("max_age_days", 7))

# Suppress urllib3 warnings when ssl_verify is disabled
if not SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
```

No extra logic.  All modules import from here.

**Checkpoint:** `python -c "import config; print(config.SERVER_URL)"` prints the constructed URL.

---

## Step 3 — `session.py`

```python
import time
import base64
import json
from dataclasses import dataclass, field

@dataclass
class SessionStore:
    token: str = ""
    exp: int = 0
    username: str = ""
    features: int = 0
    limits: dict = field(default_factory=dict)

    def is_valid(self) -> bool:
        """Return True if token exists and has >60 s remaining."""
        return bool(self.token) and (self.exp - time.time()) > 60

    def seconds_remaining(self) -> int:
        return max(0, int(self.exp - time.time()))

    def clear(self) -> None:
        self.token = ""
        self.exp = 0
        self.username = ""

    def load_token(self, token: str) -> None:
        """Decode and store a JWT token (no signature verification)."""
        try:
            payload_b64 = token.split(".")[1]
            # Fix padding
            padding = 4 - len(payload_b64) % 4
            payload_b64 += "=" * (padding % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            self.token    = token
            self.exp      = int(payload.get("exp", 0))
            self.username = payload.get("username", "")
            self.features = int(payload.get("features", 0))
            self.limits   = payload.get("limits", {})
        except Exception as exc:
            self.clear()
            raise RuntimeError(f"Failed to decode token: {exc}") from exc

# Module-level singleton
SESSION = SessionStore()
```

**Checkpoint:** unit-test by calling `SESSION.load_token("<a real jwt>")` and asserting `SESSION.is_valid()`.

---

## Step 4 — `http_client.py`

```python
import requests
from session import SESSION
from auth_client import login   # imported lazily to avoid circular deps
from config import SERVER_URL, SSL_VERIFY

_session = requests.Session()
_session.verify = SSL_VERIFY    # applied to every request in this session

def _headers() -> dict:
    return {"Authorization": f"Bearer {SESSION.token}"} if SESSION.token else {}

def _ensure_auth() -> None:
    """Login if session is missing or about to expire."""
    if not SESSION.is_valid():
        login()

def post(path: str, data: dict | None = None, files: dict | None = None) -> dict:
    """POST multipart/form-data.  Auto-authenticates and retries once on 401."""
    _ensure_auth()
    url = SERVER_URL + path
    resp = _session.post(url, data=data or {}, files=files or {}, headers=_headers())
    if resp.status_code == 401:
        # Token rejected server-side — force re-login and retry once
        SESSION.clear()
        login()
        resp = _session.post(url, data=data or {}, files=files or {}, headers=_headers())
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") == "error":
        raise RuntimeError(body.get("message", "Unknown server error"))
    return body

def get(path: str, params: dict | None = None) -> requests.Response:
    """GET request returning the raw Response (caller decides how to read it)."""
    _ensure_auth()
    url = SERVER_URL + path
    resp = _session.get(url, params=params or {}, headers=_headers())
    if resp.status_code == 401:
        SESSION.clear()
        login()
        resp = _session.get(url, params=params or {}, headers=_headers())
    resp.raise_for_status()
    return resp
```

**Important notes:**
- `_session.verify = SSL_VERIFY` is set once on the shared session — no need to pass it on every call.
- `SERVER_URL` and `SSL_VERIFY` are now imported at module level (no lazy import needed here — no circular dependency).
- The `login` import inside the functions still avoids the `http_client → auth_client → http_client` cycle.

**Checkpoint:** with a running server, calling `post("/api/auth/login", {...})` returns a dict with a `token` key.

---

## Step 5 — `auth_client.py`

```python
from session import SESSION
from config import SERVER_URL, SSL_VERIFY, USERNAME, PASSWORD, PIN, TOTP_TOKEN
import requests

_raw = requests.Session()   # plain session, no auth header needed for login
_raw.verify = SSL_VERIFY

def _parse_login_response(body: dict) -> None:
    if body.get("status") != "ok" or "token" not in body:
        raise RuntimeError(body.get("message", "Login failed — no token returned"))
    SESSION.load_token(body["token"])

def login() -> dict:
    """POST credentials to /api/auth/login and store the resulting token."""
    resp = _raw.post(
        SERVER_URL + "/api/auth/login",
        data={
            "username": USERNAME,
            "password": PASSWORD,
            "token":    TOTP_TOKEN,
            "pin":      PIN,
        }
    )
    resp.raise_for_status()
    body = resp.json()
    _parse_login_response(body)
    return {
        "success": True,
        "username": SESSION.username,
        "expires_in": SESSION.seconds_remaining(),
    }

def renew() -> dict:
    """POST to /api/auth/renew using the current token."""
    if not SESSION.token:
        return login()
    resp = _raw.post(
        SERVER_URL + "/api/auth/renew",
        data={},
        headers={"Authorization": f"Bearer {SESSION.token}"},
    )
    resp.raise_for_status()
    body = resp.json()
    _parse_login_response(body)
    return {
        "success": True,
        "username": SESSION.username,
        "expires_in": SESSION.seconds_remaining(),
    }
```

**Checkpoint:** calling `login()` with valid credentials returns a dict with `success: True` and `expires_in > 0`.

---

## Step 6 — `media_client.py`

Implement each function below.  All use `http_client.post()` or `http_client.get()`.

```python
import base64
import mimetypes
from http_client import post, get

def list_media(folder_id="", offset=0, limit=100, rating_limit=0,
               filter_text="", sorting="AZ") -> dict:
    body = post("/api/media/list", data={
        "folder_id":    folder_id,
        "offset":       str(offset),
        "limit":        str(limit),
        "rating":       str(rating_limit),
        "sort":         sorting,
        "filter_text":  filter_text,
        "required_tags": "",
        "hidden_tags":   "",
    })
    return {
        "info":    body.get("info", {}),
        "paging":  body.get("paging", {}),
        "folders": body.get("folders", []),
        "files":   body.get("files", []),
    }

def list_folders(folder_id="", **kwargs) -> list:
    return list_media(folder_id, **kwargs)["folders"]

def list_files(folder_id="", **kwargs) -> list:
    return list_media(folder_id, **kwargs)["files"]

def get_folder(folder_id: str) -> dict:
    body = post("/api/media/folder", data={"folder_id": folder_id})
    return body.get("info", {})

def get_file_meta(file_id: str) -> dict:
    body = post("/api/media/file", data={"file_id": file_id})
    return body.get("file", {})

def download_file(file_id: str) -> dict:
    meta = get_file_meta(file_id)
    resp = get("/api/media/view", params={"file_id": file_id})
    return {
        "file_id":        file_id,
        "filename":       meta.get("filename", ""),
        "mime_type":      meta.get("mime_type", ""),
        "size_bytes":     len(resp.content),
        "content_base64": base64.b64encode(resp.content).decode(),
    }

def upload_file(folder_id: str, filename: str, content_base64: str,
                mime_type: str = "application/octet-stream") -> dict:
    raw_bytes = base64.b64decode(content_base64)
    body = post(
        "/api/media/folder/upload/file",
        data={"folder_id": folder_id},
        files={"file": (filename, raw_bytes, mime_type)},
    )
    return {"success": True, "message": body.get("message", "")}

def migrate_file(file_id: str, target_storage: int) -> dict:
    force_archive = "true" if target_storage >= 1 else "false"
    body = post("/api/media/file/migrate", data={
        "file_id":       file_id,
        "force_archive": force_archive,
    })
    return {"success": True, "message": body.get("message", "")}

def get_preview(item_id: str, has_preview: bool) -> tuple:
    """Returns (raw_bytes, mime_type) or (None, None) when no preview exists."""
    if not has_preview:
        return None, None
    resp = get(f"/api/media/item/preview/{item_id}")
    mime_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    return resp.content, mime_type

def list_media_by_date(start_date: str, end_date: str, offset: int = 0,
                       limit: int = 200, rating_limit: int = 0,
                       sorting: str = "DA") -> dict:
    body = post("/api/media/list/by-date", data={
        "start_date": start_date,
        "end_date":   end_date,
        "offset":     str(offset),
        "limit":      str(limit),
        "rating":     str(rating_limit),
        "sort":       sorting,
    })
    folders = [{"type": "folder", **f} for f in body.get("folders", [])]
    files   = [{"type": "file",   **f} for f in body.get("files",   [])]
    return {
        "info":    body.get("info", {}),
        "paging":  body.get("paging", {}),
        "folders": folders,
        "files":   files,
    }
```

**Checkpoint:** `list_media("")` returns a dict with `folders` and `files` keys.

---

## Step 7 — `volume_client.py`

```python
import base64
import mimetypes
from http_client import post, get

def list_books(offset=0, limit=100, rating_limit=0, filter_text="",
               filter_tags="", sorting="AZ", filter_type="") -> dict:
    body = post("/api/volume/list/books", data={
        "offset":      str(offset),
        "limit":       str(limit),
        "rating":      str(rating_limit),
        "sort":        sorting,
        "filter_text": filter_text,
        "filter_type": filter_type,
        "filter_tags": filter_tags,
    })
    return {"books": body.get("books", []), "paging": body.get("paging", {})}

def get_book(book_id: str) -> dict:
    body = post("/api/volume/details", data={"book_id": book_id})
    return body.get("info", {})

def list_chapters(book_id: str) -> dict:
    body = post("/api/volume/list/chapters", data={"book_id": book_id})
    return {
        "name":     body.get("name", ""),
        "style":    body.get("style", ""),
        "info_url": body.get("info_url", ""),
        "chapters": body.get("chapters", []),
    }

def list_images(book_id: str, chapter_id: str) -> dict:
    body = post(
        "/api/volume/list/images?include_sizes=false",
        data={"book_id": book_id, "chapter_id": chapter_id},
    )
    return {
        "files": body.get("files", []),
        "prev":  body.get("prev", ""),
        "next":  body.get("next", ""),
        "style": body.get("style", ""),
    }

def get_image(book_id: str, chapter_id: str, filename: str) -> tuple:
    """Returns (raw_bytes, mime_type) — the MCP layer wraps this as ImageContent."""
    # Served via path-based endpoint; mime resolved from magic bytes
    # (server Content-Type can be wrong), then header, then extension.
    resp = get(f"/api/volume/serve_image/{book_id}/{chapter_id}/{filename}")
    return resp.content, detect_image_mime(resp.content, resp.headers.get("Content-Type", ""), filename)

def _update_book(book: dict) -> dict:
    """Send a full book update.  Caller must supply the complete book dict."""
    body = post("/api/volume/update", data={
        "id":            book["id"],
        "name":          book["name"],
        "processor":     book.get("processor", ""),
        "active":        "true" if book.get("active") else "false",
        "info_url":      book.get("info_url", ""),
        "rss_url":       book.get("rss_url", ""),
        "extra_url":     book.get("extra_url", ""),
        "start_chapter": book.get("start_chapter", ""),
        "skip":          book.get("skip", ""),
        "rating":        str(book.get("rating", 0)),
        "tags":          ",".join(book.get("tags", [])),
        "style":         book.get("style", "page"),
        "alt_name":      book.get("alt_name", ""),
    })
    return {"success": True, "message": body.get("message", "")}

def update_title(book_id: str, name: str) -> dict:
    book = get_book(book_id)
    book["name"] = name
    return _update_book(book)

def update_alt_name(book_id: str, alt_name: str) -> dict:
    book = get_book(book_id)
    book["alt_name"] = alt_name
    return _update_book(book)

def update_tags(book_id: str, tags: list) -> dict:
    book = get_book(book_id)
    book["tags"] = tags
    return _update_book(book)

def update_rating(book_id: str, rating: int) -> dict:
    book = get_book(book_id)
    book["rating"] = rating
    return _update_book(book)

def list_tags() -> dict:
    body = post("/api/volume/list/tags", data={})
    return {"tags": body.get("tags", [])}
```

**Checkpoint:** `list_books()` returns a dict with a `books` list.

---

## Step 7c — `process_client.py`

```python
from urllib.parse import quote
from http_client import post

_SEVERITY = {0: "TRACE", 10: "DEBUG", 20: "INFO", 30: "WARN",
             40: "ERROR", 50: "CRIT", 100: "LOG"}

def list_tasks(page: int = 0, page_size: int = 20,
               extra_method: str = "NONE") -> dict:
    body = post(
        f"/api/process/status/all/with/{quote(extra_method, safe='')}",
        data={"page": str(page), "page_size": str(page_size)},
    )
    return {
        "tasks":   body.get("tasks", []),
        "workers": body.get("workers", []),
        "page":    body.get("page", 0),
        "pages":   body.get("pages", 1),
        "total":   body.get("total", 0),
        "weight":  body.get("weight", 0),
    }

def get_status(task_id: int, log_page: int = 0, log_page_size: int = 0,
               include_files: bool = False) -> dict:
    data = {"include_files": "1" if include_files else "0"}
    if log_page_size > 0:
        data["log_page_size"] = str(log_page_size)
        data["log_page"]      = str(log_page)
    body = post(f"/api/process/status/{task_id}", data=data)
    return body.get("task", {})

def get_log(task_id: int, max_entries: int = 200) -> str:
    """Return log lines as a single formatted text block."""
    task = get_status(task_id, log_page=0, log_page_size=max_entries)
    lines = []
    for entry in task.get("log", []):
        label = _SEVERITY.get(entry.get("s", 100), "LOG")
        lines.append(f"[{label:<5}]  {entry.get('text', '')}")
    return "\n".join(lines) if lines else "(no log entries)"

def cancel_task(task_id: int) -> dict:
    body = post(f"/api/process/cancel/{task_id}", data={})
    return {"success": True, "message": body.get("message", "")}

def stop_server() -> dict:
    body = post("/api/process/stop", data={})
    return {"success": True, "message": body.get("message", "")}

def restart_server() -> dict:
    body = post("/api/process/restart", data={})
    return {"success": True, "message": body.get("message", "")}
```

**Checkpoint:** `list_tasks()` returns a dict with a `tasks` list.

---

## Step 7d — `plugin_client.py`

```python
import json
from http_client import post

def list_plugins() -> list:
    body = post("/api/plugin/list", data={})
    return body.get("plugins", [])

def list_plugins_ai() -> list:
    body = post("/api/plugin/list/ai", data={})
    return body.get("plugins", [])

def describe_plugin(plugin_id: str) -> dict:
    body = post("/api/plugin/describe", data={"plugin_id": plugin_id})
    return body.get("plugin", {})

def run_plugin(plugin_id: str, args: dict) -> dict:
    bundle = json.dumps({"id": plugin_id, "args": args})
    body = post("/api/process/add/plugin", data={"bundle": bundle})
    return {
        "success": True,
        "message": body.get("message", ""),
        "task_id": body.get("task_id"),
    }
```

**Checkpoint:** `list_plugins()` returns a list; each item has `id`, `name`, `category`, `args`.

---

## Step 7e — `scratch.py`

```python
import time
import uuid
import mimetypes
from pathlib import Path
from config import SCRATCH_PATH, SCRATCH_MAX_AGE_DAYS

def init_scratch() -> None:
    """Create scratch directory and purge files older than max_age_days."""
    SCRATCH_PATH.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - SCRATCH_MAX_AGE_DAYS * 86400
    for f in SCRATCH_PATH.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)

def scratch_path_for(file_id: str, mime_type: str) -> Path:
    """Return the expected scratch path for a given file_id and MIME type."""
    ext = mimetypes.guess_extension(mime_type) or ""
    ext = {".jpe": ".jpg", ".jpeg": ".jpg"}.get(ext, ext)
    return SCRATCH_PATH / f"{file_id}{ext}"

def get_scratch_path() -> Path:
    """Return the scratch directory path."""
    return SCRATCH_PATH

def create_scratch_file(mime_type: str = "", extension: str = "") -> Path:
    """Reserve an empty scratch file with a fresh UUID name and return its path."""
    if extension:
        ext = extension if extension.startswith(".") else f".{extension}"
    elif mime_type:
        ext = mimetypes.guess_extension(mime_type) or ""
        ext = {".jpe": ".jpg", ".jpeg": ".jpg"}.get(ext, ext)
    else:
        ext = ""
    path = SCRATCH_PATH / f"{uuid.uuid4()}{ext}"
    path.touch()
    return path
```

Call `init_scratch()` once at MCP server startup, before registering any tools.

`scratch_path_for` is used by `media_client.download_file` to determine the local path before and after streaming. If the file already exists at that path, the download is skipped.

**Checkpoint:** calling `init_scratch()` creates the directory; a stale test file older than `max_age_days` is removed.

---

## Step 7b — `cursor_store.py`

```python
import math
import uuid
from dataclasses import dataclass, field
import media_client
import volume_client

PAGE_SIZE  = 20
CHUNK_SIZE = 200

@dataclass
class Cursor:
    cursor_id:    str
    domain:       str        # "books" | "media"
    params:       dict       # frozen search params
    chunk:        list       # current fetched items
    chunk_offset: int        # server offset of chunk[0]
    page_index:   int        # current page within chunk (0-based)
    total:        int        # total items reported by server

CURSORS: dict[str, Cursor] = {}


def _fetch_chunk(cursor: Cursor, offset: int) -> None:
    """Re-fetch a chunk at the given server offset and update cursor state."""
    if cursor.domain == "books":
        result = volume_client.list_books(
            offset=offset, limit=CHUNK_SIZE, **cursor.params
        )
        cursor.chunk = result["books"]
        cursor.total = result["paging"]["total"]
    elif cursor.domain == "media_by_date":
        result = media_client.list_media_by_date(
            offset=offset, limit=CHUNK_SIZE, **cursor.params
        )
        cursor.chunk = result["folders"] + result["files"]
        cursor.total = result["paging"]["total"]
    else:  # "media"
        result = media_client.list_media(
            offset=offset, limit=CHUNK_SIZE, **cursor.params
        )
        folders = [{"type": "folder", **f} for f in result["folders"]]
        files   = [{"type": "file",   **f} for f in result["files"]]
        cursor.chunk = folders + files
        cursor.total = result["paging"]["total"]
    cursor.chunk_offset = offset
    cursor.page_index   = 0


def _make_response(cursor: Cursor) -> dict:
    start = cursor.page_index * PAGE_SIZE
    page_items = cursor.chunk[start : start + PAGE_SIZE]
    global_start = cursor.chunk_offset + start
    total_pages = math.ceil(cursor.total / PAGE_SIZE) if cursor.total > 0 else 1
    current_page = (global_start // PAGE_SIZE) + 1
    has_next = (global_start + len(page_items)) < cursor.total
    has_prev = global_start > 0
    return {
        "cursor_id":   cursor.cursor_id,
        "page":        current_page,
        "total_pages": total_pages,
        "total_items": cursor.total,
        "has_next":    has_next,
        "has_prev":    has_prev,
        "items":       page_items,
    }


def open_cursor(domain: str, params: dict) -> dict:
    cursor = Cursor(
        cursor_id=uuid.uuid4().hex,
        domain=domain,
        params=params,
        chunk=[],
        chunk_offset=0,
        page_index=0,
        total=0,
    )
    _fetch_chunk(cursor, offset=0)
    CURSORS[cursor.cursor_id] = cursor
    return _make_response(cursor)


def cursor_next(cursor_id: str) -> dict:
    cursor = CURSORS.get(cursor_id)
    if cursor is None:
        raise RuntimeError(f"Cursor not found: {cursor_id}")

    next_start = (cursor.page_index + 1) * PAGE_SIZE

    if next_start < len(cursor.chunk):
        # Still items left in the current chunk
        cursor.page_index += 1
        return _make_response(cursor)

    # Need more data from the server
    next_chunk_offset = cursor.chunk_offset + len(cursor.chunk)
    if next_chunk_offset >= cursor.total:
        return {"done": True, "cursor_id": cursor_id}

    _fetch_chunk(cursor, offset=next_chunk_offset)
    return _make_response(cursor)


def cursor_prev(cursor_id: str) -> dict:
    cursor = CURSORS.get(cursor_id)
    if cursor is None:
        raise RuntimeError(f"Cursor not found: {cursor_id}")

    if cursor.page_index > 0:
        cursor.page_index -= 1
        return _make_response(cursor)

    if cursor.chunk_offset == 0:
        return {"at_start": True, "cursor_id": cursor_id}

    # Load the previous chunk
    prev_offset = max(0, cursor.chunk_offset - CHUNK_SIZE)
    _fetch_chunk(cursor, offset=prev_offset)
    # Position at the last full page of the newly loaded chunk
    last_page = max(0, (len(cursor.chunk) - 1) // PAGE_SIZE)
    cursor.page_index = last_page
    return _make_response(cursor)


def cursor_close(cursor_id: str) -> dict:
    CURSORS.pop(cursor_id, None)
    return {"closed": True, "cursor_id": cursor_id}
```

**Checkpoint:** `open_cursor("books", {})` returns a dict with `items` (up to 20 entries) and a `cursor_id`.

This is the entry point.  It registers every tool and starts the stdio MCP loop.

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
import auth_client
import media_client
import volume_client
import process_client
import plugin_client
import cursor_store

app = Server("media-server-bridge")

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    match name:

        # Auth
        case "auth_login":
            return [types.TextContent(type="text", text=str(auth_client.login()))]

        case "auth_renew":
            return [types.TextContent(type="text", text=str(auth_client.renew()))]

        # Media
        case "media_list":
            result = media_client.list_media(
                folder_id=arguments.get("folder_id", ""),
                offset=int(arguments.get("offset", 0)),
                limit=int(arguments.get("limit", 100)),
                rating_limit=int(arguments.get("rating_limit", 0)),
                filter_text=arguments.get("filter_text", ""),
                sorting=arguments.get("sorting", "AZ"),
            )
            return [types.TextContent(type="text", text=str(result))]

        case "media_list_folders":
            result = media_client.list_folders(
                folder_id=arguments.get("folder_id", ""),
                offset=int(arguments.get("offset", 0)),
                limit=int(arguments.get("limit", 100)),
            )
            return [types.TextContent(type="text", text=str(result))]

        case "media_list_files":
            result = media_client.list_files(
                folder_id=arguments.get("folder_id", ""),
                offset=int(arguments.get("offset", 0)),
                limit=int(arguments.get("limit", 100)),
            )
            return [types.TextContent(type="text", text=str(result))]

        case "media_get_folder":
            result = media_client.get_folder(arguments["folder_id"])
            return [types.TextContent(type="text", text=str(result))]

        case "media_get_file":
            result = media_client.get_file_meta(arguments["file_id"])
            return [types.TextContent(type="text", text=str(result))]

        case "media_download_file":
            result = media_client.download_file(arguments["file_id"])
            return [types.TextContent(type="text", text=str(result))]

        case "media_upload_file":
            result = media_client.upload_file(
                folder_id=arguments["folder_id"],
                filename=arguments["filename"],
                content_base64=arguments["content_base64"],
                mime_type=arguments.get("mime_type", "application/octet-stream"),
            )
            return [types.TextContent(type="text", text=str(result))]

        case "media_migrate_file":
            result = media_client.migrate_file(
                file_id=arguments["file_id"],
                target_storage=int(arguments["target_storage"]),
            )
            return [types.TextContent(type="text", text=str(result))]

        case "media_get_preview":
            has_preview = bool(arguments["has_preview"])
            item_id     = arguments["item_id"]
            raw_bytes, mime_type = media_client.get_preview(item_id, has_preview)
            if raw_bytes is None:
                return [types.TextContent(type="text", text=str({"has_preview": False, "item_id": item_id}))]
            import base64 as _b64
            return [
                types.ImageContent(
                    type="image",
                    data=_b64.b64encode(raw_bytes).decode(),
                    mimeType=mime_type,
                ),
                types.TextContent(type="text", text=str({"item_id": item_id, "has_preview": True})),
            ]

        # Volume
        case "volume_list_books":
            result = volume_client.list_books(
                offset=int(arguments.get("offset", 0)),
                limit=int(arguments.get("limit", 100)),
                rating_limit=int(arguments.get("rating_limit", 0)),
                filter_text=arguments.get("filter_text", ""),
                filter_tags=arguments.get("filter_tags", ""),
                sorting=arguments.get("sorting", "AZ"),
                filter_type=arguments.get("filter_type", ""),
            )
            return [types.TextContent(type="text", text=str(result))]

        case "volume_get_book":
            result = volume_client.get_book(arguments["book_id"])
            return [types.TextContent(type="text", text=str(result))]

        case "volume_list_chapters":
            result = volume_client.list_chapters(arguments["book_id"])
            return [types.TextContent(type="text", text=str(result))]

        case "volume_list_images":
            result = volume_client.list_images(
                arguments["book_id"], arguments["chapter_id"]
            )
            return [types.TextContent(type="text", text=str(result))]

        case "volume_get_image":
            raw_bytes, mime_type = volume_client.get_image(
                arguments["book_id"],
                arguments["chapter_id"],
                arguments["filename"],
            )
            import base64 as _b64
            meta = {
                "book_id":    arguments["book_id"],
                "chapter_id": arguments["chapter_id"],
                "filename":   arguments["filename"],
            }
            return [
                types.ImageContent(
                    type="image",
                    data=_b64.b64encode(raw_bytes).decode(),
                    mimeType=mime_type,
                ),
                types.TextContent(type="text", text=str(meta)),
            ]

        case "volume_update_title":
            result = volume_client.update_title(arguments["book_id"], arguments["name"])
            return [types.TextContent(type="text", text=str(result))]

        case "volume_update_alt_name":
            result = volume_client.update_alt_name(
                arguments["book_id"], arguments["alt_name"]
            )
            return [types.TextContent(type="text", text=str(result))]

        case "volume_update_tags":
            tags = arguments["tags"]
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            result = volume_client.update_tags(arguments["book_id"], tags)
            return [types.TextContent(type="text", text=str(result))]

        case "volume_update_rating":
            result = volume_client.update_rating(
                arguments["book_id"], int(arguments["rating"])
            )
            return [types.TextContent(type="text", text=str(result))]

        case "volume_list_tags":
            result = volume_client.list_tags()
            return [types.TextContent(type="text", text=str(result))]

        # Process
        case "process_list":
            result = process_client.list_tasks(
                page=int(arguments.get("page", 0)),
                page_size=int(arguments.get("page_size", 20)),
                extra_method=arguments.get("extra_method", "NONE"),
            )
            return [types.TextContent(type="text", text=str(result))]

        case "process_get_status":
            result = process_client.get_status(
                task_id=int(arguments["task_id"]),
                log_page=int(arguments.get("log_page", 0)),
                log_page_size=int(arguments.get("log_page_size", 0)),
                include_files=bool(arguments.get("include_files", False)),
            )
            return [types.TextContent(type="text", text=str(result))]

        case "process_get_log":
            text = process_client.get_log(
                task_id=int(arguments["task_id"]),
                max_entries=int(arguments.get("max_entries", 200)),
            )
            return [types.TextContent(type="text", text=text)]

        case "process_cancel":
            result = process_client.cancel_task(int(arguments["task_id"]))
            return [types.TextContent(type="text", text=str(result))]

        case "process_stop_server":
            result = process_client.stop_server()
            return [types.TextContent(type="text", text=str(result))]

        case "process_restart_server":
            result = process_client.restart_server()
            return [types.TextContent(type="text", text=str(result))]

        # Plugins
        case "plugin_list":
            result = plugin_client.list_plugins()
            return [types.TextContent(type="text", text=str(result))]

        case "plugin_run":
            args = arguments.get("args", {})
            if not isinstance(args, dict):
                args = {}
            result = plugin_client.run_plugin(
                plugin_id=arguments["plugin_id"],
                args=args,
            )
            return [types.TextContent(type="text", text=str(result))]

        # Pagination / search cursors
        case "search_books":
            params = {
                "rating_limit": int(arguments.get("rating_limit", 0)),
                "filter_text":  arguments.get("filter_text", ""),
                "filter_tags":  arguments.get("filter_tags", ""),
                "sorting":      arguments.get("sorting", "AZ"),
                "filter_type":  arguments.get("filter_type", ""),
            }
            result = cursor_store.open_cursor("books", params)
            return [types.TextContent(type="text", text=str(result))]

        case "search_media":
            params = {
                "folder_id":    arguments.get("folder_id", ""),
                "rating_limit": int(arguments.get("rating_limit", 0)),
                "filter_text":  arguments.get("filter_text", ""),
                "sorting":      arguments.get("sorting", "AZ"),
            }
            result = cursor_store.open_cursor("media", params)
            return [types.TextContent(type="text", text=str(result))]

        case "search_media_by_date":
            params = {
                "start_date":   arguments["start_date"],
                "end_date":     arguments["end_date"],
                "rating_limit": int(arguments.get("rating_limit", 0)),
                "sorting":      arguments.get("sorting", "DA"),
            }
            result = cursor_store.open_cursor("media_by_date", params)
            return [types.TextContent(type="text", text=str(result))]

        case "cursor_next":
            result = cursor_store.cursor_next(arguments["cursor_id"])
            return [types.TextContent(type="text", text=str(result))]

        case "cursor_prev":
            result = cursor_store.cursor_prev(arguments["cursor_id"])
            return [types.TextContent(type="text", text=str(result))]

        case "cursor_close":
            result = cursor_store.cursor_close(arguments["cursor_id"])
            return [types.TextContent(type="text", text=str(result))]

        case _:
            raise ValueError(f"Unknown tool: {name}")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(name="auth_login",           description="Authenticate with the media server using stored credentials.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="auth_renew",            description="Renew the current auth token.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="media_list",            description="List folders and files in a media folder.", inputSchema={"type":"object","properties":{"folder_id":{"type":"string"},"offset":{"type":"integer"},"limit":{"type":"integer"},"rating_limit":{"type":"integer"},"filter_text":{"type":"string"},"sorting":{"type":"string"}}}),
        types.Tool(name="media_list_folders",    description="List only subfolders in a media folder.", inputSchema={"type":"object","properties":{"folder_id":{"type":"string"},"offset":{"type":"integer"},"limit":{"type":"integer"}}}),
        types.Tool(name="media_list_files",      description="List only files in a media folder.", inputSchema={"type":"object","properties":{"folder_id":{"type":"string"},"offset":{"type":"integer"},"limit":{"type":"integer"}}}),
        types.Tool(name="media_get_folder",      description="Get details for a media folder.", inputSchema={"type":"object","properties":{"folder_id":{"type":"string"}},"required":["folder_id"]}),
        types.Tool(name="media_get_file",        description="Get metadata for a media file.", inputSchema={"type":"object","properties":{"file_id":{"type":"string"}},"required":["file_id"]}),
        types.Tool(name="media_download_file",   description="Download a media file; returns base64 content.", inputSchema={"type":"object","properties":{"file_id":{"type":"string"}},"required":["file_id"]}),
        types.Tool(name="media_upload_file",     description="Upload a file to a media folder.", inputSchema={"type":"object","properties":{"folder_id":{"type":"string"},"filename":{"type":"string"},"content_base64":{"type":"string"},"mime_type":{"type":"string"}},"required":["folder_id","filename","content_base64"]}),
        types.Tool(name="media_migrate_file",    description="Move a file between storage tiers. target_storage: 0=primary, 1=archive.", inputSchema={"type":"object","properties":{"file_id":{"type":"string"},"target_storage":{"type":"integer","enum":[0,1]}},"required":["file_id","target_storage"]}),
        types.Tool(name="media_get_preview",     description="Get the preview image for a folder or file. Pass has_preview from item metadata; returns ImageContent or a no-preview marker.", inputSchema={"type":"object","properties":{"item_id":{"type":"string"},"has_preview":{"type":"boolean"}},"required":["item_id","has_preview"]}),
        types.Tool(name="volume_list_books",     description="List books (volumes) with optional filters.", inputSchema={"type":"object","properties":{"offset":{"type":"integer"},"limit":{"type":"integer"},"rating_limit":{"type":"integer"},"filter_text":{"type":"string"},"filter_tags":{"type":"string"},"sorting":{"type":"string"},"filter_type":{"type":"string"}}}),
        types.Tool(name="volume_get_book",       description="Get full details for a single book.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"}},"required":["book_id"]}),
        types.Tool(name="volume_list_chapters",  description="List all chapters for a book.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"}},"required":["book_id"]}),
        types.Tool(name="volume_list_images",    description="List image filenames in a book chapter.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"chapter_id":{"type":"string"}},"required":["book_id","chapter_id"]}),
        types.Tool(name="volume_get_image",      description="Retrieve a single chapter image by filename; returns base64 content.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"chapter_id":{"type":"string"},"filename":{"type":"string"}},"required":["book_id","chapter_id","filename"]}),
        types.Tool(name="volume_update_title",   description="Update a book's display title.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"name":{"type":"string"}},"required":["book_id","name"]}),
        types.Tool(name="volume_update_alt_name",description="Update a book's alternative name.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"alt_name":{"type":"string"}},"required":["book_id","alt_name"]}),
        types.Tool(name="volume_update_tags",    description="Replace a book's tags list.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}}},"required":["book_id","tags"]}),
        types.Tool(name="volume_update_rating",  description="Update a book's rating.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"rating":{"type":"integer"}},"required":["book_id","rating"]}),
        types.Tool(name="volume_list_tags",      description="List all available book tags.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="process_list",          description="List all tasks (queued, running, finished) and worker status.", inputSchema={"type":"object","properties":{"page":{"type":"integer"},"page_size":{"type":"integer"},"extra_method":{"type":"string"}}}),
        types.Tool(name="process_get_status",    description="Get full status and optional log for a single task. Poll this to track progress.", inputSchema={"type":"object","properties":{"task_id":{"type":"integer"},"log_page":{"type":"integer"},"log_page_size":{"type":"integer"},"include_files":{"type":"boolean"}},"required":["task_id"]}),
        types.Tool(name="process_get_log",       description="Return the log of a task as formatted text. Use after task completes.", inputSchema={"type":"object","properties":{"task_id":{"type":"integer"},"max_entries":{"type":"integer"}},"required":["task_id"]}),
        types.Tool(name="process_cancel",        description="Cancel a queued or running task.", inputSchema={"type":"object","properties":{"task_id":{"type":"integer"}},"required":["task_id"]}),
        types.Tool(name="process_stop_server",   description="DANGEROUS: stop the background worker process. All tasks halt. Only call when explicitly requested by the user.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="process_restart_server",description="DANGEROUS: restart the background worker process. Running tasks are interrupted. Only call when explicitly requested by the user.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="plugin_list",           description="List all available plugins with their argument definitions.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="plugin_run",            description="Run a plugin by id, passing args as a flat dict. Returns task_id for tracking via process tools.", inputSchema={"type":"object","properties":{"plugin_id":{"type":"string"},"args":{"type":"object"}},"required":["plugin_id"]}),
        types.Tool(name="search_books",          description="Open a paginated search cursor over books. Returns first page of 20 plus a cursor_id.", inputSchema={"type":"object","properties":{"filter_text":{"type":"string"},"filter_tags":{"type":"string"},"rating_limit":{"type":"integer"},"sorting":{"type":"string"},"filter_type":{"type":"string"}}}),
        types.Tool(name="search_media",          description="Open a paginated search cursor over media folders/files. Returns first page of 20 plus a cursor_id.", inputSchema={"type":"object","properties":{"folder_id":{"type":"string"},"filter_text":{"type":"string"},"rating_limit":{"type":"integer"},"sorting":{"type":"string"}}}),
        types.Tool(name="search_media_by_date",  description="Open a paginated cursor over media files created within a date range (YYYY-MM-DD). Default sort is newest first.", inputSchema={"type":"object","properties":{"start_date":{"type":"string"},"end_date":{"type":"string"},"rating_limit":{"type":"integer"},"sorting":{"type":"string"}},"required":["start_date","end_date"]}),
        types.Tool(name="cursor_next",           description="Advance a search cursor by one page (20 items). Fetches next server chunk automatically when needed.", inputSchema={"type":"object","properties":{"cursor_id":{"type":"string"}},"required":["cursor_id"]}),
        types.Tool(name="cursor_prev",           description="Move a search cursor back one page.", inputSchema={"type":"object","properties":{"cursor_id":{"type":"string"}},"required":["cursor_id"]}),
        types.Tool(name="cursor_close",          description="Release a search cursor and free its memory.", inputSchema={"type":"object","properties":{"cursor_id":{"type":"string"}},"required":["cursor_id"]}),
    ]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

**Checkpoint:** `python mcp_server.py` starts without error and waits on stdin.

---

## Step 9 — Wire up to Claude Desktop (or any MCP client)

Add an entry to the MCP client config (e.g. `claude_desktop_config.json`).  
All connection and credential settings live in `config.json` — no env vars needed here.

```json
{
  "mcpServers": {
    "media-server-bridge": {
      "command": "python",
      "args": ["C:/path/to/mcp_media_server/mcp_server.py"]
    }
  }
}
```

Ensure `config.json` is present in the same directory as `mcp_server.py` before starting the client.
```

**Checkpoint:** the MCP client lists all 19 tools when it starts.

---

## Step 10 — Smoke-test sequence

Run these tool calls in order via the MCP client:

1. `auth_login` → should return `success: True`
2. `volume_list_books` with `limit=5` → should return up to 5 books
3. Pick a `book_id`, call `volume_get_book` → should return full details
4. Call `volume_list_chapters` with that `book_id` → should return chapters list
5. Pick a `chapter_id`, call `volume_list_images` → should return filenames
6. Pick a `filename`, call `volume_get_image` → should return `content_base64`
7. `media_list` with empty `folder_id` → should return root folders/files
8. `media_list_folders` on the root → only folders returned
9. `volume_list_tags` → list of tag strings
10. `volume_update_title` with a book_id and new name → `success: True`, verify with `volume_get_book`
11. `search_books` with no params → `cursor_id` + first 20 books, `total_items` > 0
12. `cursor_next` with that cursor_id → next 20 books, `page` incremented
13. `cursor_prev` → back to page 1
14. `cursor_close` → `{ "closed": true }`
15. `search_media` on root folder → `cursor_id` + mixed folders/files with `type` field

---

## Notes for the implementing AI

- **Never hard-code credentials** — always read from environment variables via `config.py`
- **Do not add threading** — the server is single-instance, single-thread; `requests.Session` is reused across calls
- **Token storage** — the `SESSION` singleton in `session.py` lives in memory for the process lifetime; it is not persisted to disk
- **Circular import** — `http_client.py` imports `login` lazily (inside the function) to avoid the `auth_client → http_client → auth_client` cycle
- **Base64 for binary** — all binary responses (images, file downloads) are base64-encoded before being placed in the MCP text result so the JSON transport stays clean
- **Error surfacing** — never swallow exceptions silently; always let them propagate so the MCP framework can return them as tool errors to the AI caller
