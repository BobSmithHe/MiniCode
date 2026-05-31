"""File-system paths and utilities shared across modules."""

from pathlib import Path

from ..config import WORKDIR


def safe_path(p: str, cwd: Path | None = None) -> Path:
    """Resolve *p* relative to *cwd* (or WORKDIR).  Reject paths that escape."""
    base = cwd or WORKDIR
    path = (base / p).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Path escapes workspace: {p}")
    return path
