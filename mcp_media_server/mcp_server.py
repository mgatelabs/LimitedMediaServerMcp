"""Limited Media Server MCP server (FastMCP).

Registers 71 tools covering auth, media, file navigation, folder stacks,
scratch, volume, process, plugin, and cursor domains. Cursor state is a
single active item-level search cursor plus single-active chapter and
image list cursors; volume tools take optional book_id / chapter_id /
filename that fall back to the cursor's current item. Single-field
volume_get_<field> tools return just one book field instead of the whole
book definition.
Run with `python mcp_server.py` (stdio transport) or
`python mcp_server.py tcp` / `python mcp_server.py http` (streamable-http).
"""

import json
import sys

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from mediaserver import MediaServerClient

import cursor_store
import file_session
import folder_stack
import scratch

_client = MediaServerClient()


def _make_server() -> FastMCP:
    mcp = FastMCP("MediaServerMCP")

    # --- auth ---

    @mcp.tool()
    def auth_login() -> dict:
        """Log in to the media server using configured credentials."""
        return _client.auth.login()

    @mcp.tool()
    def auth_renew() -> dict:
        """Renew the current session token. Falls back to login when inactive."""
        return _client.auth.renew()

    @mcp.tool()
    def auth_get_session_info() -> dict:
        """Return the current session's decoded capabilities and limits (no network call)."""
        try:
            return _client.auth.get_session_info()
        except RuntimeError as e:
            return {"error": str(e)}

    # --- media ---

    @mcp.tool()
    def media_list(folder_id: str = "", offset: int = 0, limit: int = 100, rating_limit: int = 0,
                   filter_text: str = "", sorting: str = "AZ") -> dict:
        """List folders and files in a media folder (folder_id "" = root)."""
        return _client.media.list_media(folder_id=folder_id, offset=offset, limit=limit,
                                        rating_limit=rating_limit, filter_text=filter_text,
                                        sorting=sorting)

    @mcp.tool()
    def media_list_folders(folder_id: str = "", offset: int = 0, limit: int = 100,
                           rating_limit: int = 0, filter_text: str = "",
                           sorting: str = "AZ") -> list:
        """List only the subfolders of a media folder (folder_id "" = root)."""
        return _client.media.list_media(folder_id=folder_id, offset=offset, limit=limit,
                                        rating_limit=rating_limit, filter_text=filter_text,
                                        sorting=sorting).get("folders", [])

    @mcp.tool()
    def media_list_files(folder_id: str = "", offset: int = 0, limit: int = 100,
                         rating_limit: int = 0, filter_text: str = "",
                         sorting: str = "AZ") -> list:
        """List only the files in a media folder (folder_id "" = root)."""
        return _client.media.list_media(folder_id=folder_id, offset=offset, limit=limit,
                                        rating_limit=rating_limit, filter_text=filter_text,
                                        sorting=sorting).get("files", [])

    @mcp.tool()
    def media_get_folder(folder_id: str) -> dict:
        """Get full details of one media folder."""
        return _client.media.get_folder(folder_id)

    @mcp.tool()
    def media_get_file(file_id: str) -> dict:
        """Get full details of one media file."""
        return _client.media.get_file(file_id)

    @mcp.tool()
    def media_download_file(file_id: str) -> dict:
        """Download a media file to the local scratch directory; returns its local path."""
        return _client.media.download_file(file_id, scratch.get_scratch_path())

    @mcp.tool()
    def media_upload_file(folder_id: str, local_path: str, mime_type: str = "") -> dict:
        """Upload a local file into a media folder."""
        return _client.media.upload_file(folder_id, local_path, mime_type=mime_type)

    @mcp.tool()
    def media_migrate_file(file_id: str, force_archive: bool) -> dict:
        """Migrate a media file (re-archive/normalize). force_archive forces re-archiving."""
        return _client.media.migrate_file(file_id, force_archive)

    @mcp.tool()
    def media_get_preview(item_id: str, has_preview: bool) -> object:
        """Get the preview image of a media folder or file as image content.

        Pass has_preview=true only when the item reports a preview exists;
        otherwise returns a plain no-preview marker.
        """
        info = _client.media.get_preview(item_id, has_preview)
        if not info.get("has_preview"):
            return info
        return [
            ImageContent(type="image", data=info["data"], mimeType=info["mime_type"]),
            TextContent(type="text", text=json.dumps({"item_id": item_id, "has_preview": True})),
        ]

    @mcp.tool()
    def media_move_file(file_id: str, folder_id: str) -> dict:
        """Move a media file into another folder."""
        return _client.media.move_file(file_id, folder_id)

    @mcp.tool()
    def media_move_folder(source_id: str, folder_id: str) -> dict:
        """Move a folder into another folder (folder_id "" = root)."""
        return _client.media.move_folder(source_id, folder_id)

    @mcp.tool()
    def media_create_folder(parent_id: str, name: str, rating: int = 0, info_url: str = "",
                            tags: str = "", active: bool = True) -> dict:
        """Create a new media folder under parent_id ("" = root)."""
        return _client.media.create_folder(parent_id, name, rating=rating, info_url=info_url,
                                           tags=tags, active=active)

    @mcp.tool()
    def media_update_folder(folder_id: str, name: str, rating: int, info_url: str,
                            tags: str, active: bool) -> dict:
        """Update all editable fields of a media folder."""
        return _client.media.update_folder(folder_id, name, rating, info_url, tags, active)

    @mcp.tool()
    def media_update_file(file_id: str, filename: str, mime_type: str) -> dict:
        """Update the filename and/or mime_type of a media file."""
        return _client.media.update_file(file_id, filename, mime_type)

    @mcp.tool()
    def media_set_folder_active(folder_id: str, active: bool) -> dict:
        """Activate or deactivate a media folder."""
        return _client.media.set_folder_active(folder_id, active)

    @mcp.tool()
    def media_upload_preview(folder_id: str, local_path: str, mime_type: str = "") -> dict:
        """Upload a local image as the preview of a media folder."""
        return _client.media.upload_preview(folder_id, local_path, mime_type=mime_type)

    # --- file navigation ---

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

    @mcp.tool()
    def files_open(folder_id: str) -> dict:
        """Open a folder and load its full file list into the navigation context."""
        folder = _client.media.get_folder(folder_id)
        files: list = []
        offset = 0
        limit = 100
        while True:
            result = _client.media.list_media(folder_id=folder_id, offset=offset, limit=limit)
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

    @mcp.tool()
    def files_current() -> dict:
        """Return the current file's metadata without advancing the cursor (no network call)."""
        if file_session.CONTEXT is None:
            return {"error": "No folder open — call files_open first"}
        return _file_context_summary()

    @mcp.tool()
    def files_next() -> dict:
        """Advance the cursor to the next file and return its metadata."""
        ctx = file_session.CONTEXT
        if ctx is None:
            raise RuntimeError("No folder open — call files_open first")
        if not ctx.files or ctx.index + 1 >= len(ctx.files):
            return {"done": True, "index": ctx.index, "file_count": len(ctx.files)}
        ctx.index += 1
        return _file_context_summary()

    @mcp.tool()
    def files_prev() -> dict:
        """Move the cursor back to the previous file and return its metadata."""
        ctx = file_session.CONTEXT
        if ctx is None:
            raise RuntimeError("No folder open — call files_open first")
        if not ctx.files or ctx.index == 0:
            return {"at_start": True, "index": 0, "file_count": len(ctx.files)}
        ctx.index -= 1
        return _file_context_summary()

    @mcp.tool()
    def files_get_preview() -> object:
        """Fetch the preview image for the current file."""
        ctx = file_session.CONTEXT
        if ctx is None:
            raise RuntimeError("No folder open — call files_open first")
        if not ctx.files:
            return {"has_preview": False}
        file = ctx.files[ctx.index]
        if not file.get("preview"):
            return {"has_preview": False, "file_id": file["id"],
                    "filename": file.get("filename", "")}
        info = _client.media.get_preview(file["id"], has_preview=True)
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

    # --- folder stack ---

    @mcp.tool()
    def folder_stack_create(seed_folder_id: str = "") -> dict:
        """Create a folder stack seeded with the subfolders of seed_folder_id ("" = root)."""
        return folder_stack.create(seed_folder_id, _client.media.list_media)

    @mcp.tool()
    def folder_stack_push_children(stack_id: str, folder_id: str) -> dict:
        """Push all direct subfolders of folder_id onto an existing stack."""
        return folder_stack.push_children(stack_id, folder_id, _client.media.list_media)

    @mcp.tool()
    def folder_stack_pop(stack_id: str) -> dict:
        """Pop and return the top folder ID from the stack."""
        return folder_stack.pop(stack_id)

    @mcp.tool()
    def folder_stack_peek(stack_id: str) -> dict:
        """Peek at the top folder ID without removing it."""
        return folder_stack.peek(stack_id)

    @mcp.tool()
    def folder_stack_close(stack_id: str) -> dict:
        """Discard a folder stack and release its memory."""
        return folder_stack.close(stack_id)

    # --- scratch ---

    @mcp.tool()
    def scratch_get_path() -> dict:
        """Return the local scratch directory path used for downloads and temporary files."""
        return {"path": str(scratch.get_scratch_path())}

    @mcp.tool()
    def scratch_create_file(mime_type: str = "", extension: str = "") -> dict:
        """Reserve an empty scratch file with a fresh UUID name; returns its path."""
        return {"path": str(scratch.create_scratch_file(mime_type=mime_type, extension=extension))}

    # --- volume ---

    def _book_id_from_cursor(book_id: str | None) -> str:
        """Resolve book_id from the argument, or from the active search
        cursor when it points at a book and the argument was omitted."""
        if book_id:
            return book_id
        c = cursor_store.ACTIVE
        if c is not None and c.type == "v" and c.items:
            return c.items[c.index]["id"]
        raise RuntimeError(
            "No book_id given and no active book search pointing at a book — "
            "pass book_id or run search_books first")

    def _chapter_id_from_cursor(chapter_id: str | None) -> str:
        """Resolve chapter_id from the argument, or from the active list
        cursor when the argument was omitted (the chapter cursor points at a
        chapter directly; an image cursor is scoped to one)."""
        if chapter_id:
            return chapter_id
        return cursor_store.current_chapter_id()

    def _filename_from_cursor(filename: str | None) -> str:
        """Resolve filename from the argument, or from the active image
        cursor when the argument was omitted."""
        if filename:
            return filename
        return cursor_store.current_image_filename()

    @mcp.tool()
    def volume_list_books(offset: int = 0, limit: int = 100, rating_limit: int = 0,
                          filter_text: str = "", filter_tags: str = "", sorting: str = "AZ",
                          filter_type: str = "") -> dict:
        """List books (volumes) with paging, filters, and tag filters."""
        return _client.books.list_books(offset=offset, limit=limit, rating_limit=rating_limit,
                                        filter_text=filter_text, filter_tags=filter_tags,
                                        sorting=sorting, filter_type=filter_type)

    @mcp.tool()
    def volume_get_book(book_id: str | None = None) -> dict:
        """Get full details of one book. book_id optional — defaults to the
        book the active search cursor is pointing at."""
        return _client.books.get_book(_book_id_from_cursor(book_id))

    def _book_field_from_cursor(field: str, book_id: str | None):
        """Fetch one book field, resolving book_id from the active search
        cursor when omitted."""
        book = _client.books.get_book(_book_id_from_cursor(book_id))
        return book.get(field)

    @mcp.tool()
    def volume_get_name(book_id: str | None = None) -> str:
        """Get just the book's title. book_id optional — defaults to the
        book the active search cursor is pointing at."""
        return _book_field_from_cursor("name", book_id)

    @mcp.tool()
    def volume_get_alt_name(book_id: str | None = None) -> str:
        """Get just the book's alternative name. book_id optional — defaults
        to the book the active search cursor is pointing at."""
        return _book_field_from_cursor("alt_name", book_id)

    @mcp.tool()
    def volume_get_style(book_id: str | None = None) -> str:
        """Get just the book's layout style ("page" or "scroll"). book_id
        optional — defaults to the book the active search cursor is
        pointing at."""
        return _book_field_from_cursor("style", book_id)

    @mcp.tool()
    def volume_get_tags(book_id: str | None = None) -> str:
        """Get just the book's tag list as a JSON array of strings
        (e.g. ["MC:A", "x"]; "[]" when the book has no tags). book_id
        optional — defaults to the book the active search cursor is
        pointing at."""
        tags = _book_field_from_cursor("tags", book_id)
        return json.dumps(tags if tags is not None else [])

    @mcp.tool()
    def volume_get_rating(book_id: str | None = None) -> int:
        """Get just the book's rating. book_id optional — defaults to the
        book the active search cursor is pointing at."""
        return _book_field_from_cursor("rating", book_id)

    @mcp.tool()
    def volume_get_active(book_id: str | None = None) -> bool:
        """Get just the book's active flag. book_id optional — defaults to
        the book the active search cursor is pointing at."""
        return _book_field_from_cursor("active", book_id)

    @mcp.tool()
    def volume_list_chapters(book_id: str | None = None) -> dict:
        """List all chapters of a book and point the chapter cursor at the
        first one. book_id optional — defaults to the book the active
        search cursor is pointing at."""
        bid = _book_id_from_cursor(book_id)
        body = _client.books.list_chapters(bid)
        chapters = body.get("chapters", [])
        cursor_store.open_list_cursor("c", bid, None, chapters)
        return body

    @mcp.tool()
    def volume_list_images(chapter_id: str | None = None, book_id: str | None = None) -> dict:
        """List the image files of one chapter and point the image cursor
        at the first one. chapter_id optional — defaults to the chapter the
        active chapter/image cursor points at; book_id optional — defaults
        to the book the active search cursor is pointing at."""
        bid = _book_id_from_cursor(book_id)
        cid = _chapter_id_from_cursor(chapter_id)
        body = _client.books.list_images(bid, cid)
        cursor_store.open_list_cursor("i", bid, cid, body.get("files", []))
        return body

    @mcp.tool()
    def volume_get_image(chapter_id: str | None = None, filename: str | None = None,
                         book_id: str | None = None) -> object:
        """Get one chapter image as image content with identifying metadata.
        chapter_id optional — defaults to the chapter the active
        chapter/image cursor points at; filename optional — defaults to the
        file the active image cursor is pointing at; book_id optional —
        defaults to the book the active search cursor is pointing at."""
        bid = _book_id_from_cursor(book_id)
        cid = _chapter_id_from_cursor(chapter_id)
        fname = _filename_from_cursor(filename)
        info = _client.books.get_image(bid, cid, fname)
        return [
            ImageContent(type="image", data=info["image_base64"], mimeType=info["mime_type"]),
            TextContent(type="text", text=json.dumps({
                "book_id": bid, "chapter_id": cid, "filename": fname,
            })),
        ]

    @mcp.tool()
    def volume_update_title(name: str, book_id: str | None = None) -> dict:
        """Update the title of a book. book_id optional — defaults to the
        book the active search cursor is pointing at."""
        return _client.books.update_title(_book_id_from_cursor(book_id), name)

    @mcp.tool()
    def volume_update_alt_name(alt_name: str, book_id: str | None = None) -> dict:
        """Update the alternate name of a book. book_id optional — defaults
        to the book the active search cursor is pointing at."""
        return _client.books.update_alt_name(_book_id_from_cursor(book_id), alt_name)

    @mcp.tool()
    def volume_update_tags(tags: list[str], book_id: str | None = None) -> dict:
        """Replace the full tag list of a book. book_id optional — defaults
        to the book the active search cursor is pointing at."""
        return _client.books.update_tags(_book_id_from_cursor(book_id), tags)

    @mcp.tool()
    def volume_update_rating(rating: int, book_id: str | None = None) -> dict:
        """Update the rating of a book. book_id optional — defaults to the
        book the active search cursor is pointing at."""
        return _client.books.update_rating(_book_id_from_cursor(book_id), rating)

    @mcp.tool()
    def volume_update_style(style: str, book_id: str | None = None) -> dict:
        """Update the display style of a book ("page" or "scroll"). book_id
        optional — defaults to the book the active search cursor is pointing at."""
        return _client.books.update_style(_book_id_from_cursor(book_id), style)

    @mcp.tool()
    def volume_list_tags() -> dict:
        """List all tags in use across books."""
        return _client.books.list_tags()

    @mcp.tool()
    def volume_guess_tags(values: str) -> dict:
        """Guess book tags from a free-text description."""
        return _client.books.guess_tags(values)

    @mcp.tool()
    def volume_update_book(name: str, alt_name: str, rating: int, tags: list[str],
                           active: bool, info_url: str, rss_url: str, extra_url: str,
                           start_chapter: str, skip: str, style: str, processor: str,
                           book_id: str | None = None) -> dict:
        """Update all editable fields of a book at once. All fields except
        book_id are required: pass a full book definition obtained from
        volume_get_book. book_id is optional — defaults to the book the
        active search cursor is pointing at."""
        return _client.books.update_book(_book_id_from_cursor(book_id), name, alt_name, rating, tags, active,
                                         info_url, rss_url, extra_url, start_chapter,
                                         skip, style, processor)

    # --- chapter/image cursors (list-level, single active) ---

    @mcp.tool()
    def chapter_next() -> dict:
        """Advance the chapter cursor to the next chapter of the current
        book. Envelope: { cursor_id, type: "c", book_id, chapter_id: null,
        index, content: {name, value}, total }. At the last chapter returns
        { status: "exhausted" }."""
        return cursor_store.list_next()

    @mcp.tool()
    def chapter_prev() -> dict:
        """Move the chapter cursor back one chapter. On the first chapter
        returns { status: "at_start" }."""
        return cursor_store.list_prev()

    @mcp.tool()
    def image_next() -> dict:
        """Advance the image cursor to the next file of the current
        chapter. Envelope: { cursor_id, type: "i", book_id, chapter_id,
        index, content: filename, total }. At the last file returns
        { status: "exhausted" }."""
        return cursor_store.list_next()

    @mcp.tool()
    def image_prev() -> dict:
        """Move the image cursor back one file. On the first file returns
        { status: "at_start" }."""
        return cursor_store.list_prev()

    # --- process ---

    @mcp.tool()
    def process_list(page: int = 0, page_size: int = 20, extra_method: str = "NONE") -> dict:
        """List background tasks (queued, running, recently finished) with worker status."""
        return _client.process.list_tasks(page=page, page_size=page_size,
                                          extra_method=extra_method)

    @mcp.tool()
    def process_get_status(task_id: int, log_page: int = 0, log_page_size: int = 0,
                           include_files: bool = False) -> dict:
        """Get full details of one task. Use log_page_size=0 while polling to avoid large logs."""
        return _client.process.get_status(task_id, log_page=log_page,
                                          log_page_size=log_page_size,
                                          include_files=include_files)

    @mcp.tool()
    def process_get_log(task_id: int, format: str = "txt", max_entries: int = 200) -> str:
        """Get the task log rendered as readable text (txt, md, or json)."""
        return _client.process.get_log(task_id, format=format, max_entries=max_entries)

    @mcp.tool()
    def process_cancel(task_id: int) -> dict:
        """Cancel a queued or running task."""
        return _client.process.cancel(task_id)

    @mcp.tool()
    def process_stop_server() -> dict:
        """DANGEROUS: stop the entire background worker. Only on explicit user request."""
        return _client.process.stop_server()

    @mcp.tool()
    def process_restart_server() -> dict:
        """DANGEROUS: restart the background worker, interrupting running tasks. Only on explicit user request."""
        return _client.process.restart_server()

    # --- plugin ---

    @mcp.tool()
    def plugin_list_ai() -> list:
        """List all plugins with AI-friendly descriptions (no UI metadata). Prefer over plugin_list."""
        return _client.plugins.list_ai()

    @mcp.tool()
    def plugin_describe(plugin_id: str) -> dict:
        """Get full detail for one plugin, including usage notes and preconditions."""
        return _client.plugins.describe(plugin_id)

    @mcp.tool()
    def plugin_list() -> list:
        """List all plugins with full argument definitions (includes UI metadata)."""
        return _client.plugins.list()

    @mcp.tool()
    def plugin_run(plugin_id: str, args: dict | None = None) -> dict:
        """Execute a plugin as a background task; returns the task_id for polling."""
        return _client.plugins.run(plugin_id, args)

    # --- search cursor (item-level, single active search) ---

    @mcp.tool()
    def search_books(offset: int = 0, filter_text: str = "", filter_tags: str = "",
                     rating_limit: int = 0, sorting: str = "AZ", filter_type: str = "") -> dict:
        """Start (or re-issue) the book search; replaces any previous search.
        Returns the first item: { cursor_id, type: "v", index, content, total }.
        Re-issue with the offset carried by a sentinel to continue stepping."""
        return cursor_store.search("v", {
            "filter_text":  filter_text,
            "filter_tags":  filter_tags,
            "rating_limit": rating_limit,
            "sorting":      sorting,
            "filter_type":  filter_type,
        }, offset=offset)

    @mcp.tool()
    def search_media(folder_id: str = "", offset: int = 0, filter_text: str = "",
                     rating_limit: int = 0, sorting: str = "AZ") -> dict:
        """Start (or re-issue) the media search over folders and files
        ("" = root); replaces any previous search. Returns the first item:
        { cursor_id, type: "m", index, content, total } where content has a
        "type": "folder"|"file" field. Re-issue with the offset carried by a
        sentinel to continue stepping."""
        return cursor_store.search("m", {
            "folder_id":    folder_id,
            "filter_text":  filter_text,
            "rating_limit": rating_limit,
            "sorting":      sorting,
        }, offset=offset)

    @mcp.tool()
    def search_media_by_date(start_date: str, end_date: str, offset: int = 0,
                             rating_limit: int = 0, sorting: str = "DA") -> dict:
        """Start (or re-issue) the media-by-date search; replaces any previous
        search. Returns the first item: { cursor_id, type: "md", index,
        content, total } where content has a "type": "folder"|"file" field.
        Re-issue with the offset carried by a sentinel to continue stepping."""
        return cursor_store.search("md", {
            "start_date":   start_date,
            "end_date":     end_date,
            "rating_limit": rating_limit,
            "sorting":      sorting,
        }, offset=offset)

    @mcp.tool()
    def cursor_info() -> dict:
        """Describe the active search cursor without moving it:
        { cursor_id, type, index, content, offset, fetched, total }."""
        return cursor_store.cursor_info()

    @mcp.tool()
    def cursor_next() -> dict:
        """Advance the active search to the next item. At the end of the
        fetched items returns { status: "exhausted", offset, total } —
        re-issue the search with that offset to continue."""
        return cursor_store.cursor_next()

    @mcp.tool()
    def cursor_prev() -> dict:
        """Move the active search back one item. At the start of the fetched
        items returns { status: "window_start", offset, total } (earlier items
        exist) or { status: "at_start" } on the very first item."""
        return cursor_store.cursor_prev()

    @mcp.tool()
    def cursor_close() -> dict:
        """Discard the active search cursor and any active chapter/image
        cursor."""
        return cursor_store.cursor_close()

    return mcp


scratch.init_scratch()

_server = _make_server()


def main() -> None:
    transport = "stdio"
    if len(sys.argv) > 1 and sys.argv[1] in ("tcp", "http"):
        transport = "streamable-http"
    _server.run(transport=transport)


if __name__ == "__main__":
    main()
