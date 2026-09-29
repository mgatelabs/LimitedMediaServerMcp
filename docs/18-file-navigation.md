# MCP Server — File Navigation Tool Contracts

These tools provide a **stateful file browsing context** that remembers the
currently open folder and the agent's position within its file list.

This removes the need for the agent to manually track offsets or file IDs when
stepping through a folder's contents one file at a time.

The file context is stored **in-memory** in the MCP server process and is lost
on restart — the same behaviour as search cursors and the book reading context.
Only one folder can be open at a time; opening a new folder replaces the
previous context.

---

## File context state

```python
@dataclass
class FileContext:
    folder_id:    str    # currently open folder ID
    folder_name:  str    # display name of the folder
    files:        list   # full file list [{id, filename, filesize, mime_type,
                         #                  preview, archive, folder_id}, ...]
    index:        int    # 0-based position within files[]

# Module-level singleton; None when no folder is open
CONTEXT: FileContext | None = None
```

**Invariants:**
- `CONTEXT` is `None` until `files_open` is called successfully.
- `index` is always a valid index into `files` (0 ≤ index < len(files)).
- `files` may be an empty list if the folder contains no files — see
  `files_open` return value for this case.

---

## Tool: `files_open`

**Purpose:** Load all files from a folder into the navigation context and
position the cursor at the first file.

**MCP tool name:** `files_open`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `folder_id` | string | yes | ID of the folder to open |

**Behaviour:**
1. Call `media_client.get_folder(folder_id)` to fetch folder metadata — raises on error.
2. Fetch all files via `media_client.list_media(folder_id, offset=0, limit=100)`;
   paginate until all files are collected.
3. Store folder name, full file list, and `index=0` in `CONTEXT`.
4. Return the context summary.

**Returns:**
```json
{
  "folder_id":   "abc123",
  "folder_name": "My Folder",
  "file_count":  42,
  "index":       0,
  "file": {
    "id":        "f001",
    "filename":  "movie.mp4",
    "filesize":  1073741824,
    "mime_type": "video/mp4",
    "preview":   false,
    "archive":   false,
    "folder_id": "abc123"
  }
}
```

If the folder contains no files, `file` is `null` and `file_count` is `0`.

**Agent guidance:**
- Calling `files_open` on a different folder replaces the previous context
  entirely — there is no nesting.
- Root folders (`folder_id=""`) contain no files; `file_count` will be `0`.
- All files in the folder are loaded upfront so `files_next`/`files_prev` need
  no further network calls.

---

## Tool: `files_current`

**Purpose:** Return the current file's metadata without advancing the cursor
and without any network call.

**MCP tool name:** `files_current`

**Parameters:** none

**Returns (context active):** same shape as the `files_open` return value.

**Returns (no context):**
```json
{ "error": "No folder open — call files_open first" }
```

**Returns (folder is empty):**
```json
{
  "folder_id":   "abc123",
  "folder_name": "My Folder",
  "file_count":  0,
  "index":       0,
  "file":        null
}
```

---

## Tool: `files_next`

**Purpose:** Advance the cursor to the next file and return its metadata.

**MCP tool name:** `files_next`

**Parameters:** none

**Behaviour:**
1. Raise `RuntimeError("No folder open")` if `CONTEXT` is `None`.
2. If `index + 1 >= len(files)` return `{ "done": true }` — already at last file.
3. Increment `index`.
4. Return the context summary.

**Returns (normal):** same shape as `files_open`.

**Returns (at last file):**
```json
{ "done": true, "index": 41, "file_count": 42 }
```

**Agent guidance:** `done=true` means the agent has seen every file in this
folder. It should close or move on rather than calling `files_next` again.

---

## Tool: `files_prev`

**Purpose:** Move the cursor back to the previous file.

**MCP tool name:** `files_prev`

**Parameters:** none

**Behaviour:**
1. Raise `RuntimeError("No folder open")` if `CONTEXT` is `None`.
2. If `index == 0` return `{ "at_start": true }`.
3. Decrement `index`.
4. Return the context summary.

**Returns (normal):** same shape as `files_open`.

**Returns (at first file):**
```json
{ "at_start": true, "index": 0, "file_count": 42 }
```

---

## Tool: `files_get_preview`

**Purpose:** Fetch the preview image for the current file.

**MCP tool name:** `files_get_preview`

**Parameters:** none

**Behaviour:**
1. Raise `RuntimeError("No folder open")` if `CONTEXT` is `None`.
2. If `files` is empty or `file.preview == false`, return
   `{ "has_preview": false }` — no network call.
3. Otherwise call `media_client.get_preview(file.id, has_preview=True)` and
   return the image content.

**Returns (no preview):**
```json
{ "has_preview": false, "file_id": "f001", "filename": "movie.mp4" }
```

**Returns (preview available):** a list — `[ImageContent, TextContent]`:
```python
[
  ImageContent(type="image", data="<base64>", mimeType="image/jpeg"),
  TextContent(type="text", text=json.dumps({
    "file_id":   "f001",
    "filename":  "movie.mp4",
    "folder_id": "abc123",
    "index":     0,
    "file_count": 42,
  }))
]
```

---

## Error responses (all files_* tools)

| Condition | Response |
|---|---|
| No folder open | `RuntimeError("No folder open — call files_open first")` |
| Backend error | `RuntimeError("<server error message>")` propagated from media_client |
| Empty folder | `file: null` in summary; `files_next`/`files_prev` return `done`/`at_start` immediately |
