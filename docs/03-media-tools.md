# MCP Server — Media Tool Contracts

All tools in this file map to `/api/media/*` endpoints.  
Every call is authenticated via `Authorization: Bearer <token>` header.  
All list/write calls use `multipart/form-data` POST bodies.

**Access control:** the server enforces per-request access on every call. Folders and files whose `rating` exceeds the authenticated user's media rating limit (`SESSION.limits.media`) are invisible — list calls omit them and direct fetch calls return an error. This is enforced server-side; the agent cannot bypass it. Group-based folder ownership also exists on the server but is managed by the administrator and transparent to the agent.

---

## Tool: `media_list`

**Purpose:** List folders and files within a media folder (paginated).

**MCP tool name:** `media_list`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `folder_id` | string | no | `""` | ID of the folder to list; empty = root |
| `offset` | integer | no | `0` | Pagination offset |
| `limit` | integer | no | `100` | Max items to return |
| `rating_limit` | integer | no | `0` | Minimum rating filter |
| `filter_text` | string | no | `""` | Text search filter |
| `sorting` | string | no | `"AZ"` | Sort order (`AZ`, `ZA`, `DA`, `DD`) |

**Backend endpoint:** `POST /api/media/list`

**Form fields:** `folder_id`, `offset`, `limit`, `rating`, `sort`, `filter_text`, `required_tags` (empty), `hidden_tags` (empty)

**Structural rules enforced by this tool:**
- `info.parent_id` is `""` when the listed folder is a root folder (no parent).
- Root folders never contain files — only subfolders. The `files` array will always be empty when `folder_id` is `""`.
- Every file always belongs to a folder. `files` is only non-empty when a non-root `folder_id` is provided.

**Expected response fields returned to AI:**

```json
{
  "info": { "id": "", "name": "", "rating": 0, "parent_id": "" },
  "paging": { "total": 0, "offset": 0 },
  "folders": [{ "id": "", "name": "", "rating": 0, "preview": false, "active": true }],
  "files":   [{ "id": "", "folder_id": "", "name": "", "filesize": 0, "mime_type": "", "preview": false }]
}
```

`info.parent_id` is empty string when this is a root folder.

---

## Tool: `media_list_folders`

**Purpose:** Return only the folder children of a given folder (convenience wrapper).

**MCP tool name:** `media_list_folders`

**Parameters:** same as `media_list`

**Implementation:** calls `media_list` and returns only the `folders` array.

**Note:** passing `folder_id=""` (root) is valid and common — root contains only folders.

---

## Tool: `media_list_files`

**Purpose:** Return only the file children of a given folder (convenience wrapper).

**MCP tool name:** `media_list_files`

**Parameters:** same as `media_list`

**Implementation:** calls `media_list` and returns only the `files` array.

**Note:** `folder_id` is required in practice — calling with `folder_id=""` (root) will always return an empty list because root folders contain no files.

---

## Tool: `media_get_folder`

**Purpose:** Fetch full details for a single media folder.

**MCP tool name:** `media_get_folder`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `folder_id` | string | yes | Folder ID |

**Backend endpoint:** `POST /api/media/folder`

**Form fields:** `folder_id`

**Returns:** `MediaFolderDefinition` object
```json
{
  "id": "", "name": "", "rating": 0, "preview": false, "active": true,
  "parent_id": "", "tags": "", "created": "", "updated": "", "info_url": ""
}
```

`parent_id` is `""` when this is a root folder (no parent).

---

## Tool: `media_get_file`

**Purpose:** Fetch metadata for a single media file.

**MCP tool name:** `media_get_file`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `file_id` | string | yes | File ID |

**Backend endpoint:** `POST /api/media/file`

**Form fields:** `file_id`

**Returns:**
```json
{
  "id": "", "filename": "", "filesize": 0,
  "mime_type": "", "preview": false, "archive": false, "created": "",
  "folder_id": ""
}
```

`folder_id` is always present and non-empty — every file belongs to a folder.

---

## Tool: `media_download_file`

**Purpose:** Download a file from the server and save it to the local scratch directory.

**MCP tool name:** `media_download_file`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `file_id` | string | yes | File ID |

**Backend endpoint:** `GET /api/media/view?file_id=<file_id>`

**Auth:** Bearer token in header

**Behaviour:**
1. Derive the local filename: `<file_id>.<ext>` where `<ext>` is determined from the file's MIME type (fetched via `media_get_file` if not already known, or from the response `Content-Type` header).
2. If that file already exists in the scratch directory, skip the download and return the existing path.
3. Otherwise stream the response body directly to disk — never buffer the full file in memory.

**Returns:**
```json
{
  "file_id": "<file_id>",
  "local_path": "/tmp/mcp_scratch/a3f7c2d1-4b5e-4b1a-8c3e-1234567890ab.mp4",
  "mime_type": "video/mp4",
  "size_bytes": 2147483648
}
```

**Agent guidance:**
- `local_path` is an absolute path on the machine running the MCP server — pass it to other local tools or report it to the user.
- Files accumulate in scratch until the MCP server restarts (which purges files older than `max_age_days`). The agent should not delete scratch files manually.
- For large files this call may take significant time — the agent should not assume it completes instantly.

---

## Tool: `media_upload_file`

**Purpose:** Upload a local file to a media folder on the server.

**MCP tool name:** `media_upload_file`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `folder_id` | string | yes | Destination folder ID |
| `local_path` | string | yes | Absolute path to the file on the local filesystem (e.g. a scratch path) |
| `mime_type` | string | no | MIME type hint. If omitted, guessed from the file extension |

**Backend endpoint:** `POST /api/media/folder/upload/file`

**Form fields:** `folder_id`, `file` (streamed directly from `local_path` — never fully buffered in memory)

**Returns:**
```json
{ "success": true, "message": "" }
```

**Agent guidance:**
- `local_path` will typically be a path returned by `scratch_create_file` or `media_download_file`.
- The file is streamed from disk — large files are safe to upload without memory pressure.
- Verify the file exists at `local_path` before calling; a missing file raises `RuntimeError`.
- **The server determines MIME type from the file extension.** If `local_path` has no extension, `mime_type` must be provided so the MCP layer can append the correct extension to the filename sent to the server. Uploading an extensionless file without `mime_type` will likely result in the server misclassifying it.

---

## Tool: `media_migrate_file`

**Purpose:** Move a file between primary and archive storage.

**MCP tool name:** `media_migrate_file`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `file_id` | string | yes | File ID to migrate |
| `force_archive` | boolean | yes | `true` = send to archive, `false` = return to primary |

**Backend endpoint:** `POST /api/media/file/migrate`

**Form fields:** `file_id`, `force_archive` (sent as `"true"` or `"false"`)

**How to check current tier before migrating:**  
Call `media_get_file(file_id)` and read the `archive` field:
- `archive: false` → file is on primary storage
- `archive: true` → file is on archive storage

**Returns:**
```json
{ "success": true, "message": "" }
```

**Agent guidance:**
- To move to archive: `media_migrate_file(file_id, force_archive=True)`
- To return to primary: `media_migrate_file(file_id, force_archive=False)`
- Check `archive` flag first to avoid migrating a file already on the target tier.

---

## Tool: `media_get_preview`

**Purpose:** Retrieve the preview image for a media folder or file.

**MCP tool name:** `media_get_preview`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `item_id` | string | yes | ID of the folder or file |
| `has_preview` | boolean | yes | The `preview` flag from the folder/file metadata |

**Before calling this tool** the agent must read the `preview` field from the item's metadata (`media_get_folder`, `media_get_file`, or any list/search result). If `preview` is `false` there is no image on the server — do not call this tool.

**Backend endpoint:** `GET /api/media/item/preview/{item_id}`

**Auth:** Bearer token in header

**Behaviour:**
1. If `has_preview` is `false`, return immediately with `{ "has_preview": false, "item_id": "" }` — no HTTP request is made.
2. If `has_preview` is `true`, fetch the image from the server and return it as an MCP `ImageContent` block.

**Returns (no preview):**
```json
{ "has_preview": false, "item_id": "<id>" }
```

**Returns (preview available):** a list with one `ImageContent` and one `TextContent`:

```python
[
  ImageContent(type="image", data="<base64>", mimeType="image/jpeg"),
  TextContent(type="text", text='{"item_id": "...", "has_preview": true}')
]
```

MIME type is resolved from the image's magic bytes (the server's `Content-Type` header can be wrong — e.g. it reported `image/webp` for a PNG), then the response header, then defaults to `image/jpeg`.

**Agent guidance:**
- Always check `preview: true/false` in the item metadata before calling this tool.
- Works identically for folders and files — both use the item's own `id`.
- Useful for visually identifying the contents of a folder or confirming what a file contains before downloading it.

---

## Tool: `media_move_file`

**Purpose:** Move a media file into a different folder.

**MCP tool name:** `media_move_file`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `file_id` | string | yes | ID of the file to move |
| `folder_id` | string | yes | ID of the destination folder |

**Backend endpoint:** `POST /api/media/file/move`

**Form fields:** `file_id`, `folder_id`

**Returns:**
```json
{ "success": true, "message": "" }
```

**Agent guidance:** confirm the destination folder exists with `media_get_folder` before moving.

---

## Tool: `media_move_folder`

**Purpose:** Move a media folder under a different parent folder.

**MCP tool name:** `media_move_folder`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `source_id` | string | yes | ID of the folder to move |
| `folder_id` | string | yes | ID of the destination parent folder |

**Backend endpoint:** `POST /api/media/folder/move`

**Form fields:** `source_id`, `folder_id`

**Returns:**
```json
{ "success": true, "message": "" }
```

**Agent guidance:**
- `folder_id=""` moves the folder to the root level.
- Do not pass the same ID for both `source_id` and `folder_id`.

---

## Tool: `media_create_folder`

**Purpose:** Create a new media folder under a given parent.

**MCP tool name:** `media_create_folder`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `parent_id` | string | yes | — | Parent folder ID; `""` creates a root folder |
| `name` | string | yes | — | Folder name |
| `rating` | integer | no | `0` | Content rating (0–5) |
| `info_url` | string | no | `""` | External reference URL |
| `tags` | string | no | `""` | Free-text tag string |
| `active` | boolean | no | `true` | Whether the folder is active/visible |

**Backend endpoint:** `POST /api/media/folder/post`

**Form fields:** `parent_id`, `name`, `rating`, `info_url`, `active` (`"true"`/`"false"`), `tags`, `fast_tags` (send `""`)

**Returns:**
```json
{ "success": true, "message": "", "folder_id": "<new-folder-id>" }
```

`folder_id` in the response is the ID of the newly created folder.

---

## Tool: `media_update_folder`

**Purpose:** Update metadata of an existing media folder.

**MCP tool name:** `media_update_folder`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `folder_id` | string | yes | ID of the folder to update |
| `name` | string | yes | New folder name |
| `rating` | integer | yes | Content rating (0–5) |
| `info_url` | string | yes | External reference URL (empty string to clear) |
| `tags` | string | yes | Free-text tag string (empty string to clear) |
| `active` | boolean | yes | Whether the folder is active/visible |

**Backend endpoint:** `POST /api/media/folder/put`

**Form fields:** `folder_id`, `name`, `rating`, `info_url`, `active` (`"true"`/`"false"`), `tags`, `fast_tags` (send `""`)

**Pattern:** fetch first with `media_get_folder`, modify desired fields, pass the full set back.

**Returns:**
```json
{ "success": true, "message": "" }
```

---

## Tool: `media_update_file`

**Purpose:** Update the filename and/or MIME type of an existing media file.

**MCP tool name:** `media_update_file`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `file_id` | string | yes | ID of the file to update |
| `filename` | string | yes | New filename |
| `mime_type` | string | yes | MIME type (e.g. `"video/mp4"`) |

**Backend endpoint:** `POST /api/media/file/put`

**Form fields:** `file_id`, `filename`, `mime_type`

**Pattern:** fetch first with `media_get_file`, modify desired fields, pass the full set back.

**Returns:**
```json
{ "success": true, "message": "" }
```

---

## Tool: `media_set_folder_active`

**Purpose:** Activate or inactivate a media folder (toggle visibility).

**MCP tool name:** `media_set_folder_active`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `folder_id` | string | yes | ID of the folder |
| `active` | boolean | yes | `true` = activate, `false` = inactivate |

**Backend endpoint:** `POST /api/media/folder/activate` or `POST /api/media/folder/inactivate`

The endpoint path is chosen based on the `active` parameter — not a form field.

**Returns:**
```json
{ "success": true, "message": "" }
```

**Agent guidance:** inactivating a folder hides it from normal browsing but does not delete it. Use `media_get_folder` to check current `active` state before toggling.

---

## Tool: `media_upload_preview`

**Purpose:** Upload a preview image for a media folder.

**MCP tool name:** `media_upload_preview`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `folder_id` | string | yes | ID of the folder to set a preview for |
| `local_path` | string | yes | Absolute path to the image file on the local filesystem |
| `mime_type` | string | no | MIME type hint. If omitted, guessed from the file extension |

**Backend endpoint:** `POST /api/media/folder/upload/preview`

**Form fields:** `folder_id`, `image` (streamed directly from `local_path`)

**Returns:**
```json
{ "success": true, "message": "" }
```

**Agent guidance:** after uploading, the folder's `preview` flag will be `true`. Use `media_get_preview` to verify. Typical use: after a vision pass identifies a representative image for a folder, download it to scratch with `media_download_file`, then upload it here.

---

## Tool: `scratch_get_path`

**Purpose:** Return the configured scratch directory path.

**MCP tool name:** `scratch_get_path`

**Parameters:** none

**Implementation:** reads `SCRATCH_PATH` from config — no HTTP call.

**Returns:**
```json
{ "path": "/tmp/mcp_scratch" }
```

**Agent guidance:** use this when an external tool or plugin needs to know where to write output files. All files written here will be subject to the same startup purge as downloaded files.

---

## Tool: `scratch_create_file`

**Purpose:** Reserve an empty scratch file with a new UUID name and return its path.

**MCP tool name:** `scratch_create_file`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `mime_type` | string | no | `""` | MIME type used to determine the file extension (e.g. `"text/plain"`, `"video/mp4"`) |
| `extension` | string | no | `""` | Explicit extension including the dot (e.g. `".srt"`). Takes precedence over `mime_type` if both provided |

**Implementation:** generates a fresh UUID, resolves the extension from `extension` or `mime_type`, creates an empty file at `<scratch>/<uuid><ext>`, returns the path. No HTTP call.

**Returns:**
```json
{ "path": "/tmp/mcp_scratch/b7e2a4f1-9c3d-4e8b-a1f2-abcdef012345.srt" }
```

**Agent guidance:**
- Use this to reserve a path before passing it to a plugin or external process that will write the output.
- **Always provide `mime_type` or `extension`** — a scratch file with no extension cannot be uploaded to the server without the server misclassifying it. Only omit both if the file will never be uploaded.
- The file is empty on creation — the agent or external process is responsible for writing content to it.

---

## Error responses (all media tools)

If the server returns `{"status": "error", "message": "..."}` the tool raises a `RuntimeError` with that message, which the MCP framework surfaces to the AI as a tool error.
