"""In-memory pagination: cursors over books / media / media-by-date searches."""

import uuid
from dataclasses import dataclass, field

PAGE_SIZE = 20    # items returned to agent per call
CHUNK_SIZE = 200  # items fetched from backend per HTTP request


@dataclass
class Cursor:
    cursor_id: str
    domain: str          # "books" | "media" | "media_by_date"
    params: dict         # original search parameters (frozen after open)
    chunk: list = field(default_factory=list)
    chunk_offset: int = 0
    page_index: int = 0
    total: int = -1      # total items on server (-1 = unknown)


CURSORS: dict[str, Cursor] = {}


def _global_offset(cursor: Cursor) -> int:
    """Absolute offset of the first item on the current page."""
    return cursor.chunk_offset + cursor.page_index * PAGE_SIZE


def _current_page(cursor: Cursor) -> list:
    start = cursor.page_index * PAGE_SIZE
    return cursor.chunk[start:start + PAGE_SIZE]


def _needs_next_chunk(cursor: Cursor) -> bool:
    start = (cursor.page_index + 1) * PAGE_SIZE
    return start >= len(cursor.chunk)


def _needs_prev_chunk(cursor: Cursor) -> bool:
    return cursor.page_index == 0 and cursor.chunk_offset > 0


def _fetch_domain_cursor(cursor: Cursor, offset: int):
    """Return (items, total) fetched from the backend for this cursor's domain."""
    from mcp_server import _client  # shared MediaServerClient instance
    p = cursor.params
    if cursor.domain == "books":
        body = _client.books.list_books(
            offset=offset, limit=CHUNK_SIZE,
            filter_text=p.get("filter_text", ""),
            filter_tags=p.get("filter_tags", ""),
            rating_limit=p.get("rating_limit", 0),
            sorting=p.get("sorting", "AZ"),
            filter_type=p.get("filter_type", ""),
        )
        return body.get("books", []), int(body.get("paging", {}).get("total", 0))
    if cursor.domain == "media":
        body = _client.media.list_media(
            folder_id=p.get("folder_id", ""),
            offset=offset, limit=CHUNK_SIZE,
            rating_limit=p.get("rating_limit", 0),
            sorting=p.get("sorting", "AZ"),
            filter_text=p.get("filter_text", ""),
        )
        items = [{"type": "folder", **f} for f in body.get("folders", [])]
        items += [{"type": "file", **f} for f in body.get("files", [])]
        return items, int(body.get("paging", {}).get("total", 0))
    if cursor.domain == "media_by_date":
        body = _client.media.list_media_by_date(
            start_date=p.get("start_date", ""),
            end_date=p.get("end_date", ""),
            offset=offset, limit=CHUNK_SIZE,
            rating_limit=p.get("rating_limit", 0),
            sorting=p.get("sorting", "DA"),
        )
        items = [{"type": "folder", **f} for f in body.get("folders", [])]
        items += [{"type": "file", **f} for f in body.get("files", [])]
        return items, int(body.get("paging", {}).get("total", 0))
    raise ValueError(f"Unknown cursor domain: {cursor.domain}")


def _load_chunk(cursor: Cursor, offset: int) -> None:
    items, total = _fetch_domain_cursor(cursor, offset)
    cursor.chunk = items
    cursor.chunk_offset = offset
    cursor.page_index = 0
    cursor.total = total


def _has_next(cursor: Cursor) -> bool:
    if cursor.total < 0:
        return True  # total unknown — allow the attempt
    return _global_offset(cursor) + PAGE_SIZE < cursor.total


def open_cursor(domain: str, params: dict) -> dict:
    """Create a cursor, fetch the first chunk, and return the first page envelope."""
    c = Cursor(
        cursor_id=str(uuid.uuid4()),
        domain=domain,
        params=dict(params),
    )
    _load_chunk(c, 0)
    CURSORS[c.cursor_id] = c
    return _envelope(c)


def _envelope(c: Cursor) -> dict:
    return {
        "cursor_id": c.cursor_id,
        "page": c.page_index + 1,
        "total_pages": (c.total + PAGE_SIZE - 1) // PAGE_SIZE if c.total >= 0 else 0,
        "total_items": c.total,
        "has_next": _has_next(c),
        "has_prev": _global_offset(c) > 0,
        "items": _current_page(c),
    }


def next_cursor(cursor_id: str) -> dict:
    c = CURSORS.get(cursor_id)
    if c is None:
        raise RuntimeError("Cursor not found")
    if _needs_next_chunk(c):
        if c.total < 0 or c.chunk_offset + len(c.chunk) < c.total:
            _load_chunk(c, c.chunk_offset + len(c.chunk))
            if not c.chunk:
                return {"done": True, "cursor_id": cursor_id}
            if len(c.chunk) < CHUNK_SIZE:
                c.total = c.chunk_offset + len(c.chunk)
            return _envelope(c)
        return {"done": True, "cursor_id": cursor_id}
    c.page_index += 1
    return _envelope(c)


def prev_cursor(cursor_id: str) -> dict:
    c = CURSORS.get(cursor_id)
    if c is None:
        raise RuntimeError("Cursor not found")
    if c.page_index > 0:
        c.page_index -= 1
        return _envelope(c)
    if _needs_prev_chunk(c):
        prev_offset = max(0, c.chunk_offset - CHUNK_SIZE)
        _load_chunk(c, prev_offset)
        if not c.chunk:
            return {"at_start": True, "cursor_id": cursor_id}
        last = (len(c.chunk) + PAGE_SIZE - 1) // PAGE_SIZE - 1
        c.page_index = last
        return _envelope(c)
    return {"at_start": True, "cursor_id": cursor_id}


def close_cursor(cursor_id: str) -> dict:
    CURSORS.pop(cursor_id, None)
    return {"closed": True, "cursor_id": cursor_id}
