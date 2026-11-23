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

Single active search, item-level stepping. `search()` fetches a window of up
to `CHUNK_SIZE` (200) items and replaces any previous cursor. `cursor_next` /
`cursor_prev` move one item at a time; when the window runs out they return a
sentinel carrying the `offset` the agent needs to re-issue the same search.
The server never re-fetches automatically.

Two single-active **list cursors** sit below the search cursor: the chapter
cursor (type `"c"`) and the image cursor (type `"i"`). `volume_list_chapters`
and `volume_list_images` open them (full list fetched on open, cursor pointed
at the first entry) and `chapter_next`/`chapter_prev` and `image_next`/
`image_prev` step them. The whole list is fetched on open, so there is no
offset/resume — only `exhausted`/`at_start` sentinels. Opening a new search
or `cursor_close()` drops the active list cursor.

```python
import uuid
from dataclasses import dataclass, field

CHUNK_SIZE = 200  # items fetched from the backend per HTTP request

STATUS_EXHAUSTED    = "exhausted"
STATUS_WINDOW_START = "window_start"
STATUS_AT_START     = "at_start"

@dataclass
class Cursor:
    cursor_id: str
    type:      str        # "v" | "m" | "md"
    params:    dict       # original search parameters (frozen after open)
    items:     list = field(default_factory=list)  # current fetched window
    offset:    int = 0    # server offset of items[0]
    index:     int = 0    # 0-based position within items[]
    total:     int = 0    # total items on the server

# Module-level singleton: only ONE active cursor
ACTIVE: Cursor | None = None


def _fetch(type: str, params: dict, offset: int, limit: int):
    """Return (items, total) fetched from the backend for this search type."""
    from mcp_server import _client  # shared MediaServerClient instance
    if type == "v":
        body = _client.books.list_books(
            offset=offset, limit=limit,
            filter_text=params.get("filter_text", ""),
            filter_tags=params.get("filter_tags", ""),
            rating_limit=params.get("rating_limit", 0),
            sorting=params.get("sorting", "AZ"),
            filter_type=params.get("filter_type", ""),
        )
        return body.get("books", []), int(body.get("paging", {}).get("total", 0))
    if type in ("m", "md"):
        if type == "m":
            body = _client.media.list_media(
                folder_id=params.get("folder_id", ""),
                offset=offset, limit=limit,
                rating_limit=params.get("rating_limit", 0),
                sorting=params.get("sorting", "AZ"),
                filter_text=params.get("filter_text", ""),
            )
        else:
            body = _client.media.list_media_by_date(
                start_date=params.get("start_date", ""),
                end_date=params.get("end_date", ""),
                offset=offset, limit=limit,
                rating_limit=params.get("rating_limit", 0),
                sorting=params.get("sorting", "DA"),
            )
        items = [{"type": "folder", **f} for f in body.get("folders", [])]
        items += [{"type": "file", **f} for f in body.get("files", [])]
        return items, int(body.get("paging", {}).get("total", 0))
    raise ValueError(f"Unknown cursor type: {type}")


def _fetch_window(c: Cursor, offset: int) -> None:
    items, total = _fetch(c.type, c.params, offset, CHUNK_SIZE)
    c.items  = items
    c.offset = offset
    c.index  = 0
    c.total  = total


def _envelope(c: Cursor) -> dict:
    """Normal envelope: the item the cursor is pointing at."""
    return {
        "cursor_id": c.cursor_id,
        "type":      c.type,
        "index":     c.index,
        "content":   c.items[c.index] if c.items else None,
        "total":     c.total,
    }


def _sentinel(c: Cursor, status: str, offset: int | None = None) -> dict:
    """Sentinel envelope: no current item, plus the offset needed to continue."""
    return {
        "cursor_id": c.cursor_id,
        "type":      c.type,
        "index":     c.index,
        "content":   None,
        "offset":    c.offset + len(c.items) if offset is None else offset,
        "total":     c.total,
        "status":    status,
    }


def search(type: str, params: dict, offset: int = 0) -> dict:
    """Open a new search and replace any previous cursor.

    Also discards any active chapter/image cursor. Returns the first item
    of the fetch window, or an exhausted sentinel when the search has no
    results.
    """
    global ACTIVE, ACTIVE_LIST
    c = Cursor(cursor_id=str(uuid.uuid4()), type=type, params=dict(params))
    _fetch_window(c, offset)
    ACTIVE = c
    ACTIVE_LIST = None
    if c.items:
        return _envelope(c)
    return _sentinel(c, STATUS_EXHAUSTED)


def _active() -> Cursor:
    if ACTIVE is None:
        raise RuntimeError("No active search — call search_books or search_media first")
    return ACTIVE


def cursor_info() -> dict:
    """Describe the active cursor without moving it (no network call)."""
    c = _active()
    return {
        "cursor_id": c.cursor_id,
        "type":      c.type,
        "index":     c.index,
        "content":   c.items[c.index] if c.items else None,
        "offset":    c.offset,
        "fetched":   len(c.items),
        "total":     c.total,
    }


def cursor_next() -> dict:
    """Advance one item. Sentinel at the end of the fetched window."""
    c = _active()
    if c.index + 1 < len(c.items):
        c.index += 1
        return _envelope(c)
    return _sentinel(c, STATUS_EXHAUSTED)


def cursor_prev() -> dict:
    """Move back one item. Sentinel at the start of the fetched window."""
    c = _active()
    if c.index > 0:
        c.index -= 1
        return _envelope(c)
    if c.offset > 0:
        return _sentinel(c, STATUS_WINDOW_START, offset=c.offset - CHUNK_SIZE)
    return _sentinel(c, STATUS_AT_START)


def cursor_close() -> dict:
    """Discard the active search and any active list cursor."""
    global ACTIVE, ACTIVE_LIST
    if ACTIVE is None and ACTIVE_LIST is None:
        return {"closed": False}
    ACTIVE = None
    ACTIVE_LIST = None
    return {"closed": True}
```

**List cursors** (appended to the same module):

```python
@dataclass
class ListCursor:
    """Single-active cursor over a fully fetched list: the chapters of one
    book (type "c") or the image files of one chapter (type "i")."""
    cursor_id: str
    type: str            # "c" | "i"
    book_id: str
    chapter_id: str | None   # None on a chapter cursor
    items: list          # full list, fetched on open
    index: int = 0       # 0-based position within items[]

# Module-level singleton: only ONE active list cursor
ACTIVE_LIST: ListCursor | None = None


def _list_active() -> ListCursor:
    if ACTIVE_LIST is None:
        raise RuntimeError(
            "No active chapter/image cursor — call volume_list_chapters or "
            "volume_list_images first")
    return ACTIVE_LIST


def _list_envelope(c: ListCursor) -> dict:
    """Normal envelope: the item the list cursor is pointing at."""
    return {
        "cursor_id":  c.cursor_id,
        "type":       c.type,
        "book_id":    c.book_id,
        "chapter_id": c.chapter_id,
        "index":      c.index,
        "content":    c.items[c.index],
        "total":      len(c.items),
    }


def _list_sentinel(c: ListCursor, status: str) -> dict:
    """Sentinel envelope: no current item on a fully fetched list."""
    return {
        "cursor_id":  c.cursor_id,
        "type":       c.type,
        "book_id":    c.book_id,
        "chapter_id": c.chapter_id,
        "index":      c.index,
        "content":    None,
        "total":      len(c.items),
        "status":     status,
    }


def open_list_cursor(type: str, book_id: str, chapter_id: str | None,
                     items: list) -> dict:
    """Point the list cursor at items (fetched by the caller) and replace
    any previous list cursor. Returns the first item's envelope, or an
    exhausted sentinel when the list is empty."""
    global ACTIVE_LIST
    ACTIVE_LIST = ListCursor(cursor_id=str(uuid.uuid4()), type=type,
                             book_id=book_id, chapter_id=chapter_id,
                             items=list(items))
    c = ACTIVE_LIST
    if c.items:
        return _list_envelope(c)
    return _list_sentinel(c, STATUS_EXHAUSTED)


def current_chapter_id() -> str:
    """Chapter id from the active list cursor (for param fallback): the
    chapter the chapter cursor points at, or the chapter an image cursor is
    scoped to (opening the image cursor replaces the chapter cursor)."""
    c = _list_active()
    if c.type == "c":
        return c.items[c.index]["value"]
    if c.type == "i":
        return c.chapter_id
    raise RuntimeError("No active chapter/image cursor — call volume_list_chapters first")


def current_image_filename() -> str:
    """Filename the image cursor points at (for param fallback)."""
    c = _list_active()
    if c.type != "i":
        raise RuntimeError("No active image cursor — call volume_list_images first")
    return c.items[c.index]


def list_info() -> dict:
    """Describe the active list cursor without moving it (no network call)."""
    c = _list_active()
    return {
        "cursor_id":  c.cursor_id,
        "type":       c.type,
        "book_id":    c.book_id,
        "chapter_id": c.chapter_id,
        "index":      c.index,
        "content":    c.items[c.index] if c.items else None,
        "total":      len(c.items),
    }


def list_next() -> dict:
    """Advance the list cursor one item; exhausted sentinel at the end."""
    c = _list_active()
    if c.index + 1 < len(c.items):
        c.index += 1
        return _list_envelope(c)
    return _list_sentinel(c, STATUS_EXHAUSTED)


def list_prev() -> dict:
    """Move the list cursor back one item; at_start sentinel on item 0."""
    c = _list_active()
    if c.index > 0:
        c.index -= 1
        return _list_envelope(c)
    return _list_sentinel(c, STATUS_AT_START)


def list_close() -> dict:
    """Discard the active list cursor (the search cursor is untouched)."""
    global ACTIVE_LIST
    if ACTIVE_LIST is None:
        return {"closed": False}
    ACTIVE_LIST = None
    return {"closed": True}
```

`search()` and `cursor_close()` above also set `ACTIVE_LIST = None` so the
book → chapter → image stack stays coherent when the book changes.

**Checkpoint:** `search("v", {})` returns `{ cursor_id, type: "v", index: 0, content, total }`; `cursor_next()` with no arguments advances one item; past the last fetched item it returns `{ status: "exhausted", offset, total }`.

**Volume cursor fallback:** in `mcp_server.py` the volume get/update tools take
`book_id: str = ""` and resolve it through `_book_id_from_cursor()` — the
argument wins, otherwise the active cursor's current item is used, otherwise a
`RuntimeError` is raised. `search_media` / `search_media_by_date` search types
(`"m"`, `"md"`) never satisfy the fallback (only `type == "v"` does).

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

        # --- Volume cursor fallback: book_id optional; the active search
        # cursor's current item is used when the argument is omitted ---

        def _book_id_from_cursor(book_id: str | None) -> str:
            if book_id:
                return book_id
            c = cursor_store.ACTIVE
            if c is not None and c.type == "v" and c.items:
                return c.items[c.index]["id"]
            raise RuntimeError(
                "No book_id given and no active book search pointing at a book — "
                "pass book_id or run search_books first")

        # --- List-cursor fallbacks: chapter_id / filename optional; the
        # active chapter/image cursor's current item is used when omitted ---

        def _chapter_id_from_cursor(chapter_id: str | None) -> str:
            if chapter_id:
                return chapter_id
            return cursor_store.current_chapter_id()

        def _filename_from_cursor(filename: str | None) -> str:
            if filename:
                return filename
            return cursor_store.current_image_filename()

        def _book_field_from_cursor(field: str, book_id: str | None):
            # One-horse-pony getters: fetch the book, return one field
            book = volume_client.get_book(_book_id_from_cursor(book_id))
            return book.get(field)

        case "volume_get_book":
            result = volume_client.get_book(_book_id_from_cursor(arguments.get("book_id", "")))
            return [types.TextContent(type="text", text=str(result))]

        case "volume_get_name":
            result = _book_field_from_cursor("name", arguments.get("book_id", ""))
            return [types.TextContent(type="text", text=str(result))]

        case "volume_get_alt_name":
            result = _book_field_from_cursor("alt_name", arguments.get("book_id", ""))
            return [types.TextContent(type="text", text=str(result))]

        case "volume_get_style":
            result = _book_field_from_cursor("style", arguments.get("book_id", ""))
            return [types.TextContent(type="text", text=str(result))]

        case "volume_get_tags":
            tags = _book_field_from_cursor("tags", arguments.get("book_id", ""))
            result = json.dumps(tags if tags is not None else [])
            return [types.TextContent(type="text", text=result)]

        case "volume_get_rating":
            result = _book_field_from_cursor("rating", arguments.get("book_id", ""))
            return [types.TextContent(type="text", text=str(result))]

        case "volume_get_active":
            result = _book_field_from_cursor("active", arguments.get("book_id", ""))
            return [types.TextContent(type="text", text=str(result))]

        case "volume_list_chapters":
            book_id = _book_id_from_cursor(arguments.get("book_id", ""))
            body = volume_client.list_chapters(book_id)
            # Side effect: point the chapter cursor at the first chapter
            cursor_store.open_list_cursor("c", book_id, None, body.get("chapters", []))
            result = body
            return [types.TextContent(type="text", text=str(result))]

        case "volume_list_images":
            book_id   = _book_id_from_cursor(arguments.get("book_id", ""))
            chapter_id = _chapter_id_from_cursor(arguments.get("chapter_id", ""))
            body = volume_client.list_images(book_id, chapter_id)
            # Side effect: point the image cursor at the first file
            cursor_store.open_list_cursor("i", book_id, chapter_id, body.get("files", []))
            result = body
            return [types.TextContent(type="text", text=str(result))]

        case "volume_get_image":
            book_id   = _book_id_from_cursor(arguments.get("book_id", ""))
            chapter_id = _chapter_id_from_cursor(arguments.get("chapter_id", ""))
            filename   = _filename_from_cursor(arguments.get("filename", ""))
            raw_bytes, mime_type = volume_client.get_image(
                book_id, chapter_id, filename,
            )
            import base64 as _b64
            meta = {
                "book_id":    book_id,
                "chapter_id": chapter_id,
                "filename":   filename,
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
            result = volume_client.update_title(
                _book_id_from_cursor(arguments.get("book_id", "")), arguments["name"])
            return [types.TextContent(type="text", text=str(result))]

        case "volume_update_alt_name":
            result = volume_client.update_alt_name(
                _book_id_from_cursor(arguments.get("book_id", "")), arguments["alt_name"]
            )
            return [types.TextContent(type="text", text=str(result))]

        case "volume_update_tags":
            tags = arguments["tags"]
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            result = volume_client.update_tags(
                _book_id_from_cursor(arguments.get("book_id", "")), tags)
            return [types.TextContent(type="text", text=str(result))]

        case "volume_update_rating":
            result = volume_client.update_rating(
                _book_id_from_cursor(arguments.get("book_id", "")), int(arguments["rating"])
            )
            return [types.TextContent(type="text", text=str(result))]

        case "volume_update_style":
            result = volume_client.update_style(
                _book_id_from_cursor(arguments.get("book_id", "")), arguments["style"]
            )
            return [types.TextContent(type="text", text=str(result))]

        case "volume_update_book":
            tags = arguments["tags"]
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            # All fields except book_id are required — a full book definition
            # must be passed back (fetch first via volume_get_book).
            result = volume_client.update_book(
                _book_id_from_cursor(arguments.get("book_id", "")),
                arguments["name"], arguments["alt_name"],
                int(arguments["rating"]), tags, bool(arguments["active"]),
                arguments["info_url"], arguments["rss_url"],
                arguments["extra_url"], arguments["start_chapter"],
                arguments["skip"], arguments["style"],
                arguments["processor"],
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

        # Search cursors (item-level, single active search)
        case "search_books":
            params = {
                "rating_limit": int(arguments.get("rating_limit", 0)),
                "filter_text":  arguments.get("filter_text", ""),
                "filter_tags":  arguments.get("filter_tags", ""),
                "sorting":      arguments.get("sorting", "AZ"),
                "filter_type":  arguments.get("filter_type", ""),
            }
            result = cursor_store.search("v", params, offset=int(arguments.get("offset", 0)))
            return [types.TextContent(type="text", text=str(result))]

        case "search_media":
            params = {
                "folder_id":    arguments.get("folder_id", ""),
                "rating_limit": int(arguments.get("rating_limit", 0)),
                "filter_text":  arguments.get("filter_text", ""),
                "sorting":      arguments.get("sorting", "AZ"),
            }
            result = cursor_store.search("m", params, offset=int(arguments.get("offset", 0)))
            return [types.TextContent(type="text", text=str(result))]

        case "search_media_by_date":
            params = {
                "start_date":   arguments["start_date"],
                "end_date":     arguments["end_date"],
                "rating_limit": int(arguments.get("rating_limit", 0)),
                "sorting":      arguments.get("sorting", "DA"),
            }
            result = cursor_store.search("md", params, offset=int(arguments.get("offset", 0)))
            return [types.TextContent(type="text", text=str(result))]

        case "cursor_info":
            result = cursor_store.cursor_info()
            return [types.TextContent(type="text", text=str(result))]

        case "cursor_next":
            result = cursor_store.cursor_next()
            return [types.TextContent(type="text", text=str(result))]

        case "cursor_prev":
            result = cursor_store.cursor_prev()
            return [types.TextContent(type="text", text=str(result))]

        case "cursor_close":
            result = cursor_store.cursor_close()
            return [types.TextContent(type="text", text=str(result))]

        # Chapter/image list cursors (single active, full list on open)
        case "chapter_next":
            result = cursor_store.list_next()
            return [types.TextContent(type="text", text=str(result))]

        case "chapter_prev":
            result = cursor_store.list_prev()
            return [types.TextContent(type="text", text=str(result))]

        case "image_next":
            result = cursor_store.list_next()
            return [types.TextContent(type="text", text=str(result))]

        case "image_prev":
            result = cursor_store.list_prev()
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
        types.Tool(name="volume_get_book",       description="Get full details for a single book. book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"}}}),
        types.Tool(name="volume_get_name",       description="Get just the book's title. book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"}}}),
        types.Tool(name="volume_get_alt_name",   description="Get just the book's alternative name. book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"}}}),
        types.Tool(name="volume_get_style",      description="Get just the book's layout style (\"page\" or \"scroll\"). book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"}}}),
        types.Tool(name="volume_get_tags",       description="Get just the book's tag list as a JSON array of strings (e.g. [\"MC:A\", \"x\"]; \"[]\" when empty). book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"}}}),
        types.Tool(name="volume_get_rating",     description="Get just the book's rating. book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"}}}),
        types.Tool(name="volume_get_active",     description="Get just the book's active flag. book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"}}}),
        types.Tool(name="volume_list_chapters",  description="List all chapters for a book and point the chapter cursor at the first one. book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"}}}),
        types.Tool(name="volume_list_images",    description="List image filenames in a book chapter and point the image cursor at the first one. chapter_id optional — defaults to the chapter the active chapter/image cursor points at; book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"chapter_id":{"type":"string"}}}),
        types.Tool(name="volume_get_image",      description="Retrieve a single chapter image; returns image content. chapter_id optional — defaults to the active chapter/image cursor; filename optional — defaults to the active image cursor; book_id optional — defaults to the active search cursor.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"chapter_id":{"type":"string"},"filename":{"type":"string"}}}),
        types.Tool(name="volume_update_title",   description="Update a book's display title. book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"name":{"type":"string"}},"required":["name"]}),
        types.Tool(name="volume_update_alt_name",description="Update a book's alternative name. book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"alt_name":{"type":"string"}},"required":["alt_name"]}),
        types.Tool(name="volume_update_tags",    description="Replace a book's tags list. book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}}},"required":["tags"]}),
        types.Tool(name="volume_update_rating",  description="Update a book's rating. book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"rating":{"type":"integer"}},"required":["rating"]}),
        types.Tool(name="volume_update_style",   description="Update a book's display style (\"page\" or \"scroll\"). book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"style":{"type":"string"}},"required":["style"]}),
        types.Tool(name="volume_update_book",    description="Update all editable fields of a book at once. All fields except book_id are required; pass a full definition from volume_get_book. book_id optional — defaults to the book the active search cursor points at.", inputSchema={"type":"object","properties":{"book_id":{"type":"string"},"name":{"type":"string"},"alt_name":{"type":"string"},"rating":{"type":"integer"},"tags":{"type":"array","items":{"type":"string"}},"active":{"type":"boolean"},"info_url":{"type":"string"},"rss_url":{"type":"string"},"extra_url":{"type":"string"},"start_chapter":{"type":"string"},"skip":{"type":"string"},"style":{"type":"string"},"processor":{"type":"string"}},"required":["name","alt_name","rating","tags","active","info_url","rss_url","extra_url","start_chapter","skip","style","processor"]}),
        types.Tool(name="volume_list_tags",      description="List all available book tags.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="process_list",          description="List all tasks (queued, running, finished) and worker status.", inputSchema={"type":"object","properties":{"page":{"type":"integer"},"page_size":{"type":"integer"},"extra_method":{"type":"string"}}}),
        types.Tool(name="process_get_status",    description="Get full status and optional log for a single task. Poll this to track progress.", inputSchema={"type":"object","properties":{"task_id":{"type":"integer"},"log_page":{"type":"integer"},"log_page_size":{"type":"integer"},"include_files":{"type":"boolean"}},"required":["task_id"]}),
        types.Tool(name="process_get_log",       description="Return the log of a task as formatted text. Use after task completes.", inputSchema={"type":"object","properties":{"task_id":{"type":"integer"},"max_entries":{"type":"integer"}},"required":["task_id"]}),
        types.Tool(name="process_cancel",        description="Cancel a queued or running task.", inputSchema={"type":"object","properties":{"task_id":{"type":"integer"}},"required":["task_id"]}),
        types.Tool(name="process_stop_server",   description="DANGEROUS: stop the background worker process. All tasks halt. Only call when explicitly requested by the user.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="process_restart_server",description="DANGEROUS: restart the background worker process. Running tasks are interrupted. Only call when explicitly requested by the user.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="plugin_list",           description="List all available plugins with their argument definitions.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="plugin_run",            description="Run a plugin by id, passing args as a flat dict. Returns task_id for tracking via process tools.", inputSchema={"type":"object","properties":{"plugin_id":{"type":"string"},"args":{"type":"object"}},"required":["plugin_id"]}),
        types.Tool(name="search_books",          description="Start (or re-issue) the book search; replaces any previous search. Returns the first item { cursor_id, type: \"v\", index, content, total }. Re-issue with the offset carried by a sentinel to continue stepping.", inputSchema={"type":"object","properties":{"offset":{"type":"integer"},"filter_text":{"type":"string"},"filter_tags":{"type":"string"},"rating_limit":{"type":"integer"},"sorting":{"type":"string"},"filter_type":{"type":"string"}}}),
        types.Tool(name="search_media",          description="Start (or re-issue) the media search over folders and files (\"\" = root); replaces any previous search. Returns the first item { cursor_id, type: \"m\", index, content, total } where content has a \"type\": \"folder\"|\"file\" field.", inputSchema={"type":"object","properties":{"folder_id":{"type":"string"},"offset":{"type":"integer"},"filter_text":{"type":"string"},"rating_limit":{"type":"integer"},"sorting":{"type":"string"}}}),
        types.Tool(name="search_media_by_date",  description="Start (or re-issue) the media-by-date search; replaces any previous search. Returns the first item { cursor_id, type: \"md\", index, content, total }. Default sort is date descending (newest first).", inputSchema={"type":"object","properties":{"start_date":{"type":"string"},"end_date":{"type":"string"},"offset":{"type":"integer"},"rating_limit":{"type":"integer"},"sorting":{"type":"string"}},"required":["start_date","end_date"]}),
        types.Tool(name="cursor_info",           description="Describe the active search cursor without moving it: { cursor_id, type, index, content, offset, fetched, total }.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="cursor_next",           description="Advance the active search to the next item (one item at a time). At the end of the fetched items returns { status: \"exhausted\", offset, total } — re-issue the search with that offset to continue.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="cursor_prev",           description="Move the active search back one item. At the start of the fetched items returns { status: \"window_start\", offset, total } (earlier items exist) or { status: \"at_start\" } on the very first item.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="cursor_close",          description="Discard the active search cursor and any active chapter/image cursor, and free their memory.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="chapter_next",          description="Advance the chapter cursor to the next chapter of the current book. Envelope: { cursor_id, type: \"c\", book_id, chapter_id: null, index, content: {name, value}, total }. At the last chapter returns { status: \"exhausted\" }.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="chapter_prev",          description="Move the chapter cursor back one chapter. On the first chapter returns { status: \"at_start\" }.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="image_next",            description="Advance the image cursor to the next file of the current chapter. Envelope: { cursor_id, type: \"i\", book_id, chapter_id, index, content: filename, total }. At the last file returns { status: \"exhausted\" }.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="image_prev",            description="Move the image cursor back one file. On the first file returns { status: \"at_start\" }.", inputSchema={"type":"object","properties":{}}),
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

**Checkpoint:** the MCP client lists all registered tools when it starts.

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
11. `search_books` with no params → first item: `{ cursor_id, type: "v", index: 0, content, total }`, `total` > 0
12. `cursor_next` → next item (index 1)
13. `search_books(offset=<offset from an exhausted sentinel>)` → continues stepping from that window
14. `cursor_prev` on the very first item → `{ status: "at_start" }`
15. `volume_get_book` with no `book_id` → returns the book the cursor points at
16. `volume_get_style` with no `book_id` → just the style field of the cursor's book
17. `volume_list_chapters` with no `book_id` → chapters of the cursor's book; points the chapter cursor at chapter 1
18. `volume_list_images` with no `chapter_id` → files of the chapter cursor's chapter; points the image cursor at file 1
19. `image_next` → next file; at the end of the chapter: `{ status: "exhausted" }`
20. `volume_get_image` with no `chapter_id`/`filename` → the image the image cursor points at
21. `chapter_next` → next chapter; at the end of the book: `{ status: "exhausted" }`
22. `cursor_close` → `{ "closed": true }` (also drops the chapter/image cursors)
23. `search_media` on root folder → first item with `content` carrying a `"type": "folder"|"file"` field

---

## Notes for the implementing AI

- **Never hard-code credentials** — always read from environment variables via `config.py`
- **Do not add threading** — the server is single-instance, single-thread; `requests.Session` is reused across calls
- **Token storage** — the `SESSION` singleton in `session.py` lives in memory for the process lifetime; it is not persisted to disk
- **Circular import** — `http_client.py` imports `login` lazily (inside the function) to avoid the `auth_client → http_client → auth_client` cycle
- **Base64 for binary** — all binary responses (images, file downloads) are base64-encoded before being placed in the MCP text result so the JSON transport stays clean
- **Error surfacing** — never swallow exceptions silently; always let them propagate so the MCP framework can return them as tool errors to the AI caller
