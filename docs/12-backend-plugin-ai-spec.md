# Backend Spec — AI-Friendly Plugin Endpoints & Book Import from URL

## Purpose

This document is directed at the **media server backend**, not the MCP server.  
It specifies:
1. Two new endpoints for AI-friendly plugin discovery
2. A new book import workflow that allows an AI agent to create a book from a URL via the scraper server

---

## Endpoint 1: `POST /api/plugin/list/ai`

**Purpose:** Return all plugins in a format optimised for AI consumption.  
Same data as `/api/plugin/list` but with UI metadata stripped and AI-friendly fields added.

**Auth:** Bearer token (same as existing plugin endpoints)

**Request:** empty body or empty form

**Response shape:**

```json
{
  "status": "ok",
  "message": "",
  "plugins": [
    {
      "id": "action.media.preview",
      "name": "Generate Preview",
      "category": "Media",
      "standalone": false,
      "description": "Generates a preview thumbnail image for a media folder. The preview is derived from the first suitable image or video frame found in the folder.",
      "args": [
        {
          "id": "folder_id",
          "name": "Folder",
          "type": "folder_id",
          "required": true,
          "description": "The media folder to generate a preview for."
        },
        {
          "id": "source_action",
          "name": "After completion",
          "type": "select",
          "required": false,
          "default": "keep",
          "description": "What to do with the source file after processing.",
          "values": [
            { "id": "keep",   "name": "Keep source file" },
            { "id": "delete", "name": "Delete source file" },
            { "id": "move",   "name": "Move source to archive" }
          ]
        }
      ]
    }
  ]
}
```

**Differences from `/api/plugin/list`:**

| Field | `/api/plugin/list` | `/api/plugin/list/ai` |
|---|---|---|
| `description` on plugin | absent | **required** — full sentence explaining what the plugin does and what it produces |
| `description` on each arg | may be terse/absent | **required** — full sentence explaining what to pass and why |
| `required` on each arg | absent (inferred from `default`) | **explicit boolean** |
| `prefix_lang_id` | present | **omitted** |
| `clear_after` | present | **omitted** |
| `arg1`–`arg4` | present | **omitted** |
| `adv` | present | **omitted** |
| `icon` | present | **omitted** |

**Key rule:** every plugin and every argument **must** have a non-empty `description`. This is the primary signal the agent uses to decide which plugin to run and what value to pass for each argument.

---

## Endpoint 2: `POST /api/plugin/describe`

**Purpose:** Return the full AI-friendly description for a single plugin by ID.  
Useful when the agent has already identified a plugin ID and wants deep detail before running it.

**Auth:** Bearer token

**Request form fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `plugin_id` | string | yes | The plugin `id` from `plugin_list` or `plugin_list/ai` |

**Response shape:**

```json
{
  "status": "ok",
  "message": "",
  "plugin": {
    "id": "action.media.preview",
    "name": "Generate Preview",
    "category": "Media",
    "standalone": false,
    "description": "Generates a preview thumbnail image for a media folder. The preview is derived from the first suitable image or video frame found in the folder. After completion the folder's `preview` flag is set to `true`.",
    "usage_notes": "Run this after uploading files to a new folder to make the folder's preview image available. The folder must contain at least one image or video file.",
    "args": [
      {
        "id": "folder_id",
        "name": "Folder",
        "type": "folder_id",
        "required": true,
        "description": "The media folder to generate a preview for. Must be a non-root folder containing at least one file."
      },
      {
        "id": "source_action",
        "name": "After completion",
        "type": "select",
        "required": false,
        "default": "keep",
        "description": "What to do with the source file after processing. Choose 'keep' unless the user has explicitly requested deletion or archiving.",
        "values": [
          { "id": "keep",   "name": "Keep source file" },
          { "id": "delete", "name": "Delete source file" },
          { "id": "move",   "name": "Move source to archive" }
        ]
      }
    ]
  }
}
```

**Additional field: `usage_notes`**  
A freeform string giving the agent extra guidance: preconditions, typical use patterns, what state changes after the plugin runs. Not present in the list endpoint — only in the detail endpoint where there is space for it.

**Error — plugin not found:**
```json
{ "status": "error", "message": "Plugin not found: action.media.unknown" }
```

---

## Implementation notes for the backend

- Both endpoints reuse the existing auth and plugin registry infrastructure.
- `description` and `usage_notes` fields should be stored alongside the existing plugin metadata, not generated dynamically.
- The stripped fields (`prefix_lang_id`, `clear_after`, `arg1`–`arg4`, `adv`, `icon`) are UI concerns — they do not need to be removed from the existing `/api/plugin/list` endpoint, which should remain unchanged for Angular compatibility.
- `required` is derived from whether `default` is absent/null — it can be computed rather than stored separately.

---

## Part 2 — Book import from URL (plugin)

### Overview

Book creation from a URL is implemented as a **plugin**, not a direct API endpoint. This keeps the general API spartan — the agent uses the existing `plugin_run` / `process_get_status` / `process_get_log` flow it already knows.

The plugin communicates with the scraper server as part of its background process, extracts metadata, and optionally creates the book. A `preview` argument controls whether the plugin commits or just reports what it found.

Structured results (scraped metadata, created `book_id`) are written to the process log as JSON log entries (`fmt: "json"`), which the agent reads via `process_get_log`.

---

### Plugin definition

```json
{
  "id": "action.book.import-url",
  "name": "Import Book from URL",
  "category": "Book",
  "standalone": true,
  "description": "Scrapes a URL via the scraper server to extract book metadata (title, alt name, tags, style), then optionally creates the book. Use preview=true to inspect extracted metadata without committing.",
  "usage_notes": "Run with preview=true first to verify scraped metadata. If the result looks correct, run again with preview=false to create the book. The created book_id is written to the process log as a JSON entry.",
  "args": [
    {
      "id": "url",
      "name": "URL",
      "type": "string",
      "required": true,
      "description": "The page URL to scrape."
    },
    {
      "id": "processor",
      "name": "Processor",
      "type": "string",
      "required": false,
      "default": "",
      "description": "Processor ID to use for scraping. Leave empty for auto-detection. Use volume_list_processors to find valid IDs if auto-detection fails."
    },
    {
      "id": "scraped_data",
      "name": "Scraped data",
      "type": "string",
      "required": false,
      "default": "",
      "description": "Optional JSON string from a previous preview run (the 'scraped' event payload). If provided, the plugin skips the scraper call and uses this data directly. Pass the raw JSON text from the process log's scraped event."
    },
    {
      "id": "preview",
      "name": "Preview only",
      "type": "boolean",
      "required": false,
      "default": "true",
      "description": "If true, scrape and log extracted metadata but do not create the book. If false, create the book after scraping. Defaults to true — safe by default."
    },
    {
      "id": "style",
      "name": "Page style",
      "type": "select",
      "required": false,
      "default": "",
      "description": "Override the scraped page style. Leave empty to use the scraped value.",
      "values": [
        { "id": "",       "name": "Use scraped value" },
        { "id": "page",   "name": "Page (side by side)" },
        { "id": "scroll", "name": "Scroll (vertical strip)" }
      ]
    }
  ]
}
```

---

### Process log JSON entries

The plugin writes JSON log entries (`fmt: "json"`) so the agent can extract structured data.

**After successful scrape:**
```json
{ "event": "scraped", "name": "My Title", "alt_name": "原タイトル", "tags": ["action", "fantasy"], "style": "page", "info_url": "https://..." }
```

**After book created (`preview=false` only):**
```json
{ "event": "created", "book_id": "my-title-id" }
```

**On error:**
```json
{ "event": "error", "reason": "Scraper failed: could not parse title from page" }
```

**On duplicate:**
```json
{ "event": "error", "reason": "already exists", "book_id": "existing-book-id" }
```

The agent should scan log entries where `fmt == "json"` and parse `text` to extract the event and its fields.

---

### Agent workflow

```
1. plugin_run("action.book.import-url", {"url": "...", "preview": "true"})
      → task_id

2. process_get_status(task_id) — poll until finished=true

3. process_get_log(task_id)
      → find JSON entry where event=scraped
      → capture the raw JSON text as scraped_data
      → review name, alt_name, tags, style

4. If metadata looks correct:
   plugin_run("action.book.import-url", {
       "url": "...",
       "preview": "false",
       "scraped_data": "<raw JSON text from step 3>"
   })
      → task_id  (scraper is NOT called again)

5. process_get_status(task_id) — poll until finished=true

6. process_get_log(task_id)
      → find JSON entry where event=created → extract book_id

7. volume_get_book(book_id) — confirm book created correctly
```

If scraped metadata needs correction, omit `scraped_data` so the plugin re-scrapes, or use `volume_update_*` tools after step 7 to fix fields.

---

### Implementation notes for the backend

- Default `preview` to `true` — never accidentally creates a book.
- If `scraped_data` is provided and non-empty, skip the scraper call entirely and deserialise the JSON directly. Validate it has at minimum a `name` field before proceeding.
- The plugin runs as a background process and may wait in the process queue before starting. Once started, the scraper server has its own internal queue — the plugin should wait on the scraper response without imposing a hard timeout. Write progress log entries while waiting so the agent can see the task is alive.
- Auto-detection of `processor` is best-effort. Write a clear error entry if it fails, naming the URL.
- If a book with the same `info_url` already exists, write an error JSON entry with `reason: "already exists"` and the existing `book_id`, then fail without creating a duplicate.

---

## Backend checklist

### Plugin AI endpoints
- [ ] Add `description` field to plugin registry entries (plugin-level)
- [ ] Add `description` field to each argument definition
- [ ] Add `usage_notes` field to plugin registry entries
- [ ] Implement `POST /api/plugin/list/ai` — filtered/enriched list response
- [ ] Implement `POST /api/plugin/describe` — single plugin detail response
- [ ] Populate descriptions for all existing plugins

### Book import plugin
- [ ] Implement `action.book.import-url` plugin with `url`, `processor`, `preview`, `style`, `scraped_data` args
- [ ] If `scraped_data` is provided, skip scraper call and deserialise directly (validate `name` field present)
- [ ] Wire scraper server communication into the plugin's background process
- [ ] Write JSON log entries (`fmt: "json"`) for `scraped`, `created`, and `error` events
- [ ] Default `preview` to `true`
- [ ] Handle duplicate URL — log existing `book_id` with `reason: "already exists"` and fail cleanly
- [ ] Write progress log entries while waiting on scraper so the task appears alive

### Overview

The agent needs to be able to say "create a book from this URL" and have the server handle the scraping, metadata extraction, and book creation as a background process. This mirrors what a human user does via the Angular form but removes the manual steps.

The workflow involves three systems:
```
Agent → MCP server → Media server → Scraper server → Media server (creates book)
```

Two new endpoints are needed:

---

### Endpoint 3: `POST /api/volume/import/preview`

**Purpose:** Scrape a URL and return extracted metadata **without** creating a book. Allows the agent to inspect what the scraper found before committing.

**Auth:** Bearer token

**Request form fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | The page URL to scrape |
| `processor` | string | no | Processor ID hint. If omitted the server attempts auto-detection |

**Response shape:**

```json
{
  "status": "ok",
  "message": "",
  "preview": {
    "url": "https://example.com/book/my-title",
    "processor": "my-processor-id",
    "name": "My Title",
    "alt_name": "原タイトル",
    "tags": ["action", "fantasy"],
    "style": "page",
    "info_url": "https://example.com/book/my-title",
    "rss_url": "",
    "extra_url": "",
    "start_chapter": ""
  }
}
```

Fields that the scraper could not determine are returned as empty strings or empty arrays. The agent can review, correct, and then pass the result to the import endpoint.

**Error — scraper unreachable or parse failed:**
```json
{ "status": "error", "message": "Scraper failed: could not parse title from page" }
```

---

### Endpoint 4: `POST /api/volume/import/url`

**Purpose:** Scrape a URL and create a new book as a background process. Returns a `task_id` for tracking via the existing process tools.

**Auth:** Bearer token

**Request form fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | The page URL to scrape and import |
| `processor` | string | no | Processor ID hint. If omitted the server attempts auto-detection |
| `name` | string | no | Override the scraped title |
| `alt_name` | string | no | Override the scraped alternative name |
| `tags` | string | no | Override scraped tags (comma-separated) |
| `style` | string | no | Override display style: `"page"` or `"scroll"` |

Override fields allow the agent to correct scraper output from a prior `import/preview` call before committing.

**Response shape:**

```json
{
  "status": "ok",
  "message": "",
  "task_id": 87
}
```

The background process:
1. Contacts the scraper server with the URL
2. Extracts title, alt_name, tags, style, info_url, rss_url, extra_url, start_chapter
3. Applies any override fields from the request
4. Creates the book record
5. Logs each step — the agent can read the outcome via `process_get_log(task_id)`

On completion, the process log should include the created `book_id` so the agent can reference it in subsequent calls.

**Error — book already exists:**
```json
{ "status": "error", "message": "A book with this URL already exists: <book_id>" }
```

---

### Agent workflow: import a book from URL

```
1. volume_import_preview(url)
      → review extracted metadata
      → correct any fields if needed

2. volume_import_url(url, name=..., tags=..., ...)
      → capture task_id

3. process_get_status(task_id, log_page_size=0)
      → poll until finished=true

4. process_get_log(task_id)
      → read output, extract book_id from log

5. volume_get_book(book_id)
      → confirm book was created correctly
```

---

### Implementation notes for the backend

- `import/preview` is synchronous (scrapes inline, returns immediately). Keep a short timeout — if the scraper does not respond within ~10 seconds, return an error rather than hanging.
- `import/url` is asynchronous — enqueues a background process and returns `task_id` immediately.
- Both endpoints require the scraper server to be running and reachable. If the scraper is unavailable both endpoints should return a clear error rather than timing out silently.
- Auto-detection of `processor` from a URL is a best-effort heuristic — the agent should be prepared to supply `processor` explicitly if auto-detection fails. Use `volume_list_processors` (existing endpoint) to get available processor IDs.
- The created `book_id` must appear in the process log so the agent can retrieve it without a separate search.
