# MCP Server — Volume (Book) Tool Contracts

All tools in this file map to `/api/volume/*` endpoints.  
The internal name is "Volume"; the user-facing name is "Book".  
Every call uses `Authorization: Bearer <token>` header.  
All write/list calls use `multipart/form-data` POST bodies.

**Access control:** the server enforces per-request access on every call. Books whose `rating` exceeds the authenticated user's volume rating limit (`SESSION.limits.volume`) are invisible — list calls omit them and direct fetch calls return an error. Each image fetch is independently verified. This is enforced server-side; the agent cannot bypass it.

**Cursor fallback:** the `book_id` parameter is optional on every tool in this file except `volume_list_books`. When omitted, the tool applies to the book the active search cursor points at (set by `search_books` + `cursor_next`/`cursor_prev` — see `07-pagination-tools.md`). If no book search is active, the call raises an error.

---

## Tool: `volume_list_books`

**Purpose:** List books with optional filtering and pagination.

**MCP tool name:** `volume_list_books`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `offset` | integer | no | `0` | Pagination offset |
| `limit` | integer | no | `100` | Max books to return |
| `rating_limit` | integer | no | `0` | Minimum rating |
| `filter_text` | string | no | `""` | Title text filter |
| `filter_tags` | string | no | `""` | Comma-separated tag filter |
| `sorting` | string | no | `"AZ"` | Sort order |
| `filter_type` | string | no | `""` | Type filter |

**Backend endpoint:** `POST /api/volume/list/books`

**Form fields:** `offset`, `limit`, `rating`, `sort`, `filter_text`, `filter_type`, `filter_tags`

**Returns:**
```json
{
  "books": [
    {
      "id": "", "name": "", "first": "", "last": "", "cover": "",
      "date": "", "tags": [], "style": "page", "restricted": false,
      "active": true, "rating": 0
    }
  ],
  "paging": { "total": 0, "offset": 0 }
}
```

---

## Tool: `volume_get_book`

**Purpose:** Fetch full details (definition) of a single book.

**MCP tool name:** `volume_get_book`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `book_id` | string | no | Book ID (the `id` / `json` field). Optional — defaults to the book the active search cursor points at |

**Backend endpoint:** `POST /api/volume/details`

**Form fields:** `book_id`

**Returns:**
```json
{
  "id": "", "name": "", "alt_name": "", "extra_url": "",
  "start_chapter": "", "rating": 0, "processor": "",
  "info_url": "", "rss_url": "", "skip": "",
  "style": "page", "active": true, "tags": []
}
```

---

## Single-field getters (one-horse-pony)

Six tools return **just one field** of the book definition instead of the
whole object — for agents that only need a specific value (e.g. confirming
a style write, or reading tags before merging). All share the same shape:

| Tool | Returns |
|---|---|
| `volume_get_name` | the title (`name`) — string |
| `volume_get_alt_name` | the alternative name (`alt_name`) — string |
| `volume_get_style` | the layout style (`style`) — string, `"page"` or `"scroll"` |
| `volume_get_tags` | the tag list (`tags`) — JSON array of strings, e.g. `["MC:A", "x"]`; `"[]"` when empty |
| `volume_get_rating` | the rating (`rating`) — integer |
| `volume_get_active` | the active flag (`active`) — boolean |

**Parameters (all six):**

| Name | Type | Required | Description |
|---|---|---|---|
| `book_id` | string | no | Book ID. Optional — defaults to the book the active search cursor points at |

**Backend endpoint:** `POST /api/volume/details` (same call as
`volume_get_book`; the server extracts the single field).

---

## Tool: `volume_list_chapters`

**Purpose:** List all chapters for a book.

**MCP tool name:** `volume_list_chapters`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `book_id` | string | no | Book ID. Optional — defaults to the book the active search cursor points at |

**Backend endpoint:** `POST /api/volume/list/chapters`

**Form fields:** `book_id`

**Returns:**
```json
{
  "name": "",
  "style": "page",
  "info_url": "",
  "chapters": [
    { "name": "Chapter 1", "value": "ch001" }
  ]
}
```

`value` is the chapter ID used in subsequent image calls.

**Side effect:** this call points the **chapter cursor** at `chapters[0]`
(single-active list cursor; see [`docs/07`](07-pagination-tools.md)). While
it is active, `volume_list_images` and `volume_get_image` may omit
`chapter_id` — they apply to the chapter the cursor points at — and
`chapter_next` / `chapter_prev` step through the book's chapters.

---

## Tool: `volume_list_images`

**Purpose:** List all image filenames for a specific chapter of a book.

**MCP tool name:** `volume_list_images`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `book_id` | string | no | Book ID. Optional — defaults to the book the active search cursor points at |
| `chapter_id` | string | no | Chapter value/ID. Optional — defaults to the chapter the active chapter/image cursor points at |

**Backend endpoint:** `POST /api/volume/list/images`

**Query string:** `?include_sizes=false`

**Form fields:** `book_id`, `chapter_id`

**Returns:**
```json
{
  "files": ["001.jpg", "002.jpg"],
  "prev": "ch000",
  "next": "ch002",
  "style": "page"
}
```

**Cover image convention:** There is no dedicated cover field on a book.  
The first entry in `files[0]` of the first chapter is treated as the cover image.  
To get the cover: call `volume_list_chapters`, take `chapters[0].value`, call `volume_list_images`, take `files[0]`, then call `volume_get_image`.

**Side effect:** this call points the **image cursor** at `files[0]`
(single-active list cursor; see [`docs/07`](07-pagination-tools.md)). While
it is active, `volume_get_image` may omit `filename` — it fetches the image
the cursor points at — and `image_next` / `image_prev` step through the
chapter's files.

---

## Tool: `volume_get_image`

**Purpose:** Retrieve a single image from a book's chapter by filename.

**MCP tool name:** `volume_get_image`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `book_id` | string | no | Book ID. Optional — defaults to the book the active search cursor points at |
| `chapter_id` | string | no | Chapter ID. Optional — defaults to the chapter the active chapter/image cursor points at |
| `filename` | string | no | Image filename (e.g. `001.jpg`). Optional — defaults to the file the active image cursor points at |

With all three omitted, the call fetches the image the cursor stack points
at: the search cursor's book → the chapter cursor's chapter → the image
cursor's file. After `volume_list_chapters` + `volume_list_images` with no
arguments, `volume_get_image()` with no arguments returns the book's cover.

**Backend endpoint:** `GET /api/volume/serve_image/{book_id}/{chapter_id}/{filename}`

(The doc previously listed a fictional `GET /api/volume/image` query-string endpoint — verified 404 live. The `?t=<n>` cache-buster suffix seen in browser URLs is optional and not required by the API.)

**Auth:** Bearer token in header

**Returns:** MCP `ImageContent` block. `mimeType` is resolved from the image's magic bytes (the server's `Content-Type` header can be wrong, e.g. reports `image/webp` for a PNG), then the response header, then the filename extension.

The tool returns a **list containing one `ImageContent` and one `TextContent`**:

```
[
  ImageContent(type="image", data="...", mimeType="image/jpeg"),
  TextContent(type="text",  text='{"book_id":"...","chapter_id":"...","filename":"..."}')
]
```

The `TextContent` carries the identifier metadata so the agent knows which image it received.  
The `ImageContent` is passed directly to a vision-capable model without any re-encoding by the agent.

MIME type is inferred from the filename extension (`.jpg`/`.jpeg` → `image/jpeg`, `.png` → `image/png`, `.webp` → `image/webp`). Defaults to `image/jpeg`.

---

## Tool: `volume_update_title`

**Purpose:** Update the display name (title) of a book.

**MCP tool name:** `volume_update_title`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `book_id` | string | no | Book ID. Optional — defaults to the book the active search cursor points at |
| `name` | string | yes | New title |

**Implementation:** calls `volume_get_book(book_id)` to fetch the full `BookDefinition`, updates the `name` field, then posts the full object to `POST /api/volume/update`.

**Backend endpoint:** `POST /api/volume/update`

**Form fields (full book definition required):**

| Field | Value |
|---|---|
| `id` | book_id (unchanged) |
| `name` | new title |
| `processor` | from fetched book |
| `active` | from fetched book |
| `info_url` | from fetched book |
| `rss_url` | from fetched book |
| `extra_url` | from fetched book |
| `start_chapter` | from fetched book |
| `skip` | from fetched book |
| `rating` | from fetched book |
| `tags` | comma-joined from fetched book |
| `style` | from fetched book |
| `alt_name` | from fetched book |

**Returns:**
```json
{ "success": true, "message": "" }
```

---

## Tool: `volume_update_alt_name`

**Purpose:** Update the alternative name / description of a book.

**MCP tool name:** `volume_update_alt_name`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `book_id` | string | no | Book ID. Optional — defaults to the book the active search cursor points at |
| `alt_name` | string | yes | New alternative name |

**Implementation:** same fetch-then-update pattern as `volume_update_title`, changing only `alt_name`.

**Backend endpoint:** `POST /api/volume/update` (same as title update)

**Returns:**
```json
{ "success": true, "message": "" }
```

---

## Tool: `volume_update_tags`

**Purpose:** Replace the tags list for a book.

**MCP tool name:** `volume_update_tags`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `book_id` | string | no | Book ID. Optional — defaults to the book the active search cursor points at |
| `tags` | array of strings | yes | Complete new tag list (replaces existing) |

**Implementation:** same fetch-then-update pattern, replacing `tags` with the provided list.

**Backend endpoint:** `POST /api/volume/update`

**Form field:** `tags` = comma-joined tag list

**Returns:**
```json
{ "success": true, "message": "" }
```

---

## Tool: `volume_update_rating`

**Purpose:** Update the rating of a book.

**MCP tool name:** `volume_update_rating`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `book_id` | string | no | Book ID. Optional — defaults to the book the active search cursor points at |
| `rating` | integer | yes | New rating value (valid range determined by the server, typically 0–5) |

**Implementation:** same fetch-then-update pattern as `volume_update_title` — fetch the full book, replace `rating`, post back.

**Backend endpoint:** `POST /api/volume/update`

**Returns:**
```json
{ "success": true, "message": "" }
```

---

## Tool: `volume_update_style`

**Purpose:** Update the display style of a book — `"page"` (discrete pages) or `"scroll"` (vertical strip, manhwa/webtoon).

**MCP tool name:** `volume_update_style`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `book_id` | string | no | Book ID. Optional — defaults to the book the active search cursor points at |
| `style` | string | yes | Display style: `"page"` or `"scroll"` |

**Implementation:** same fetch-then-update pattern as `volume_update_title` — fetch the full book, replace `style`, post back.

**Backend endpoint:** `POST /api/volume/update`

**Returns:**
```json
{ "success": true, "message": "" }
```

---

## Tool: `volume_list_tags`

**Purpose:** Fetch all available tags in the system.

**MCP tool name:** `volume_list_tags`

**Parameters:** none

**Backend endpoint:** `POST /api/volume/list/tags`

**Returns:**
```json
{ "tags": ["action", "romance", "sci-fi"] }
```

---

## Tool: `volume_guess_tags`

**Purpose:** Parse a raw tag string (comma or space separated, potentially without spaces) into canonical tags by matching against the known tag database.

**MCP tool name:** `volume_guess_tags`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `values` | string | yes | Raw tag string to parse — comma-separated, space-separated, or run-together (e.g. `"sliceofliferomance"`) |

**Backend endpoint:** `POST /api/volume/guess/tags`

**Form fields:** `values`

**Returns:**
```json
{ "tags": ["slice of life", "romance"] }
```

**How it works:** the server performs a longest-match scan of `values` against all known tags (case-insensitive). Multi-word tags like `"slice of life"` are matched before their component words, so `"sliceoflife"` correctly yields `["slice of life"]` rather than `["slice", "of", "life"]`. Words that do not match any known tag are returned as-is and treated as new tags.

**Agent guidance:**
- **Only call this tool when the input is a raw, unstructured string** — e.g. scraped metadata, vision output that produced a run-together tag blob, or user-typed free text. If the agent already has a clean list of tag strings, join them with commas and pass directly to `volume_update_tags` without calling this tool.
- Unmatched fragments may still contain punctuation or run-together characters from the original input (e.g. `"SLICE,OF,LIFE"` or `"SLICEOFLIFE"`). Before adding an unmatched entry as a new tag, normalise it: replace commas, underscores, and similar separators with spaces, then trim whitespace.
- To distinguish matched from unmatched: cross-reference the result against `volume_list_tags`. Anything not in that list is an unmatched fragment and should be normalised before use.
- If the normalised form still looks like noise (very short, all punctuation, a single stop-word), discard it rather than creating a junk tag.

---

## Tool: `volume_update_book`

**Purpose:** Update all editable fields of a book in one call.

**MCP tool name:** `volume_update_book`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `book_id` | string | no | Book ID. Optional — defaults to the book the active search cursor points at |
| `name` | string | yes | Display title |
| `alt_name` | string | yes | Alternative name / description (empty string to clear) |
| `rating` | integer | yes | Rating (0–5) |
| `tags` | array of strings | yes | Complete tag list (replaces existing) |
| `active` | boolean | yes | Whether the book is active/visible |
| `info_url` | string | yes | Primary reference URL |
| `rss_url` | string | yes | RSS feed URL (empty string if unused) |
| `extra_url` | string | yes | Secondary/base URL (empty string if unused) |
| `start_chapter` | string | yes | Starting chapter ID (empty string if unused) |
| `skip` | string | yes | Skip pattern (empty string if unused) |
| `style` | string | yes | Display style: `"page"` or `"scroll"` |
| `processor` | string | yes | Processor ID (from `volume_get_book`) |

**Backend endpoint:** `POST /api/volume/update`

**Form fields:** `id`, `name`, `alt_name`, `rating`, `tags` (comma-joined), `active` (`"true"`/`"false"`), `info_url`, `rss_url`, `extra_url`, `start_chapter`, `skip`, `style`, `processor`

**Pattern:** always fetch first with `volume_get_book(book_id)`, modify the desired fields, pass the complete set back. Never construct a book definition from scratch — unknown fields default to empty which may overwrite existing data.

**Returns:**
```json
{ "success": true, "message": "" }
```

**Agent guidance:** use the individual `volume_update_*` tools for single-field changes. Use this tool when updating multiple fields at once (e.g. after a vision pass that yields title, alt_name, tags, and rating simultaneously).

---

## Common error pattern (all volume tools)

Server responses with `status != "ok"` raise `RuntimeError(message)`.  
The MCP framework surfaces this to the AI as a tool error payload.
