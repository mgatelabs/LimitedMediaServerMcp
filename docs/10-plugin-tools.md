# MCP Server — Plugin Tool Contracts

## Overview

Plugins are server-side actions the agent can trigger on demand.  
Each plugin has a unique `id`, a `category`, optional typed arguments, and a `standalone` flag.

Running a plugin creates a background **process task** and returns a `task_id`.  
Use the process tools (`process_get_status`, `process_get_log`) to track completion.

```
plugin_list_ai()
  → find plugin by id / name / category with full descriptions

plugin_describe(plugin_id)
  → get deep detail and usage notes for a specific plugin

plugin_run(plugin_id, args)
  → returns task_id

process_get_status(task_id, log_page_size=0)
  → poll until finished=true

process_get_log(task_id)
  → read results
```

**Preferred discovery flow:** use `plugin_list_ai` and `plugin_describe` rather than `plugin_list`. The AI-friendly endpoints include natural-language descriptions, strip Angular UI metadata, and expose an explicit `required` flag on each argument. `plugin_list` is retained for backward compatibility with the Angular client only.

---

## Argument types

Each plugin argument (`ActionPluginArg`) has a `type` field that tells the agent what value to supply:

| Type | Expected value |
|---|---|
| `string` | Free text string |
| `integer` | Integer number as a string |
| `boolean` | `"true"` or `"false"` |
| `select` | One of the `id` values from the arg's `values` list |
| `book_id` | A valid book ID (use `volume_list_books` to find one) |
| `folder_id` | A valid media folder ID (use `search_media` to find one) |

If an argument has a `default` value it is optional — omit it to use the default.  
If `default` is `undefined`/absent the argument is required.

The `values` list on `select`-type args contains `{id, name}` pairs — pass the `id`, not the `name`.

---

## Argument metadata fields (read-only — do not pass to `plugin_run`)

Several fields on `ActionPluginArg` are metadata for the UI or server internals.  
The agent reads them to understand behaviour but **never includes them in the `args` dict** passed to `plugin_run`:

| Field | Purpose | Agent action |
|---|---|---|
| `clear_after` | UI hint — tells the web form to clear this field's value after the form is submitted. Has no effect on plugin execution. | Ignore entirely |
| `arg1`–`arg4` | Extra configuration hints passed to the server-side argument renderer (e.g. filter constraints, linked field IDs). Opaque to the agent. | Ignore entirely |
| `adv` | Marks the argument as "advanced" — shown in a collapsed section in the UI. The arg is still valid and can be passed normally. | Treat as optional; read `description` to decide if relevant |
| `prefix_lang_id` | i18n key for the argument label prefix in the web UI. | Ignore entirely |

---

## Source file handling arguments

Plugins that process or encode files (e.g. video encoding, image conversion) typically include a `select`-type argument that controls what happens to the **source file** after the plugin finishes. This is a normal plugin argument — not special metadata.

Example arg definition the agent will see in `plugin_list`:

```json
{
  "id": "source_action",
  "name": "After completion",
  "type": "select",
  "default": "keep",
  "description": "What to do with the source file after processing",
  "values": [
    { "id": "keep",   "name": "Keep source file" },
    { "id": "delete", "name": "Delete source file" },
    { "id": "move",   "name": "Move source to archive" }
  ]
}
```

**Agent guidance for destructive source actions:**
- Always read the `description` and `values` list before choosing a value.
- `"delete"` permanently removes the original file from the server. **Only choose this if the user has explicitly requested it.**
- When in doubt, use the `default` value — it is typically the safe non-destructive option (`"keep"`).
- If no `source_action` arg exists on a plugin, the plugin does not touch the source file.
- After running a plugin with `"delete"` or `"move"`, call `process_get_log` to confirm the task completed without errors before assuming the source is gone.

---

## Tool: `plugin_list_ai`

**Purpose:** List all available plugins with AI-friendly descriptions and stripped UI metadata.

**MCP tool name:** `plugin_list_ai`

**Parameters:** none

**Backend endpoint:** `POST /api/plugin/list/ai` (empty body)

**Returns:**
```json
[
  {
    "id": "action.media.preview",
    "name": "Generate Preview",
    "category": "Media",
    "standalone": false,
    "description": "Generates a preview thumbnail for a media folder.",
    "args": [
      {
        "id": "folder_id",
        "name": "Folder",
        "type": "folder_id",
        "required": true,
        "description": "The media folder to generate a preview for."
      }
    ]
  }
]
```

**Differences from `plugin_list`:** includes `description` on every plugin and argument, exposes an explicit `required` boolean, and omits all Angular UI fields (`prefix_lang_id`, `clear_after`, `arg1`–`arg4`, `adv`, `icon`).

**Agent guidance:** prefer this over `plugin_list` for all discovery tasks. Use `plugin_describe` for deeper detail on a specific plugin before running it.

---

## Tool: `plugin_describe`

**Purpose:** Get full AI-friendly detail for a single plugin, including usage notes and preconditions.

**MCP tool name:** `plugin_describe`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `plugin_id` | string | yes | The plugin `id` from `plugin_list_ai` |

**Backend endpoint:** `POST /api/plugin/describe`

**Form fields:** `plugin_id`

**Returns:**
```json
{
  "id": "action.media.preview",
  "name": "Generate Preview",
  "category": "Media",
  "standalone": false,
  "description": "Generates a preview thumbnail for a media folder.",
  "usage_notes": "Run after uploading files to a new folder. The folder must contain at least one image or video file. After completion the folder's `preview` flag will be true.",
  "args": [
    {
      "id": "folder_id",
      "name": "Folder",
      "type": "folder_id",
      "required": true,
      "description": "The media folder to generate a preview for. Must be a non-root folder containing at least one file."
    }
  ]
}
```

`usage_notes` contains preconditions, typical use patterns, and what state changes after the plugin runs.

**Agent guidance:** call this after identifying a candidate plugin via `plugin_list_ai` and before calling `plugin_run`, especially for unfamiliar plugins or those with destructive arguments.

---

## Tool: `plugin_list`

**Purpose:** List all available plugins with their full argument definitions.

**MCP tool name:** `plugin_list`

**Parameters:** none

**Backend endpoint:** `POST /api/plugin/list` (empty body)

**Returns:**
```json
[
  {
    "id": "action.book.deduplicate",
    "name": "Book Deduplicate",
    "category": "Book",
    "standalone": false,
    "icon": "manage_search",
    "args": [
      {
        "id": "book_id",
        "name": "Book",
        "type": "book_id",
        "default": null,
        "description": "The book to deduplicate",
        "values": []
      }
    ]
  }
]
```

**Agent guidance:**
- `standalone: true` means the plugin can be run without a pre-selected item (no `book_id` / `folder_id` required by context).
- `standalone: false` means the plugin operates on a specific item — look for a required `book_id` or `folder_id` arg.
- Filter by `category` to find relevant plugins: common values include `"Book"`, `"Media"`, `"Utility"`.
- Read each arg's `description` field to understand what to pass.

---

## Tool: `plugin_run`

**Purpose:** Execute a plugin and start its background task.

**MCP tool name:** `plugin_run`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `plugin_id` | string | yes | The plugin `id` from `plugin_list` |
| `args` | object | no | Key-value pairs matching the plugin's argument `id` fields. Omit optional args to use their defaults |

**Backend endpoint:** `POST /api/process/add/plugin`

**Form fields:** single field `bundle` containing the JSON string:
```json
{ "id": "<plugin_id>", "args": { "arg_id": "value", ... } }
```

The MCP layer builds the `bundle` JSON from `plugin_id` and `args` — the agent never constructs it manually.

**Returns:**
```json
{
  "success": true,
  "message": "",
  "task_id": 42
}
```

`task_id` is present when the plugin successfully enqueued a background task.  
Pass it to `process_get_status` to track progress.

**Example — run book deduplication:**
```json
plugin_run(
  plugin_id = "action.book.deduplicate",
  args      = { "book_id": "my-book-id" }
)
```

**Example — standalone plugin with no args:**
```json
plugin_run(
  plugin_id = "action.utility.cleanup",
  args      = {}
)
```

---

## Agent workflow: discover and run a plugin

```
1. plugin_list()
      → scan results for the plugin relevant to the task
      → read its args, note which have no default (required)
      → for book_id args: use volume_get_book / volume_list_books to confirm ID
      → for folder_id args: use search_media to confirm ID
      → for select args: pick from the arg's values[].id list

2. plugin_run(plugin_id, args)
      → capture task_id from response

3. process_get_status(task_id, log_page_size=0)
      → poll every 3-5 seconds until finished=true

4. process_get_log(task_id)
      → read output to confirm success or diagnose failure
```

---

## Error cases

| Situation | Behaviour |
|---|---|
| `plugin_id` not found on server | Server returns `status: error`; tool raises `RuntimeError` |
| Required arg missing from `args` | Server returns `status: error` with a message naming the missing field |
| Plugin enqueued but task fails later | `task_id` is returned; failure is visible via `process_get_status` flags |
| `task_id` absent from response | Plugin ran synchronously or failed to enqueue; check `message` field |
