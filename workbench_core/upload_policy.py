"""Upload validation and filename normalization shared by both services."""

from __future__ import annotations

from pathlib import Path

ALLOWED_UPLOAD_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".txt", ".csv", ".json", ".xml",
    ".md", ".xlsx", ".pptx", ".xls", ".rtf", ".html", ".htm",
}


def is_allowed_upload(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_UPLOAD_EXTENSIONS


def normalize_markdown_filename(filename: str) -> str:
    """Return a markdown filename with exactly one `.md` extension."""
    safe_name = Path(filename).name
    stem = safe_name
    while stem.lower().endswith(".md"):
        stem = stem[:-3]
    stem = stem.rstrip(".")
    if not stem:
        return "document.md"
    base = Path(stem).stem if Path(stem).suffix else stem
    base = base.rstrip(".")
    if not base:
        base = "document"
    return f"{base}.md"
