# MCP Server — Search Cursor Tool Contracts

## Design summary

- `search_books`, `search_media`, and `search_media_by_date` each open **the**
  search cursor and return the **first item**. A new search **replaces** any
  previous one — there is exactly one active search at a time, and no
  cursor_id is passed between calls.
- `cursor_next` and `cursor_prev` step **one item at a time**; the server
  holds the position. `cursor_info` inspects the position without moving it.
- Cursor state is **in-memory** in the MCP server process (lost on restart).
- The server fetches **200 items per HTTP request** from the backend. The
  cursor walks that fetched window one item at a time and **does not
  re-fetch automatically**. When the window is exhausted, the cursor returns
  a sentinel with an `offset` — to keep going, the agent **re-issues the
  same search with that offset**.
- The search cursor is joined by two **list cursors** that complete the
  navigation stack book → chapter → image: the **chapter cursor** (the
  chapters of the current book) and the **image cursor** (the files of the
  current chapter). Each list is **fully fetched on open** (a book's chapter
  list and a chapter's file list are small), stepped one item at a time with
  `chapter_next`/`chapter_prev` and `image_next`/`image_prev`, with no
  offset to resume — only `exhausted`/`at_start` sentinels. One list cursor
  is active at a time (opening one replaces the other); opening a new
  search or `cursor_close` drops it. While a list cursor is active,
  `chapter_id` can be omitted from `volume_list_images` /
  `volume_get_image` and `filename` from `volume_get_image`.

---

## Envelope

**Normal step** (search, `cursor_next`, `cursor_prev`, `cursor_info`):

```json
{
  "cursor_id": "a1b2c3d4...",
  "type": "v",
  "index": 3,
  "content": { "id": "bk_004", "name": "One Piece", "style": "page", "tags": [] },
  "total": 694
}
```

| Field | Meaning |
|---|---|
| `cursor_id` | Identity of the active search (informational; not an argument) |
| `type` | Search type: `v` book · `m` media · `md` media-by-date |
| `index` | 0-based position within the current fetched window |
| `content` | The current item (`null` in sentinels). Media items carry a `"type": "folder" \| "file"` field of their own |
| `total` | Total items the backend reports for this search |

`cursor_info` additionally returns `offset` (window start) and `fetched`
(window size) instead of nothing else.

**Sentinel** (no current item — the window ran out):

```json
{
  "cursor_id": "a1b2c3d4...",
  "type": "v",
  "index": 199,
  "content": null,
  "offset": 400,
  "total": 694,
  "status": "exhausted"
}
```

| `status` | When | `offset` means |
|---|---|---|
| `exhausted` | `cursor_next` past the last fetched item (or an empty search) | Start of the **next** window: re-issue the same search with this offset while `offset < total`; otherwise the search is fully complete |
| `window_start` | `cursor_prev` on the first fetched item, earlier items exist | Start of the **previous** window: re-issue the same search with this offset to keep stepping back |
| `at_start` | `cursor_prev` on the very first item of the whole search | — |

---

## Stepping loop

```
search_books(...)                    → item 0
  work with content
  cursor_next()                      → item 1
  ...
  cursor_next()                      → item 199
  cursor_next()                      → { status: "exhausted", offset: 200, total: 694 }
  200 < 694 → search_books(offset=200, <same filters>)  → item 200
  ...
  cursor_next()                      → { status: "exhausted", offset: 600, total: 694 }
  600 < 694 → search_books(offset=600, <same filters>)  → item 600 … 693
  cursor_next()                      → { status: "exhausted", offset: 694, total: 694 }
  694 == 694 → done
  cursor_close()
```

---

## List cursors (chapter / image)

Two single-active list cursors sit below the search cursor:

| Cursor | Opens with | Walks | `type` | `content` |
|---|---|---|---|---|
| Chapter | `volume_list_chapters` (one HTTP call, full list) | the chapters of the current book | `c` | the chapter entry `{ "name": "Chapter 1", "value": "ch001" }` |
| Image | `volume_list_images` (one HTTP call, full list) | the files of the current chapter | `i` | the filename string, e.g. `"001.jpg"` |

The chapter cursor is scoped to the book the **book_id argument or the
active search cursor** points at; the image cursor to that chapter. Both
are dropped when a new search opens or `cursor_close` runs, and opening
one replaces the other.

**Normal step** (`chapter_next`, `chapter_prev`, `image_next`,
`image_prev`):

```json
{
  "cursor_id": "d3c4b5a6...",
  "type": "c",
  "book_id": "bk_004",
  "chapter_id": null,
  "index": 0,
  "content": { "name": "Chapter 1", "value": "ch001" },
  "total": 1200
}
```

```json
{
  "cursor_id": "9f8e7d6c...",
  "type": "i",
  "book_id": "bk_004",
  "chapter_id": "ch001",
  "index": 1,
  "content": "002.jpg",
  "total": 22
}
```

| Field | Meaning |
|---|---|
| `cursor_id` | Identity of the active list cursor (informational; not an argument) |
| `type` | `c` chapter · `i` image |
| `book_id` | The book the cursor is scoped to |
| `chapter_id` | The chapter (null on a chapter cursor) |
| `index` | 0-based position within the list |
| `content` | The current item (`null` in sentinels) — chapter entry `{name, value}` or filename |
| `total` | Total items in the list (the whole list is fetched on open) |

**Sentinels** — the list is fully fetched, so there is no `offset` and no
re-fetch:

| `status` | When |
|---|---|
| `exhausted` | `chapter_next`/`image_next` past the last item (or an empty list) — nothing to continue with |
| `at_start` | `chapter_prev`/`image_prev` on the first item |

**Stepping loop** (4 chapters × 6 images per book):

```
volume_list_chapters()            → { …, type: "c", index: 0, content: {name, value}, total }
  volume_list_images()            → { …, type: "i", index: 0, content: "001.jpg", total }
    volume_get_image()            → the image the image cursor points at
    image_next()                  → "002.jpg" … up to 6 times (or the exhausted sentinel)
  chapter_next()                  → { …, type: "c", index: 1, … }  … up to 4 times (or exhausted)
```

---

## Internal: `CursorStore`

```python
CHUNK_SIZE = 200  # items fetched from the backend per HTTP request

@dataclass
class Cursor:
    cursor_id: str          # uuid4 hex
    type:      str          # "v" | "m" | "md"
    params:    dict         # frozen search parameters
    items:     list         # current fetched window (up to CHUNK_SIZE)
    offset:    int          # server offset of items[0]
    index:     int          # 0-based position within items[]
    total:     int          # total items on the server

# Module-level singleton: only ONE active cursor
ACTIVE: Cursor | None = None
```

**List cursors** (chapter `"c"` / image `"i"`):

```python
@dataclass
class ListCursor:
    cursor_id:  str                 # uuid4
    type:       str                 # "c" | "i"
    book_id:    str                 # the book the cursor is scoped to
    chapter_id: str | None          # None on a chapter cursor
    items:      list                # full list, fetched on open
    index:      int = 0             # 0-based position within items[]

# Module-level singleton: only ONE active list cursor
ACTIVE_LIST: ListCursor | None = None
```

**Helpers:**

- `open_list_cursor(type, book_id, chapter_id, items)` — replace
  `ACTIVE_LIST` and return the first item's envelope (or the `exhausted`
  sentinel when the list is empty). `volume_list_chapters` calls it with
  type `"c"` and the chapter entries; `volume_list_images` with type `"i"`
  and the filenames.
- `current_chapter_id()` — the `chapter_id` fallback: the chapter a `"c"`
  cursor points at (`items[index]["value"]`) or the chapter a `"i"` cursor
  is scoped to (opening the image cursor replaces the chapter cursor, but
  the id stays usable); raises when no list cursor is active.
- `current_image_filename()` — the `filename` fallback: `items[index]` of
  an active `"i"` cursor; raises when none.
- `list_info()` — envelope plus no move; no network call.
- `list_next()` — `index += 1` if possible, else `exhausted`.
- `list_prev()` — `index -= 1` if possible, else `at_start`.
- `list_close()` — set `ACTIVE_LIST = None`; `{ "closed": true }` (or
  `{ "closed": false }`).
- `search()` and `cursor_close()` also set `ACTIVE_LIST = None` — the
  stack stays coherent when the book it points at changes.
- `chapter_next` / `chapter_prev` / `image_next` / `image_prev` raise
  `RuntimeError("No active chapter/image cursor — call volume_list_chapters
  or volume_list_images first")` when `ACTIVE_LIST is None`.

**Helpers:**

- `search(type, params, offset=0)` — fetch a window at `offset`, replace
  `ACTIVE`, return the first item (or an `exhausted` sentinel when empty).
- `_envelope(c)` — `{cursor_id, type, index, content, total}` for the item
  at `c.index`.
- `_sentinel(c, status, offset)` — `{cursor_id, type, index, content: null,
  offset, total, status}`.
- `cursor_next()` — `index += 1` if possible, else `exhausted` sentinel with
  `offset = c.offset + len(c.items)`.
- `cursor_prev()` — `index -= 1` if possible, else `window_start` sentinel
  with `offset = c.offset - CHUNK_SIZE` (when `c.offset > 0`), else
  `at_start`.
- `cursor_info()` — envelope plus `offset` and `fetched`; no network call.
- `cursor_close()` — set `ACTIVE = None`; `{ "closed": true }` (or
  `{ "closed": false }` when no search is active).
- All step tools raise `RuntimeError("No active search — call search_books
  or search_media first")` when `ACTIVE is None`.

---

## Tool: `search_books`

**Purpose:** Start (or re-issue) the book search and return the first item.
Replaces any previous search of any type.

**MCP tool name:** `search_books`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `offset` | integer | no | `0` | Window offset — use the offset carried by a sentinel to continue |
| `filter_text` | string | no | `""` | Title text filter |
| `filter_tags` | string | no | `""` | Comma-separated tag filter |
| `rating_limit` | integer | no | `0` | Minimum rating |
| `sorting` | string | no | `"AZ"` | Sort order (`AZ`, `ZA`, `DA`, `DD`) |
| `filter_type` | string | no | `""` | Type filter |

**Backend endpoint:** `POST /api/volume/list/books`

**Behaviour:**
1. Fetch up to 200 books from the backend at `offset`.
2. Replace the active cursor with this search.
3. Return the first item of the window, or an `exhausted` sentinel with
   `offset = 200` when the window is empty.

**Returns:**
```json
{ "cursor_id": "a1b2c3d4...", "type": "v", "index": 0,
  "content": { "id": "bk_001", "name": "One Piece", "style": "page", "tags": [] },
  "total": 694 }
```

**Side effect for volume tools:** while this search is active, the
`volume_get_book`, `volume_get_name`, `volume_get_alt_name`,
`volume_get_style`, `volume_get_tags`, `volume_get_rating`,
`volume_get_active`, `volume_list_chapters`, `volume_list_images`,
`volume_get_image`, `volume_update_title`, `volume_update_alt_name`,
`volume_update_tags`, `volume_update_rating`, `volume_update_style`, and
`volume_update_book` tools may omit `book_id` — they apply to `content`
(the book the cursor points at).

---

## Tool: `search_media`

**Purpose:** Start (or re-issue) the media search over folders and files.

**MCP tool name:** `search_media`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder_id` | string | no | `""` | Folder to search within (empty = root) |
| `offset` | integer | no | `0` | Window offset — use the offset carried by a sentinel to continue |
| `filter_text` | string | no | `""` | Name text filter |
| `rating_limit` | integer | no | `0` | Minimum rating |
| `sorting` | string | no | `"AZ"` | Sort order |

**Backend endpoint:** `POST /api/media/list`

**Behaviour:** identical pattern as `search_books`, with type `m`.

**Returns:** same envelope shape as `search_books`, with `type: "m"` and
`content` being a folder- or file-shaped item:
```json
{ "cursor_id": "e5f6g7h8...", "type": "m", "index": 0,
  "content": { "type": "folder", "id": "", "name": "", "rating": 0, "parent_id": "" },
  "total": 73 }
```

**Structural rules:**
- `type: "folder"` items include `parent_id`; an empty `parent_id` means the folder is at root level.
- `type: "file"` items always include `folder_id` — files are never at root level and always belong to a folder.
- When `folder_id=""` (root) is searched, the result will contain only `type: "folder"` items — no files.
- Each item has a `"type"` discriminator prepended by the MCP layer so the agent can tell them apart.

---

## Tool: `search_media_by_date`

**Purpose:** Start (or re-issue) the media search over items created within a date range.

**MCP tool name:** `search_media_by_date`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `start_date` | string | yes | — | Start of date range, inclusive. Format: `YYYY-MM-DD` |
| `end_date` | string | yes | — | End of date range, inclusive. Format: `YYYY-MM-DD` |
| `offset` | integer | no | `0` | Window offset — use the offset carried by a sentinel to continue |
| `rating_limit` | integer | no | `0` | Minimum rating filter |
| `sorting` | string | no | `"DA"` | Sort order. Default is date-descending (`DA`) — most recent first |

**Backend endpoint:** `POST /api/media/list/by-date`

**Form fields:** `start_date`, `end_date`, `offset`, `limit`, `rating`, `sort`

**Behaviour:** identical pattern as `search_media`, with type `md`.

**Returns:** same envelope shape as `search_media`, items include both folders and files with `folder_id` on every file; file items also carry `created`.

**Notes:**
- `created` is included on file items in date-search results so the agent can see when each file was added.
- Date strings must be `YYYY-MM-DD` (e.g. `"2024-01-01"`). The server interprets them in its local timezone.
- To search a single day, pass the same value for `start_date` and `end_date`.
- The default sort `DA` (date descending) returns the newest files first, which is usually most useful for a date-range query. Pass `"AZ"` to sort alphabetically instead.

---

## Tool: `cursor_info`

**Purpose:** Describe the active search cursor without moving it (no network call).

**MCP tool name:** `cursor_info`

**Parameters:** none

**Returns:**
```json
{ "cursor_id": "a1b2c3d4...", "type": "v", "index": 3,
  "content": { "id": "bk_004", "name": "One Piece", "style": "page", "tags": [] },
  "offset": 0, "fetched": 200, "total": 694 }
```

---

## Tool: `cursor_next`

**Purpose:** Advance the active search to the next item.

**MCP tool name:** `cursor_next`

**Parameters:** none

**Behaviour:**
1. Raise `RuntimeError` if no search is active.
2. If the cursor is not on the last fetched item: `index += 1`, return the item envelope.
3. Otherwise return the `exhausted` sentinel:
```json
{ "cursor_id": "a1b2c3d4...", "type": "v", "index": 199, "content": null,
  "offset": 200, "total": 694, "status": "exhausted" }
```
No re-fetch happens — the agent re-issues the same search with the
sentinel's `offset` to continue (while `offset < total`).

---

## Tool: `cursor_prev`

**Purpose:** Move the active search back one item.

**MCP tool name:** `cursor_prev`

**Parameters:** none

**Behaviour:**
1. Raise `RuntimeError` if no search is active.
2. If `index > 0`: `index -= 1`, return the item envelope.
3. If `offset > 0`: return the `window_start` sentinel — earlier items exist
   beyond the fetched window:
```json
{ "cursor_id": "a1b2c3d4...", "type": "v", "index": 0, "content": null,
  "offset": 0, "total": 694, "status": "window_start" }
```
Re-issue the same search with the sentinel's `offset` to step further back.
4. Otherwise (on the very first item of the whole search):
```json
{ "cursor_id": "a1b2c3d4...", "type": "v", "index": 0, "content": null,
  "offset": 0, "total": 694, "status": "at_start" }
```

---

## Tool: `cursor_close`

**Purpose:** Discard the active search, free its memory, and drop any
active chapter/image list cursor.

**MCP tool name:** `cursor_close`

**Parameters:** none

**Returns:**
```json
{ "closed": true }
```
`{ "closed": false }` when neither a search nor a list cursor was active.

---

## Tool: `chapter_next`

**Purpose:** Advance the chapter cursor to the next chapter of the current book.

**MCP tool name:** `chapter_next`

**Parameters:** none

**Behaviour:**
1. Raise `RuntimeError` if no list cursor is active.
2. If the cursor is not on the last chapter: `index += 1`, return the list envelope (`type: "c"`, `chapter_id: null`).
3. Otherwise return the `exhausted` sentinel — the book has no more chapters.

---

## Tool: `chapter_prev`

**Purpose:** Move the chapter cursor back one chapter.

**MCP tool name:** `chapter_prev`

**Parameters:** none

**Behaviour:**
1. Raise `RuntimeError` if no list cursor is active.
2. If `index > 0`: `index -= 1`, return the list envelope.
3. Otherwise (on the first chapter) return the `at_start` sentinel.

---

## Tool: `image_next`

**Purpose:** Advance the image cursor to the next file of the current chapter.

**MCP tool name:** `image_next`

**Parameters:** none

**Behaviour:**
1. Raise `RuntimeError` if no list cursor is active.
2. If the cursor is not on the last file: `index += 1`, return the list envelope (`type: "i"`, `content` = filename).
3. Otherwise return the `exhausted` sentinel — the chapter has no more files.

---

## Tool: `image_prev`

**Purpose:** Move the image cursor back one file.

**MCP tool name:** `image_prev`

**Parameters:** none

**Behaviour:**
1. Raise `RuntimeError` if no list cursor is active.
2. If `index > 0`: `index -= 1`, return the list envelope.
3. Otherwise (on the first file) return the `at_start` sentinel.

---

## Agent guidance

- **One search at a time** — starting any search drops the previous one, so
  interleave book and media searches carefully; the position is not shared.
- **Step, don't cache** — the server holds the position; the agent only ever
  looks at `content` and steps with `cursor_next` / `cursor_prev`.
- **Continue with the offset** — on an `exhausted` sentinel with
  `offset < total`, re-issue the same search with that offset (same
  filters). Do not assume the window refills itself.
- **Close when done** — `cursor_close` frees the fetched window; also
  dropped on server restart.
- **Omit `book_id` while stepping books** — volume get/update tools apply
  to the book the cursor points at, so a search + step + update loop never
  needs to carry IDs around explicitly.
- **Open the list cursors, then omit the ids** — `volume_list_chapters`
  and `volume_list_images` return their normal list bodies AND point the
  chapter/image cursors at the first entry. After that,
  `volume_get_image()` with no arguments fetches the current image, and
  `chapter_next` / `image_next` walk the rest — no `chapter_id` or
  `filename` arguments needed.
- **List cursors have no offset** — the whole list is fetched on open, so
  an `exhausted` sentinel is the end of the book/chapter; there is nothing
  to re-issue.
- `total` in the first response is the authoritative count for that search;
  `index` is window-relative, not an absolute library position.
