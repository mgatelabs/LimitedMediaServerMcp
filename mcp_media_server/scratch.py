"""Local scratch directory helpers: init/purge, path resolution, file reservation."""

import mimetypes
import time
import uuid
from pathlib import Path

from mediaserver._config import ServerConfig as _ServerConfig

_sc = _ServerConfig()

_JPEG_FIXES = {".jpe": ".jpg", ".jpeg": ".jpg"}


def _ext_from_mime(mime_type: str) -> str:
    ext = mimetypes.guess_extension(mime_type) or ""
    return _JPEG_FIXES.get(ext, ext)


def init_scratch() -> None:
    """Create scratch directory and purge files older than max_age_days."""
    path = Path(_sc.scratch_path()).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - _sc.scratch_max_age_days() * 86400
    for f in path.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def get_scratch_path() -> Path:
    """Return the scratch directory path."""
    return Path(_sc.scratch_path()).expanduser().resolve()


def scratch_path_for(file_id: str, mime_type: str = "") -> Path:
    """Return the expected scratch path for a given file_id and MIME type."""
    return get_scratch_path() / f"{file_id}{_ext_from_mime(mime_type)}"


def create_scratch_file(mime_type: str = "", extension: str = "") -> Path:
    """Reserve an empty scratch file with a fresh UUID name and return its path."""
    if extension:
        ext = extension if extension.startswith(".") else f".{extension}"
    elif mime_type:
        ext = _ext_from_mime(mime_type)
    else:
        ext = ""
    path = get_scratch_path() / f"{uuid.uuid4()}{ext}"
    path.touch()
    return path
