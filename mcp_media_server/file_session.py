"""In-memory file browsing context for stateful folder navigation."""

from dataclasses import dataclass, field


@dataclass
class FileContext:
    folder_id:   str
    folder_name: str
    files:       list
    index:       int


# Module-level singleton; None when no folder has been opened this session.
CONTEXT: FileContext | None = None


def clear() -> None:
    global CONTEXT
    CONTEXT = None
