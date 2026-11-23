# MCP Server — Book Navigation Implementation Guide

> **SUPERSEDED** — `book_session.py` and the `book_*` tools were never shipped
> and have been removed. The search cursor (`07-pagination-tools.md`) plus the
> volume tools now cover this. Kept for reference only.

This document tells an implementing AI exactly what to create and where.  
Read `14-book-navigation.md` first for the full tool contracts.

---

## What to create

### 1. `mcp_media_server/book_session.py` — new file

```python
"""In-memory reading context for stateful book navigation."""

from dataclasses import dataclass, field


@dataclass
class BookContext:
    book_id:       str
    book:          dict
    chapters:      list          # [{name: str, value: str}, ...]
    chapter_index: int
    images:        list          # [filename_str, ...]
    image_index:   int


# Module-level singleton; None when no book has been selected this session.
CONTEXT: BookContext | None = None


def clear() -> None:
    global CONTEXT
    CONTEXT = None
```

No other logic lives here — all manipulation is in the tool handlers in `mcp_server.py`.

---

### 2. `mcp_media_server/mcp_server.py` — additions

#### 2a. Import

Add after the existing `import volume_client` line:

```python
import book_session
```

#### 2b. New tool block

Add a new `# --- book navigation ---` section inside `_make_server()`,
after the existing `# --- volume ---` section.

Implement the following 7 tools. The full contracts (parameters, behaviour,
return shapes) are in `14-book-navigation.md`.

```python
# --- book navigation ---

@mcp.tool()
def book_select(book_id: str) -> dict:
    """Select a book and load its first chapter into the reading context."""
    ...

@mcp.tool()
def book_get_context() -> dict:
    """Return the current book/chapter/image position (no network call)."""
    ...

@mcp.tool()
def book_next_chapter() -> dict:
    """Advance to the next chapter; returns its image list summary."""
    ...

@mcp.tool()
def book_prev_chapter() -> dict:
    """Move back to the previous chapter; returns its image list summary."""
    ...

@mcp.tool()
def book_next_image() -> object:
    """Advance to the next image; crosses chapter boundaries automatically."""
    ...

@mcp.tool()
def book_prev_image() -> object:
    """Move back to the previous image; crosses chapter boundaries automatically."""
    ...

@mcp.tool()
def book_update(
    name: str | None = None,
    alt_name: str | None = None,
    rating: int | None = None,
    tags: list[str] | None = None,
    active: bool | None = None,
    info_url: str | None = None,
    rss_url: str | None = None,
    extra_url: str | None = None,
    start_chapter: str | None = None,
    skip: str | None = None,
    style: str | None = None,
    processor: str | None = None,
) -> dict:
    """Update any fields of the selected book without supplying book_id."""
    ...
```

---

## Shared helper: `_context_summary`

Define this private helper inside `_make_server()`, before the tool definitions,
or as a module-level function in `book_session.py`:

```python
def _context_summary() -> dict:
    ctx = book_session.CONTEXT
    return {
        "book_id":       ctx.book_id,
        "name":          ctx.book.get("name", ""),
        "alt_name":      ctx.book.get("alt_name", ""),
        "rating":        ctx.book.get("rating", 0),
        "tags":          ctx.book.get("tags", []),
        "style":         ctx.book.get("style", "page"),
        "chapter_count": len(ctx.chapters),
        "chapter_index": ctx.chapter_index,
        "chapter_id":    ctx.chapters[ctx.chapter_index]["value"],
        "chapter_name":  ctx.chapters[ctx.chapter_index]["name"],
        "image_count":   len(ctx.images),
        "image_index":   ctx.image_index,
        "filename":      ctx.images[ctx.image_index] if ctx.images else "",
    }
```

---

## Implementation notes for each tool

### `book_select`

```python
global book_session.CONTEXT   # use: book_session.CONTEXT = ...

book  = volume_client.get_book(book_id)
chaps = volume_client.list_chapters(book_id)
chapters = chaps.get("chapters", [])
if not chapters:
    raise RuntimeError("Book has no chapters")

imgs  = volume_client.list_images(book_id, chapters[0]["value"])
images = imgs.get("files", [])

book_session.CONTEXT = book_session.BookContext(
    book_id=book_id,
    book=book,
    chapters=chapters,
    chapter_index=0,
    images=images,
    image_index=0,
)
return _context_summary()
```

### `book_get_context`

```python
if book_session.CONTEXT is None:
    return {"error": "No book selected — call book_select first"}
return _context_summary()
```

### `book_next_chapter`

```python
ctx = book_session.CONTEXT
if ctx is None:
    raise RuntimeError("No book selected — call book_select first")
if ctx.chapter_index + 1 >= len(ctx.chapters):
    ch = ctx.chapters[ctx.chapter_index]
    return {"done": True, "chapter_index": ctx.chapter_index,
            "chapter_id": ch["value"], "chapter_name": ch["name"]}
ctx.chapter_index += 1
imgs = volume_client.list_images(ctx.book_id, ctx.chapters[ctx.chapter_index]["value"])
ctx.images = imgs.get("files", [])
ctx.image_index = 0
return _context_summary()
```

### `book_prev_chapter`

Mirror of `book_next_chapter`:  
- If `chapter_index == 0` return `{"at_start": True, ...}`.  
- Otherwise decrement `chapter_index`, reload images, reset `image_index = 0`.

### `book_next_image`

```python
ctx = book_session.CONTEXT
if ctx is None:
    raise RuntimeError("No book selected — call book_select first")

if ctx.image_index + 1 < len(ctx.images):
    ctx.image_index += 1
elif ctx.chapter_index + 1 < len(ctx.chapters):
    ctx.chapter_index += 1
    imgs = volume_client.list_images(ctx.book_id, ctx.chapters[ctx.chapter_index]["value"])
    ctx.images = imgs.get("files", [])
    ctx.image_index = 0
else:
    return {"done": True}

chapter_id = ctx.chapters[ctx.chapter_index]["value"]
filename   = ctx.images[ctx.image_index]
info = volume_client.get_image(ctx.book_id, chapter_id, filename)
return [
    ImageContent(type="image", data=info["image_base64"], mimeType=info["mime_type"]),
    TextContent(type="text", text=json.dumps({
        "book_id":       ctx.book_id,
        "chapter_id":    chapter_id,
        "chapter_name":  ctx.chapters[ctx.chapter_index]["name"],
        "chapter_index": ctx.chapter_index,
        "filename":      filename,
        "image_index":   ctx.image_index,
        "image_count":   len(ctx.images),
    })),
]
```

### `book_prev_image`

Mirror of `book_next_image`:  
- If `image_index > 0`: decrement.  
- Else if `chapter_index > 0`: decrement chapter, reload images, set `image_index = len(images) - 1`.  
- Else return `{"at_start": True}`.

### `book_update`

```python
ctx = book_session.CONTEXT
if ctx is None:
    raise RuntimeError("No book selected — call book_select first")

# Build modifications from non-None parameters only
modifications = {k: v for k, v in {
    "name": name, "alt_name": alt_name, "rating": rating, "tags": tags,
    "active": active, "info_url": info_url, "rss_url": rss_url,
    "extra_url": extra_url, "start_chapter": start_chapter,
    "skip": skip, "style": style, "processor": processor,
}.items() if v is not None}

result = volume_client._apply_update(ctx.book, modifications)
# Refresh cached book metadata so book_get_context reflects the change
ctx.book = volume_client.get_book(ctx.book_id)
return result
```

---

## File change summary

| File | Change |
|---|---|
| `mcp_media_server/book_session.py` | **Create** — `BookContext` dataclass + `CONTEXT` singleton |
| `mcp_media_server/mcp_server.py` | **Edit** — add `import book_session` and 7 new tool functions |

No other files need to change.  
No new dependencies are required — `book_session.py` uses only the standard library.

---

## Live-shape deviations discovered during implementation

The live server's actual response shapes differ from what the pseudocode
assumes. The implementation follows the live shapes:

1. **Chapter id comes from `name`, not `value`.** On the live server,
   `list_chapters` returns `chapters: [{name: "0019", value: ""}, ...]` —
   `value` is always an empty string and `name` is the actual chapter id.
   All `chapter_id` derivations (`list_images`, `get_image`, summary output)
   therefore use `chapters[i]["name"]`, and the summary's `chapter_id` and
   `chapter_name` fields are identical.
2. **`get_book` nests metadata under `info`.** The response is
   `{"info": {...book metadata...}, "message": ..., "status": ...}`.
   A `_book_info(details)` helper in `volume_client.py` flattens it
   (`details.get("info", details)`); `book_select` and `book_update`
   call it, because `_apply_update` expects a flat book dict.
3. **Empty-image chapters are guarded.** A chapter with no files makes
   plain `ctx.images[ctx.image_index]` index out of range, so
   `book_next_image` / `book_prev_image` check the index bounds after
   every movement step and return `{"done": true}` / `{"at_start": true}`
   instead.

---

## Consistency checks before submitting

- `book_session.CONTEXT` is only written in `book_select`; all other tools read it.
- All tools that require a selected book check `if book_session.CONTEXT is None` first.
- `images` may be an empty list for a chapter with no images — guard `image_index`
  accesses with `if ctx.images` before indexing.
- `_apply_update` is a module-level function in `volume_client.py` (not a method)
  and is callable as `volume_client._apply_update(book, modifications)`.
- The existing `volume_get_image` tool in `mcp_server.py` is unchanged — both it
  and the new `book_next_image` / `book_prev_image` call `volume_client.get_image`
  and wrap the result the same way.
