# MCP Server — Process Tool Contracts

## Overview

The process system runs background jobs on the media server (e.g. downloads, imports, deduplication).  
Each job is a **task** with a numeric `task_id`. Workers pick tasks from a queue and run them.

The agent's typical workflow:

```
process_list()                        ← see queued / running tasks
process_get_status(task_id)           ← check progress and state flags
  loop until finished / failure
process_get_log(task_id)              ← read output after completion
```

There is no built-in wait tool — the agent polls `process_get_status` in its own loop.  
A finished task has `finished: true`. Check `failure` and `warning` to determine outcome.

---

## Task state flags

| Flag | Meaning |
|---|---|
| `waiting: true` | Task is queued, not yet picked up by a worker |
| `waiting: false`, `finished: false` | Task is actively running |
| `finished: true`, `failure: false`, `worked: true` | Completed successfully with results |
| `finished: true`, `failure: false`, `worked: false` | Completed but nothing was processed ("fruitless") |
| `finished: true`, `failure: true` | Task failed |
| `finished: true`, `warning: true` | Completed with warnings |

## Log severity levels

| Value (`s` field) | Name |
|---|---|
| `0` | Trace |
| `10` | Debug |
| `20` | Info |
| `30` | Warning |
| `40` | Error |
| `50` | Critical |
| `100` | General |

---

## Tool: `process_list`

**Purpose:** List all tasks (queued, running, and recently finished), with worker status.

**MCP tool name:** `process_list`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `page` | integer | no | `0` | Page number (0-based) |
| `page_size` | integer | no | `20` | Tasks per page |
| `extra_method` | string | no | `"NONE"` | Optional filter method passed to the server. Use `"NONE"` to return all tasks |

**Backend endpoint:** `POST /api/process/status/all/with/{extra_method}`

**Form fields:** `page`, `page_size`

**Returns:**
```json
{
  "tasks": [
    {
      "id": 42,
      "name": "Download chapter",
      "description": "...",
      "progress": 5,
      "percent": 50,
      "finished": false,
      "waiting": false,
      "worked": false,
      "failure": false,
      "warning": false,
      "priority": 0,
      "weight": 1,
      "book_id": "",
      "folder_id": "",
      "init_timestamp": "",
      "start_timestamp": "",
      "end_timestamp": ""
    }
  ],
  "workers": [
    {
      "index": 0,
      "name": "worker-0",
      "status": "running",
      "job": 42,
      "job_name": "Download chapter",
      "last_seen": 1234567890,
      "uptime": 3600
    }
  ],
  "page": 0,
  "pages": 1,
  "total": 3,
  "weight": 2
}
```

`weight` is the total queue weight of all pending tasks.

---

## Tool: `process_get_status`

**Purpose:** Get full details and log entries for a single task.

**MCP tool name:** `process_get_status`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `task_id` | integer | yes | — | Task ID |
| `log_page` | integer | no | `0` | Log page (0-based) |
| `log_page_size` | integer | no | `0` | Log entries per page. Pass `0` to omit log from response |
| `include_files` | boolean | no | `false` | Include the list of output files produced by the task |

**Backend endpoint:** `POST /api/process/status/{task_id}`

**Form fields:** `log_page_size`, `log_page` (only sent when `log_page_size > 0`), `include_files`

**Returns:**
```json
{
  "id": 42,
  "name": "",
  "description": "",
  "progress": 10,
  "percent": 100,
  "finished": true,
  "waiting": false,
  "worked": true,
  "failure": false,
  "warning": false,
  "logging": 20,
  "delay_duration": 0,
  "running_duration": 120,
  "total_duration": 125,
  "init_timestamp": "",
  "start_timestamp": "",
  "end_timestamp": "",
  "book_id": "",
  "folder_id": "",
  "priority": 0,
  "weight": 1,
  "log": [
    { "s": 20, "time": 1234567890, "text": "Started processing", "fmt": "txt" }
  ],
  "log_total": 15,
  "log_pages": 2,
  "log_page": 0,
  "log_page_size": 10,
  "files": []
}
```

**Agent polling guidance:**
- Poll with `log_page_size=0` while the task is running to avoid fetching large logs repeatedly.
- Once `finished: true`, call again with `log_page_size=50` (or use `process_get_log`) to read the output.
- Recommended poll interval: 3–5 seconds for active tasks.

---

## Tool: `process_get_log`

**Purpose:** Retrieve the full log of a task as readable text, assembled across all pages.

**MCP tool name:** `process_get_log`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `task_id` | integer | yes | — | Task ID |
| `format` | string | no | `"txt"` | Log format hint for display: `"txt"`, `"md"`, or `"json"` |
| `max_entries` | integer | no | `200` | Maximum number of log entries to return (most recent first if truncated) |

**Implementation:** calls `process_get_status` with `log_page_size=max_entries, log_page=0` and returns the `log` array formatted as a single text block.

**Backend endpoint:** `POST /api/process/status/{task_id}` (same as `process_get_status`)

**Returns:** a single `TextContent` block with the log lines rendered as:
```
[INFO]  12:34:01  Started processing
[WARN]  12:34:05  File already exists, skipping
[ERROR] 12:34:10  Failed to fetch page 3
```

Severity labels: Trace=TRACE, Debug=DEBUG, Info=INFO, Warning=WARN, Error=ERROR, Critical=CRIT, other=LOG.

---

## Tool: `process_cancel`

**Purpose:** Cancel a queued or running task.

**MCP tool name:** `process_cancel`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `task_id` | integer | yes | Task ID to cancel |

**Backend endpoint:** `POST /api/process/cancel/{task_id}`

**Returns:**
```json
{ "success": true, "message": "" }
```

**Note:** Cancelling an already-finished task is a no-op on most server implementations — the server may return success regardless.

---

## Tool: `process_stop_server`

> ⚠️ **DANGEROUS — use with extreme caution.**  
> This stops the entire background worker process on the media server.  
> All running and queued tasks will be terminated. The server will not process any further jobs until restarted.  
> **The agent must not call this tool unless the user has explicitly requested it.**

**MCP tool name:** `process_stop_server`

**Parameters:** none

**Backend endpoint:** `POST /api/process/stop`

**Returns:**
```json
{ "success": true, "message": "" }
```

---

## Tool: `process_restart_server`

> ⚠️ **DANGEROUS — use with extreme caution.**  
> This restarts the background worker process on the media server.  
> Running tasks will be interrupted. The queue resumes after the restart completes.  
> **The agent must not call this tool unless the user has explicitly requested it.**

**MCP tool name:** `process_restart_server`

**Parameters:** none

**Backend endpoint:** `POST /api/process/restart`

**Returns:**
```json
{ "success": true, "message": "" }
```

---

## Agent workflow: submitting a task and waiting

Some other tools (e.g. plugin execution, future volume download tools) return a `task_id` when they start a background job. Once you have a `task_id`:

```
1. process_get_status(task_id, log_page_size=0)
      → check finished flag
      → if not finished: wait 3-5 seconds, repeat

2. When finished=true:
      → check failure flag
      → call process_get_log(task_id) to read output
      → if files present: call process_get_status(task_id, include_files=true)
```

There is no server-side wait endpoint — the agent must poll.
