"""Limited Media Server MCP server (FastMCP).

Registers 49 tools covering auth, media, scratch, volume, process, plugin,
and pagination domains. Run with `python mcp_server.py` (stdio transport) or
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

    @mcp.tool()
    def volume_list_books(offset: int = 0, limit: int = 100, rating_limit: int = 0,
                          filter_text: str = "", filter_tags: str = "", sorting: str = "AZ",
                          filter_type: str = "") -> dict:
        """List books (volumes) with paging, filters, and tag filters."""
        return _client.books.list_books(offset=offset, limit=limit, rating_limit=rating_limit,
                                        filter_text=filter_text, filter_tags=filter_tags,
                                        sorting=sorting, filter_type=filter_type)

    @mcp.tool()
    def volume_get_book(book_id: str) -> dict:
        """Get full details of one book."""
        return _client.books.get_book(book_id)

    @mcp.tool()
    def volume_list_chapters(book_id: str) -> dict:
        """List all chapters of a book."""
        return _client.books.list_chapters(book_id)

    @mcp.tool()
    def volume_list_images(book_id: str, chapter_id: str) -> dict:
        """List the image files of one chapter."""
        return _client.books.list_images(book_id, chapter_id)

    @mcp.tool()
    def volume_get_image(book_id: str, chapter_id: str, filename: str) -> object:
        """Get one chapter image as image content with identifying metadata."""
        info = _client.books.get_image(book_id, chapter_id, filename)
        return [
            ImageContent(type="image", data=info["image_base64"], mimeType=info["mime_type"]),
            TextContent(type="text", text=json.dumps({
                "book_id": book_id, "chapter_id": chapter_id, "filename": filename,
            })),
        ]

    @mcp.tool()
    def volume_update_title(book_id: str, name: str) -> dict:
        """Update the title of a book."""
        return _client.books.update_title(book_id, name)

    @mcp.tool()
    def volume_update_alt_name(book_id: str, alt_name: str) -> dict:
        """Update the alternate name of a book."""
        return _client.books.update_alt_name(book_id, alt_name)

    @mcp.tool()
    def volume_update_tags(book_id: str, tags: list[str]) -> dict:
        """Replace the full tag list of a book."""
        return _client.books.update_tags(book_id, tags)

    @mcp.tool()
    def volume_update_rating(book_id: str, rating: int) -> dict:
        """Update the rating of a book."""
        return _client.books.update_rating(book_id, rating)

    @mcp.tool()
    def volume_list_tags() -> dict:
        """List all tags in use across books."""
        return _client.books.list_tags()

    @mcp.tool()
    def volume_guess_tags(values: str) -> dict:
        """Guess book tags from a free-text description."""
        return _client.books.guess_tags(values)

    @mcp.tool()
    def volume_update_book(book_id: str, name: str, alt_name: str, rating: int,
                           tags: list[str], active: bool, info_url: str, rss_url: str,
                           extra_url: str, start_chapter: str, skip: str, style: str,
                           processor: str) -> dict:
        """Update all editable fields of a book at once."""
        return _client.books.update_book(book_id, name, alt_name, rating, tags, active,
                                         info_url, rss_url, extra_url, start_chapter,
                                         skip, style, processor)

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

    # --- pagination ---

    @mcp.tool()
    def search_books(filter_text: str = "", filter_tags: str = "", rating_limit: int = 0,
                     sorting: str = "AZ", filter_type: str = "") -> dict:
        """Open a paginated cursor over books. Use cursor_next/cursor_prev/cursor_close to page."""
        return cursor_store.open_cursor("books", {
            "filter_text":  filter_text,
            "filter_tags":  filter_tags,
            "rating_limit": rating_limit,
            "sorting":      sorting,
            "filter_type":  filter_type,
        })

    @mcp.tool()
    def search_media(folder_id: str = "", filter_text: str = "", rating_limit: int = 0,
                     sorting: str = "AZ") -> dict:
        """Open a paginated cursor over media folders and files ("" = root)."""
        return cursor_store.open_cursor("media", {
            "folder_id":    folder_id,
            "filter_text":  filter_text,
            "rating_limit": rating_limit,
            "sorting":      sorting,
        })

    @mcp.tool()
    def search_media_by_date(start_date: str, end_date: str, rating_limit: int = 0,
                             sorting: str = "DA") -> dict:
        """Open a paginated cursor over media created within a date range."""
        return cursor_store.open_cursor("media_by_date", {
            "start_date":   start_date,
            "end_date":     end_date,
            "rating_limit": rating_limit,
            "sorting":      sorting,
        })

    @mcp.tool()
    def cursor_next(cursor_id: str) -> dict:
        """Advance a search cursor to the next page. Returns done=true at the end."""
        return cursor_store.next_cursor(cursor_id)

    @mcp.tool()
    def cursor_prev(cursor_id: str) -> dict:
        """Move a search cursor back one page. Returns at_start=true on the first page."""
        return cursor_store.prev_cursor(cursor_id)

    @mcp.tool()
    def cursor_close(cursor_id: str) -> dict:
        """Close a search cursor and release its resources."""
        return cursor_store.close_cursor(cursor_id)

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
