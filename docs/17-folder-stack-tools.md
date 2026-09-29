# MCP Server — Folder Stack Tool Contracts

These tools provide a **server-side folder stack** for depth-first traversal of
the media folder tree without the agent having to hold the stack in its own
context window.

The stack is stored **in-memory** in the MCP server process, lost on restart —
the same behaviour as search cursors and the book reading context.

Multiple independent stacks are supported simultaneously, each identified by a
`stack_id`. This allows different agents or tasks to crawl different parts of
the tree concurrently without interfering with each other.

---

## Stack state

Each stack is a named object in `folder_stack.py`:

```python
@dataclass
class FolderStack:
    stack_id: str      # uuid4 hex
    items:    list     # list of folder ID strings, last element = top of stack

# Module-level store
STACKS: dict[str, FolderStack] = {}
```

`items[-1]` is the top (next to pop). `items[0]` is the bottom (added first).

---

## Tool: `folder_stack_create`

**Purpose:** Create a new empty folder stack and optionally seed it with the
subfolders of a starting folder.

**MCP tool name:** `folder_stack_create`

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `seed_folder_id` | string | no | `""` | If provided, immediately push all direct subfolders of this folder onto the new stack. `""` = root. |

**Behaviour:**
1. Generate a new `stack_id` (uuid4).
2. Create an empty `FolderStack` and store in `STACKS`.
3. If `seed_folder_id` is provided (including `""`), call `media_client.list_media` with `folder_id=seed_folder_id` and push all returned folder IDs onto the stack. Paginate until all subfolders are collected.
4. Return the stack summary.

**Returns:**
```json
{
  "stack_id": "a1b2c3d4...",
  "depth": 12,
  "empty": false
}
```

`depth` is the number of folder IDs currently on the stack.

**Agent guidance:**
- Seed with `""` to start a full-tree crawl from root.
- Seed with a specific folder ID to crawl only a subtree.
- Call `folder_stack_push_children` after popping each folder to keep the crawl
  going (see below).

---

## Tool: `folder_stack_push_children`

**Purpose:** List all direct subfolders of a given folder and push their IDs
onto an existing stack.

**MCP tool name:** `folder_stack_push_children`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `stack_id` | string | yes | Stack to push onto |
| `folder_id` | string | yes | Folder whose children to enumerate and push |

**Behaviour:**
1. Look up `stack_id` in `STACKS`; raise `RuntimeError("Stack not found")` if missing.
2. Call `media_client.list_media(folder_id=folder_id)` — paginate until all subfolders are fetched (handles folders with more than 100 children).
3. Push each child folder's `id` onto `stack.items`.
4. Return the stack summary plus the count of folders pushed.

**Returns:**
```json
{
  "stack_id": "a1b2c3d4...",
  "pushed": 5,
  "depth": 17,
  "empty": false
}
```

**Agent guidance:**
- Call this immediately after popping a folder, before processing its files,
  so its children are queued for later visits.
- If the folder has no subfolders, `pushed` will be `0` — this is normal for
  leaf folders.

---

## Tool: `folder_stack_pop`

**Purpose:** Remove and return the top folder ID from the stack.

**MCP tool name:** `folder_stack_pop`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `stack_id` | string | yes | Stack to pop from |

**Behaviour:**
1. Look up `stack_id`; raise `RuntimeError("Stack not found")` if missing.
2. If `stack.items` is empty, return `{ "empty": true, "stack_id": "..." }`.
3. Otherwise pop `stack.items[-1]`, return it along with the updated stack depth.

**Returns (item available):**
```json
{
  "stack_id": "a1b2c3d4...",
  "folder_id": "f9e8d7c6...",
  "depth": 16,
  "empty": false
}
```

**Returns (stack exhausted):**
```json
{
  "stack_id": "a1b2c3d4...",
  "empty": true,
  "depth": 0
}
```

---

## Tool: `folder_stack_peek`

**Purpose:** Return the top folder ID without removing it.

**MCP tool name:** `folder_stack_peek`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `stack_id` | string | yes | Stack to inspect |

**Returns (item available):**
```json
{
  "stack_id": "a1b2c3d4...",
  "folder_id": "f9e8d7c6...",
  "depth": 16,
  "empty": false
}
```

**Returns (stack empty):**
```json
{
  "stack_id": "a1b2c3d4...",
  "empty": true,
  "depth": 0
}
```

---

## Tool: `folder_stack_close`

**Purpose:** Discard a stack and release its memory.

**MCP tool name:** `folder_stack_close`

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `stack_id` | string | yes | Stack to destroy |

**Behaviour:** remove from `STACKS`; silently ignore if already gone.

**Returns:**
```json
{ "closed": true, "stack_id": "a1b2c3d4..." }
```

---

## Typical depth-first traversal pattern

```
folder_stack_create(seed_folder_id="")
→ { stack_id, depth: N }

loop while not empty:

  folder_stack_pop(stack_id)
  → { folder_id, empty, depth }

  if empty == true:
    break

  folder_stack_push_children(stack_id, folder_id)
  → pushes subfolders of folder_id onto the stack for later visits

  <process files in folder_id here>

folder_stack_close(stack_id)
```

This is depth-first because `push_children` adds new folders to the top of the
stack, so they are visited before older siblings.

---

## Implementation — new file: `mcp_media_server/folder_stack.py`

```python
"""Server-side folder stack for depth-first media tree traversal."""

import uuid
from dataclasses import dataclass, field

@dataclass
class FolderStack:
    stack_id: str
    items:    list = field(default_factory=list)

STACKS: dict[str, FolderStack] = {}


def create(seed_folder_id: str | None, list_fn) -> dict:
    stack_id = uuid.uuid4().hex
    stack = FolderStack(stack_id=stack_id)
    STACKS[stack_id] = stack
    if seed_folder_id is not None:
        _push_children(stack, seed_folder_id, list_fn)
    return {"stack_id": stack_id, "depth": len(stack.items), "empty": len(stack.items) == 0}


def push_children(stack_id: str, folder_id: str, list_fn) -> dict:
    stack = _get(stack_id)
    pushed = _push_children(stack, folder_id, list_fn)
    return {"stack_id": stack_id, "pushed": pushed,
            "depth": len(stack.items), "empty": len(stack.items) == 0}


def pop(stack_id: str) -> dict:
    stack = _get(stack_id)
    if not stack.items:
        return {"stack_id": stack_id, "empty": True, "depth": 0}
    folder_id = stack.items.pop()
    return {"stack_id": stack_id, "folder_id": folder_id,
            "depth": len(stack.items), "empty": False}


def peek(stack_id: str) -> dict:
    stack = _get(stack_id)
    if not stack.items:
        return {"stack_id": stack_id, "empty": True, "depth": 0}
    return {"stack_id": stack_id, "folder_id": stack.items[-1],
            "depth": len(stack.items), "empty": False}


def close(stack_id: str) -> dict:
    STACKS.pop(stack_id, None)
    return {"closed": True, "stack_id": stack_id}


def _get(stack_id: str) -> FolderStack:
    if stack_id not in STACKS:
        raise RuntimeError(f"Stack not found: {stack_id}")
    return STACKS[stack_id]


def _push_children(stack: FolderStack, folder_id: str, list_fn) -> int:
    """Paginate subfolders of folder_id and push all IDs onto stack. Returns count pushed."""
    pushed = 0
    offset = 0
    limit = 100
    while True:
        result = list_fn(folder_id=folder_id, offset=offset, limit=limit)
        folders = result.get("folders", [])
        for f in folders:
            stack.items.append(f["id"])
            pushed += 1
        if len(folders) < limit:
            break
        offset += limit
    return pushed
```

The `list_fn` parameter is injected at call time in `mcp_server.py`:

```python
import folder_stack
import media_client

# inside _make_server():

@mcp.tool()
def folder_stack_create(seed_folder_id: str = "") -> dict:
    """Create a folder stack seeded with subfolders of seed_folder_id ("" = root)."""
    return folder_stack.create(seed_folder_id, media_client.list_media)

@mcp.tool()
def folder_stack_push_children(stack_id: str, folder_id: str) -> dict:
    """Push all direct subfolders of folder_id onto an existing stack."""
    return folder_stack.push_children(stack_id, folder_id, media_client.list_media)

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
```

---

## File change summary

| File | Change |
|---|---|
| `mcp_media_server/folder_stack.py` | **Create** — `FolderStack` dataclass, `STACKS` store, five functions |
| `mcp_media_server/mcp_server.py` | **Edit** — add `import folder_stack` and 5 new tool registrations |

No new dependencies required.

---

## Agent guidance

- **Always close stacks** when done. Unclosed stacks accumulate in memory for
  the process lifetime.
- `depth` in every response tells the agent how much work remains — useful for
  progress logging.
- The stack survives across many tool calls in the same session; the agent does
  not need to hold folder IDs in its own context.
- Do not reuse a `stack_id` after calling `folder_stack_close`.
