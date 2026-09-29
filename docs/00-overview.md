# MCP Server — Media Server Bridge: Overview

## Purpose

A single-instance Model Context Protocol (MCP) server written in Python that gives a local AI agent authenticated access to a local media/volume server.  The server exposes tools mirroring the existing Angular web-client API calls found in `auth.service.ts`, `media.service.ts`, and `volume.service.ts`.

## Document index

| # | File | Contents |
|---|------|----------|
| 00 | `00-overview.md` | This file — goals, scope, document map |
| 01 | `01-architecture.md` | Component layout, auth lifecycle, error strategy |
| 02 | `02-auth-tools.md` | Authentication tool contracts |
| 03 | `03-media-tools.md` | Media (file/folder) tool contracts — list, get, download, upload, move, create, update, migrate, preview |
| 04 | `04-volume-tools.md` | Volume (book/chapter/image) tool contracts — list, get, update, import from URL |
| 05 | `05-implementation-guide.md` | Step-by-step build instructions for the implementing AI |
| 06 | `06-vision-workflow.md` | How the agent uses vision to extract and write book metadata |
| 07 | `07-pagination-tools.md` | Cursor-based pagination: `search_books`, `search_media`, `cursor_next/prev/close` |
| 08 | `08-configuration.md` | `config.json` schema — server address, HTTPS, SSL, credentials |
| 09 | `09-process-tools.md` | Process/task tools — list, status, log, cancel, stop, restart |
| 10 | `10-plugin-tools.md` | Plugin tools — list (AI and Angular), describe, run, track via process tools |
| 11 | `11-session-features.md` | Session feature flags and limits — bitmask reference, `auth_get_session_info` tool |
| 12 | `12-backend-plugin-ai-spec.md` | **Backend spec (not MCP)** — AI-friendly plugin endpoints; `action.book.import-url` plugin spec |
| 13 | `13-client-integration.md` | **Placeholder** — connecting the MCP server to OpenCode and other clients; same-machine constraint, stdio vs TCP |
| 14 | `14-book-navigation.md` | Stateful book navigation tools — `book_select`, `book_get_context`, `book_next/prev_chapter`, `book_next/prev_image`, `book_update` |
| 15 | `15-book-navigation-impl.md` | Implementation guide for the book navigation module (`book_session.py` + `mcp_server.py` additions) |
| 16 | `16-agent-character-extraction.md` | Agent script — extract character names from book images via vision and store them as tags |
| 17 | `17-folder-stack-tools.md` | Server-side folder stack tools — `folder_stack_create`, `push_children`, `pop`, `peek`, `close` for depth-first media tree traversal |
| 18 | `18-file-navigation.md` | Stateful file navigation tools — `files_open`, `files_current`, `files_next`, `files_prev`, `files_get_preview` |
| 19 | `19-file-navigation-impl.md` | Implementation guide for the file navigation module (`file_session.py` + `mcp_server.py` additions) |

## Scope (MVP)

**In scope**
- Single-threaded / single-process MCP server (stdio transport)
- JWT Bearer token auth with automatic re-login on 401 or expiry
- Full mirror of the web-client API calls needed by a reading/management AI
- All calls use `multipart/form-data` POST bodies, matching the existing backend

**Out of scope (post-MVP)**
- Multiple simultaneous sessions / thread safety
- SSE or WebSocket transport
- Progress/history tracking endpoints
- Bookmark management
- Plugin execution
- Duplicate scanning
- Hard-session / pin management
