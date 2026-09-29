# MCP Server — Pagination & Search Tool Contracts

## Design summary

- `search_books`, `search_media`, and `search_media_by_date` open a **cursor** and return the first page.
- `cursor_next`, `cursor_prev`, `cursor_close` operate on any cursor regardless of domain.
- Cursors are stored **in-memory** in the MCP server process (lost on restart).
- The server fetches **200 items per chunk** from the backend; the agent sees **20 items per page**.
- When the agent pages past the end of the current 200-item chunk, the server automatically fetches the next chunk using the same search parameters.

---

## Cursor lifecycle

```
search_books / search_media / search_media_by_date
        │
        ▼  returns cursor_id + page 0 (items 0-19)
        │
  cursor_next ──► fetches items 20-39 from local chunk
  cursor_next ──► fetches items 40-59 ...
  ...
  cursor_next ──► items 180-199  (end of chunk)
  cursor_next ──► re-fetches next 200 from backend, returns items 200-219
  ...
  cursor_next ──► returns { done: true } when no more items exist
  cursor_prev ──► works symmetrically; cannot go before item 0
        │
  cursor_close ──► releases the cursor from memory
```

---

## Internal: `CursorStore`

```python
PAGE_SIZE  = 20    # items returned to agent per call
CHUNK_SIZE = 200   # items fetched from backend per HTTP request

@dataclass
class Cursor:
    cursor_id:   str           # uuid4 hex
    domain:      str           # "books" | "media"
    params:      dict          # original search parameters (frozen)
    chunk:       list          # current fetched items (up to CHUNK_SIZE)
    chunk_offset: int          # offset of chunk[0] in the full result set
    page_index:  int           # current page index within the chunk (0-based)
    total:       int           # total items on server (-1 = unknown)

# Module-level singleton
CURSORS: dict[str, Cursor] = {}
```

**Helper logic:**

```python
def _global_offset(cursor: Cursor) -> int:
    """Absolute offset of the first item on the current page."""
    return cursor.chunk_offset + cursor.page_index * PAGE_SIZE

def _current_page(cursor: Cursor) -> list:
    start = cursor.page_index * PAGE_SIZE
    return cursor.chunk[start : start + PAGE_SIZE]

def _needs_next_chunk(cursor: Cursor) -> bool:
    start = (cursor.page_index + 1) * PAGE_SIZE
    return start >= len(cursor.chunk)

def _needs_prev_chunk(cursor: Cursor) -> bool:
    return cursor.page_index == 0 and cursor.chunk_offset > 0
```

---

## Tool: `search_books`

**Purpose:** Open a paginated search cursor over the book collection and return the first page.

**MCP tool name:** `search_books`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `filter_text` | string | no | `""` | Title text filter |
| `filter_tags` | string | no | `""` | Comma-separated tag filter |
| `rating_limit` | integer | no | `0` | Minimum rating |
| `sorting` | string | no | `"AZ"` | Sort order (`AZ`, `ZA`, `DA`, `DD`) |
| `filter_type` | string | no | `""` | Type filter |

**Backend endpoint:** `POST /api/volume/list/books`

**Behaviour:**
1. Fetch the first `CHUNK_SIZE` (200) books from the backend with `offset=0`.
2. Create a `Cursor` with `domain="books"`, store in `CURSORS`.
3. Return the first page (items 0–19) plus cursor metadata.

**Returns:**
```json
{
  "cursor_id": "a1b2c3d4...",
  "page": 1,
  "total_pages": 35,
  "total_items": 694,
  "has_next": true,
  "has_prev": false,
  "items": [ ...20 BookData objects... ]
}
```

`total_pages` = `ceil(total_items / PAGE_SIZE)`.  
`page` is 1-based for human readability.

---

## Tool: `search_media`

**Purpose:** Open a paginated search cursor over the media file/folder collection.

**MCP tool name:** `search_media`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder_id` | string | no | `""` | Folder to search within (empty = root) |
| `filter_text` | string | no | `""` | Name text filter |
| `rating_limit` | integer | no | `0` | Minimum rating |
| `sorting` | string | no | `"AZ"` | Sort order |

**Backend endpoint:** `POST /api/media/list`

**Behaviour:** identical cursor creation pattern as `search_books`, with `domain="media"`.

**Returns:** same envelope shape as `search_books`, with `items` being folders first, then files:
```json
{
  "cursor_id": "e5f6g7h8...",
  "page": 1,
  "total_pages": 4,
  "total_items": 73,
  "has_next": true,
  "has_prev": false,
  "items": [
    { "type": "folder", "id": "", "name": "", "rating": 0, "parent_id": "" },
    { "type": "file",   "id": "", "name": "", "filesize": 0, "mime_type": "", "folder_id": "" }
  ]
}
```

**Structural rules:**
- `type: "folder"` items include `parent_id`; an empty `parent_id` means the folder is at root level.
- `type: "file"` items always include `folder_id` — files are never at root level and always belong to a folder.
- When `folder_id=""` (root) is searched, the result will contain only `type: "folder"` items — no files.
- Each item has a `"type"` discriminator prepended by the MCP layer so the agent can tell them apart.

---

## Tool: `search_media_by_date`

**Purpose:** Open a paginated cursor over media files created within a date range.

**MCP tool name:** `search_media_by_date`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `start_date` | string | yes | — | Start of date range, inclusive. Format: `YYYY-MM-DD` |
| `end_date` | string | yes | — | End of date range, inclusive. Format: `YYYY-MM-DD` |
| `rating_limit` | integer | no | `0` | Minimum rating filter |
| `sorting` | string | no | `"DA"` | Sort order. Default is date-descending (`DA`) — most recent first |

**Backend endpoint:** `POST /api/media/list/by-date`

**Form fields:** `start_date`, `end_date`, `offset`, `limit`, `rating`, `sort`

**Behaviour:** identical cursor creation pattern as `search_media`, with `domain="media_by_date"`.

**Returns:** same envelope shape as `search_media`, items include both folders and files with `folder_id` on every file:

```json
{
  "cursor_id": "f9g0h1i2...",
  "page": 1,
  "total_pages": 3,
  "total_items": 41,
  "has_next": true,
  "has_prev": false,
  "items": [
    { "type": "folder", "id": "", "name": "", "rating": 0, "parent_id": "" },
    { "type": "file",   "id": "", "name": "", "filesize": 0, "mime_type": "", "folder_id": "", "created": "" }
  ]
}
```

**Notes:**
- `created` is included on file items in date-search results so the agent can see when each file was added.
- Date strings must be `YYYY-MM-DD` (e.g. `"2024-01-01"`). The server interprets them in its local timezone.
- To search a single day, pass the same value for `start_date` and `end_date`.
- The default sort `DA` (date descending) returns the newest files first, which is usually most useful for a date-range query. Pass `"AZ"` to sort alphabetically instead.

---

## Tool: `cursor_next`

**Purpose:** Advance the cursor by one page and return the next 20 items.

**MCP tool name:** `cursor_next`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `cursor_id` | string | yes | Cursor ID from `search_books`, `search_media`, or `search_media_by_date` |

**Behaviour:**
1. Look up cursor in `CURSORS`; raise `RuntimeError("Cursor not found")` if missing.
2. If there are still items in the current chunk for the next page: increment `page_index`, return next page.
3. If we are at the end of the current chunk AND `chunk_offset + len(chunk) < total`: fetch the next chunk from the backend (`offset = chunk_offset + CHUNK_SIZE`), reset `page_index = 0`.
4. If there are no more items: return `{ "done": true, "cursor_id": "..." }`.

**Returns (normal):** same envelope as `search_books` with updated `page`, `has_next`, `has_prev`, `items`.

**Returns (exhausted):**
```json
{ "done": true, "cursor_id": "a1b2c3d4..." }
```

---

## Tool: `cursor_prev`

**Purpose:** Move the cursor back by one page.

**MCP tool name:** `cursor_prev`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `cursor_id` | string | yes | Cursor ID |

**Behaviour:**
1. If `page_index > 0`: decrement `page_index`, return current page.
2. If `page_index == 0` AND `chunk_offset > 0`: fetch the previous chunk (`offset = chunk_offset - CHUNK_SIZE`), set `page_index` to the last page of the newly loaded chunk.
3. If already at the very first item: return `{ "at_start": true, "cursor_id": "..." }`.

**Returns (normal):** same envelope as `search_books`.

**Returns (at start):**
```json
{ "at_start": true, "cursor_id": "a1b2c3d4..." }
```

---

## Tool: `cursor_close`

**Purpose:** Release a cursor and free its memory.

**MCP tool name:** `cursor_close`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `cursor_id` | string | yes | Cursor ID to delete |

**Behaviour:** remove from `CURSORS`; silently ignore if already gone.

**Returns:**
```json
{ "closed": true, "cursor_id": "a1b2c3d4..." }
```

---

## Agent guidance

- **Always close cursors** when done browsing. Unclosed cursors accumulate in memory for the process lifetime.
- **Do not cache cursor IDs across MCP server restarts** — they are in-memory only.
- `search_books` with no parameters returns all books sorted A→Z, 20 at a time.
- To re-run the same search from the beginning, call `search_books` again (it creates a new cursor).
- `total_pages` and `total_items` in the first response are the authoritative counts for that search.
