"""In-memory cursors: one active search plus chapter/image list cursors.

Search cursor (books / media)
-----------------------------
- One active search at a time. Opening a new search (search_books /
  search_media / search_media_by_date) replaces any previous cursor and
  discards any active chapter/image cursor.
- The cursor steps one ITEM at a time (cursor_next / cursor_prev) — the
  server holds the position, the agent never passes a cursor_id around.
- The server fetches CHUNK_SIZE items per HTTP request. When the cursor
  runs out of fetched items it returns a sentinel (content = null plus a
  status) — it does NOT re-fetch automatically. To continue, the agent
  re-issues the same search with the `offset` carried by the sentinel.
- Sentinels:
    "exhausted"    — no more fetched items; re-search with the returned
                     offset while offset < total, otherwise the search is
                     fully complete
    "window_start" — at the first item of the current window but earlier
                     items exist; re-search with the returned (earlier)
                     offset to step further back
    "at_start"     — on the very first item of the whole search
- Envelope (normal step):
    { cursor_id, type, index, content, total }
  where type is "v" (book), "m" (media item with its own "type":
  "folder"|"file" field), or "md" (media-by-date item, same shape as "m").

List cursors (chapter / image)
------------------------------
The search cursor points at a book; two single-active list cursors
complete the navigation stack book → chapter → image:
- The chapter cursor (type "c") walks the chapters of one book. It is
  opened by volume_list_chapters, which fetches the full chapter list
  and points the cursor at the first chapter.
- The image cursor (type "i") walks the image files of one chapter. It
  is opened by volume_list_images, which fetches the full file list and
  points the cursor at the first file.
- One active list cursor at a time: opening one replaces the other.
  Opening or closing the search cursor also discards the active list
  cursor, so the book → chapter → image stack stays coherent.
- Stepping is one item at a time (chapter_next / chapter_prev,
  image_next / image_prev). The whole list is fetched on open (a book's
  chapter list and a chapter's file list are small), so there is no
  offset/resume: the only sentinels are "exhausted" (past the last
  item) and "at_start" (on the first item).
- Envelope (normal step):
    { cursor_id, type, book_id, chapter_id, index, content, total }
  where chapter_id is null on a chapter cursor, content is the chapter
  entry {name, value} on a chapter cursor and the filename string on an
  image cursor.
- While a list cursor is active, chapter_id may be omitted from
  volume_list_images / volume_get_image (chapter cursor, or the chapter
  an image cursor is scoped to) and filename from volume_get_image
  (image cursor).
"""

import uuid
from dataclasses import dataclass, field

CHUNK_SIZE = 200  # items fetched from the backend per HTTP request

STATUS_EXHAUSTED = "exhausted"
STATUS_WINDOW_START = "window_start"
STATUS_AT_START = "at_start"


@dataclass
class Cursor:
    cursor_id: str
    type: str            # "v" | "m" | "md"
    params: dict         # original search parameters (frozen after open)
    items: list = field(default_factory=list)   # current fetched window
    offset: int = 0      # server offset of items[0]
    index: int = 0       # 0-based position within items[]
    total: int = 0       # total items on the server


ACTIVE: Cursor | None = None


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


ACTIVE_LIST: ListCursor | None = None


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
    c.items = items
    c.offset = offset
    c.index = 0
    c.total = total


def _envelope(c: Cursor) -> dict:
    """Normal envelope: the item the cursor is pointing at."""
    return {
        "cursor_id": c.cursor_id,
        "type": c.type,
        "index": c.index,
        "content": c.items[c.index] if c.items else None,
        "total": c.total,
    }


def _sentinel(c: Cursor, status: str, offset: int | None = None) -> dict:
    """Sentinel envelope: no current item, plus the offset needed to continue."""
    return {
        "cursor_id": c.cursor_id,
        "type": c.type,
        "index": c.index,
        "content": None,
        "offset": c.offset + len(c.items) if offset is None else offset,
        "total": c.total,
        "status": status,
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
        "type": c.type,
        "index": c.index,
        "content": c.items[c.index] if c.items else None,
        "offset": c.offset,
        "fetched": len(c.items),
        "total": c.total,
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


# ── list cursors: chapter ("c") / image ("i") ──────────────────────────────

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
