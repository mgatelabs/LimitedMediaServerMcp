"""Server-side folder stack for depth-first media tree traversal."""

import uuid
from dataclasses import dataclass, field


@dataclass
class FolderStack:
    stack_id: str
    items: list = field(default_factory=list)


STACKS: dict[str, FolderStack] = {}


def create(seed_folder_id: str, list_fn) -> dict:
    stack_id = uuid.uuid4().hex
    stack = FolderStack(stack_id=stack_id)
    STACKS[stack_id] = stack
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
