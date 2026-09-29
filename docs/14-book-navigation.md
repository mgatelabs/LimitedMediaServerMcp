# MCP Server — Book Navigation Tool Contracts

These tools provide a **stateful reading context** that remembers the currently selected book,
its chapter list, and the current position within a chapter's image list.  
This removes the need for the AI to manually track and pass `book_id`, `chapter_id`, and
`filename` on every call during a reading session.

The reading context is stored **in-memory** in the MCP server process and is lost on restart —
the same behaviour as search cursors.

---

## Reading context state

The context is a single global object in `book_session.py`:

```python
@dataclass
class BookContext:
    book_id:       str        # currently selected book ID
    book:          dict       # full book metadata from volume_get_book
    chapters:      list       # [{name, value}, ...] from volume_list_chapters
    chapter_index: int        # 0-based index into chapters[]
    images:        list       # [filename, ...] for the current chapter
    image_index:   int        # 0-based index into images[]

# Module-level singleton; None when no book is selected
CONTEXT: BookContext | None = None
```

**Invariants:**
- `CONTEXT` is `None` until `book_select` is called successfully.
- `chapter_index` is always a valid index into `chapters`.
- `image_index` is always a valid index into `images`.
- When a chapter changes, `images` is reloaded and `image_index` resets to `0`.

---

## Tool: `book_select`

**Purpose:** Select a book and load its chapter list into the reading context.
Sets the current chapter to the first chapter and loads its image list.

**MCP tool name:** `book_select`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `book_id` | string | yes | ID of the book to select |

**Behaviour:**
1. Call `volume_client.get_book(book_id)` — raises on error.
2. Call `volume_client.list_chapters(book_id)` — raises on error.
3. Set `chapter_index = 0`.
4. Call `volume_client.list_images(book_id, chapters[0].value)`.
5. Set `image_index = 0`.
6. Store everything in `CONTEXT`.
7. Return the context summary (see below).

**Returns:**
```json
{
  "book_id": "abc123",
  "name": "My Book",
  "alt_name": "",
  "rating": 3,
  "tags": ["action"],
  "style": "page",
  "chapter_count": 12,
  "chapter_index": 0,
  "chapter_id": "ch001",
  "chapter_name": "Chapter 1",
  "image_count": 24,
  "image_index": 0,
  "filename": "001.jpg"
}
```

**Agent guidance:**
- Call this before any other `book_*` navigation tool.
- Replaces any previously selected book — calling again with a different `book_id`
  resets the context completely.
- If the book has no chapters the tool raises `RuntimeError("Book has no chapters")`.

---

## Tool: `book_get_context`

**Purpose:** Return the current reading position without making any network calls.

**MCP tool name:** `book_get_context`

**Parameters:** none

**Behaviour:** reads `CONTEXT` directly; no HTTP calls.

**Returns (context active):** same shape as `book_select` return value.

**Returns (no context):**
```json
{ "error": "No book selected — call book_select first" }
```

**Agent guidance:** use this to remind yourself of the current position after
returning from unrelated tool calls.

---

## Tool: `book_next_chapter`

**Purpose:** Advance to the next chapter and return its image list.

**MCP tool name:** `book_next_chapter`

**Parameters:** none

**Behaviour:**
1. Raise `RuntimeError("No book selected")` if `CONTEXT` is `None`.
2. If `chapter_index + 1 >= len(chapters)` return `{ "done": true }` — already at last chapter.
3. Increment `chapter_index`.
4. Call `volume_client.list_images(book_id, chapters[chapter_index].value)`.
5. Set `image_index = 0`.
6. Return context summary.

**Returns (normal):** same shape as `book_select` return value with updated chapter/image fields.

**Returns (at last chapter):**
```json
{ "done": true, "chapter_index": 11, "chapter_id": "ch012", "chapter_name": "Chapter 12" }
```

---

## Tool: `book_prev_chapter`

**Purpose:** Move back to the previous chapter and return its image list.

**MCP tool name:** `book_prev_chapter`

**Parameters:** none

**Behaviour:**
1. Raise `RuntimeError("No book selected")` if `CONTEXT` is `None`.
2. If `chapter_index == 0` return `{ "at_start": true }` — already at first chapter.
3. Decrement `chapter_index`.
4. Call `volume_client.list_images(book_id, chapters[chapter_index].value)`.
5. Set `image_index = 0`.
6. Return context summary.

**Returns (normal):** same shape as `book_select` return value.

**Returns (at first chapter):**
```json
{ "at_start": true, "chapter_index": 0, "chapter_id": "ch001", "chapter_name": "Chapter 1" }
```

---

## Tool: `book_next_image`

**Purpose:** Advance to the next image in the current chapter and return it.
Automatically advances to the next chapter when the last image of a chapter is passed.

**MCP tool name:** `book_next_image`

**Parameters:** none

**Behaviour:**
1. Raise `RuntimeError("No book selected")` if `CONTEXT` is `None`.
2. If `image_index + 1 < len(images)`:
   - Increment `image_index`.
   - Fetch and return the image.
3. Else if there is a next chapter (`chapter_index + 1 < len(chapters)`):
   - Increment `chapter_index`.
   - Reload `images` via `volume_client.list_images(...)`.
   - Set `image_index = 0`.
   - Fetch and return the first image of the new chapter.
4. Else return `{ "done": true }` — end of book.

**Returns (normal):** a list — `[ImageContent, TextContent]`:

```python
[
  ImageContent(type="image", data="<base64>", mimeType="image/jpeg"),
  TextContent(type="text", text=json.dumps({
    "book_id": "...",
    "chapter_id": "...",
    "chapter_name": "...",
    "chapter_index": 2,
    "filename": "003.jpg",
    "image_index": 2,
    "image_count": 24,
  }))
]
```

**Returns (end of book):**
```json
{ "done": true }
```

**Agent guidance:**
- The `TextContent` block gives the agent its updated position after the advance.
- When a chapter boundary is crossed the `TextContent` will reflect the new chapter.

---

## Tool: `book_prev_image`

**Purpose:** Move back to the previous image.
Automatically moves to the last image of the previous chapter when before the first image.

**MCP tool name:** `book_prev_image`

**Parameters:** none

**Behaviour:**
1. Raise `RuntimeError("No book selected")` if `CONTEXT` is `None`.
2. If `image_index > 0`:
   - Decrement `image_index`.
   - Fetch and return the image.
3. Else if there is a previous chapter (`chapter_index > 0`):
   - Decrement `chapter_index`.
   - Reload `images` via `volume_client.list_images(...)`.
   - Set `image_index = len(images) - 1`.
   - Fetch and return the last image of that chapter.
4. Else return `{ "at_start": true }` — already at first image of first chapter.

**Returns (normal):** same `[ImageContent, TextContent]` list as `book_next_image`.

**Returns (at start):**
```json
{ "at_start": true }
```

---

## Tool: `book_update`

**Purpose:** Update any editable fields of the currently selected book without
needing to supply `book_id` explicitly.

**MCP tool name:** `book_update`

**Parameters:** all optional — only supply the fields to change.

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | no | — | Display title |
| `alt_name` | string | no | — | Alternative title |
| `rating` | integer | no | — | Rating 0–5 |
| `tags` | list[string] | no | — | Full replacement tag list |
| `active` | boolean | no | — | Visibility flag |
| `info_url` | string | no | — | External reference URL |
| `rss_url` | string | no | — | RSS feed URL |
| `extra_url` | string | no | — | Additional URL |
| `start_chapter` | string | no | — | Chapter ID to start reading from |
| `skip` | string | no | — | Chapter skip pattern |
| `style` | string | no | — | `"page"` or `"scroll"` |
| `processor` | string | no | — | Processor plugin ID |

**Behaviour:**
1. Raise `RuntimeError("No book selected")` if `CONTEXT` is `None`.
2. Build a modifications dict from whichever parameters were supplied (omit unset ones).
3. Call `volume_client._apply_update(CONTEXT.book, modifications)`.
4. On success, refresh `CONTEXT.book` by calling `volume_client.get_book(CONTEXT.book_id)`.
5. Return the server response.

**Returns:**
```json
{ "success": true, "message": "" }
```

**Agent guidance:**
- Only the fields you pass are changed — unset parameters are not sent and the
  server retains existing values.
- `tags` replaces the entire tag list. To add a single tag, read the current tags
  from `book_get_context`, append the new one, then pass the full list.
- After calling `book_update` the in-memory `CONTEXT.book` is refreshed so
  subsequent `book_get_context` calls reflect the change immediately.

---

## Error responses (all book_* tools)

| Condition | Response |
|---|---|
| No book selected | `RuntimeError("No book selected — call book_select first")` |
| Backend error | `RuntimeError("<server error message>")` propagated from volume_client |
| Book has no chapters | `RuntimeError("Book has no chapters")` from `book_select` |
