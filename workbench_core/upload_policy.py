"""Upload validation and filename normalization shared by both services."""

from __future__ import annotations

from pathlib import Path

ALLOWED_UPLOAD_EXTENSIONS = {
    ".md",
}


def is_allowed_upload(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_UPLOAD_EXTENSIONS
