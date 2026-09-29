# MCP Server — File Navigation Implementation Guide

Read `18-file-navigation.md` first for the full tool contracts.

---

## What to create

### 1. `mcp_media_server/file_session.py` — new file

```python
"""In-memory file browsing context for stateful folder navigation."""

from dataclasses import dataclass, field


@dataclass
class FileContext:
    folder_id:   str
    folder_name: str
    files:       list   # list of file dicts
    index:       int


# Module-level singleton; None when no folder has been opened this session.
CONTEXT: FileContext | None = None


def clear() -> None:
    global CONTEXT
    CONTEXT = None
```

---

### 2. `mcp_media_server/mcp_server.py` — additions

#### 2a. Import

Add after the existing `import media_client` line:

```python
import file_session
```

#### 2b. New tool block

Add a `# --- file navigation ---` section inside `_make_server()`,
after the existing `# --- media ---` section.

```python
# --- file navigation ---

@mcp.tool()
def files_open(folder_id: str) -> dict:
    """Open a folder and load its file list into the navigation context."""
    ...

@mcp.tool()
def files_current() -> dict:
    """Return the current file's metadata (no network call)."""
    ...

@mcp.tool()
def files_next() -> dict:
    """Advance to the next file and return its metadata."""
    ...

@mcp.tool()
def files_prev() -> dict:
    """Move back to the previous file and return its metadata."""
    ...

@mcp.tool()
def files_get_preview() -> object:
    """Fetch the preview image for the current file."""
    ...
```

---

## Shared helper: `_file_context_summary`

Define as a module-level or inner function:

```python
def _file_context_summary() -> dict:
    ctx = file_session.CONTEXT
    file = ctx.files[ctx.index] if ctx.files else None
    return {
        "folder_id":   ctx.folder_id,
        "folder_name": ctx.folder_name,
        "file_count":  len(ctx.files),
        "index":       ctx.index,
        "file":        file,
    }
```

---

## Implementation notes for each tool

### `files_open`

```python
folder = media_client.get_folder(folder_id)

# Paginate all files
files = []
offset = 0
limit = 100
while True:
    result = media_client.list_media(folder_id=folder_id, offset=offset, limit=limit)
    batch = result.get("files", [])
    files.extend(batch)
    if len(batch) < limit:
        break
    offset += limit

file_session.CONTEXT = file_session.FileContext(
    folder_id=folder_id,
    folder_name=folder.get("name", folder_id),
    files=files,
    index=0,
)
return _file_context_summary()
```

### `files_current`

```python
if file_session.CONTEXT is None:
    return {"error": "No folder open — call files_open first"}
return _file_context_summary()
```

### `files_next`

```python
ctx = file_session.CONTEXT
if ctx is None:
    raise RuntimeError("No folder open — call files_open first")
if not ctx.files or ctx.index + 1 >= len(ctx.files):
    return {"done": True, "index": ctx.index, "file_count": len(ctx.files)}
ctx.index += 1
return _file_context_summary()
```

### `files_prev`

Mirror of `files_next`:
- If `index == 0` or files is empty: return `{"at_start": True, ...}`.
- Otherwise decrement `index` and return summary.

### `files_get_preview`

```python
ctx = file_session.CONTEXT
if ctx is None:
    raise RuntimeError("No folder open — call files_open first")
if not ctx.files:
    return {"has_preview": False}

file = ctx.files[ctx.index]
if not file.get("preview"):
    return {"has_preview": False, "file_id": file["id"], "filename": file.get("filename", "")}

info = media_client.get_preview(file["id"], has_preview=True)
return [
    ImageContent(type="image", data=info["data"], mimeType=info["mime_type"]),
    TextContent(type="text", text=json.dumps({
        "file_id":    file["id"],
        "filename":   file.get("filename", ""),
        "folder_id":  ctx.folder_id,
        "index":      ctx.index,
        "file_count": len(ctx.files),
    })),
]
```

---

## File change summary

| File | Change |
|---|---|
| `mcp_media_server/file_session.py` | **Create** — `FileContext` dataclass + `CONTEXT` singleton |
| `mcp_media_server/mcp_server.py` | **Edit** — add `import file_session` and 5 new tool functions |

No other files need to change. No new dependencies required.

---

## Consistency checks before submitting

- `file_session.CONTEXT` is only written in `files_open`; all other tools read it.
- All tools that require an open folder check `if file_session.CONTEXT is None` first.
- `files` may be an empty list — guard all `ctx.files[ctx.index]` accesses with
  `if ctx.files` before indexing.
- `media_client.get_preview` expects `has_preview=True` as the second positional
  argument — match the signature in `media_client.py`.
- `files_open` uses `media_client.list_media` (not `list_files`) to also get the
  folder name from `result["info"]` if needed, or uses `media_client.get_folder`
  separately as shown above.
