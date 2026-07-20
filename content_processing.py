"""Document processing: ADLS storage + Content Understanding markdown conversion.

Both ADLS_ACCOUNT_NAME and AZURE_ENDPOINT must be set for processing to be enabled.
When either is missing the processor reports ``enabled = False`` and callers should skip it.
"""

import asyncio
import html
import logging
import os
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from azure.identity.aio import DefaultAzureCredential
from workbench_core.upload_policy import normalize_markdown_filename

logger = logging.getLogger(__name__)

_PROTECTED_PDF_MARKERS = (
    "# this pdf file is protected",
    "this pdf document has been protected",
    "does not support opening files protected by microsoft office",
)

_PAGE_METADATA_COMMENT_RE = re.compile(
    r"<!--\s*Page(?:Header|Footer|Break|Number)[^>]*-->",
    flags=re.IGNORECASE,
)
_TABLE_RE = re.compile(r"<table\b[^>]*>(.*?)</table>", flags=re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", flags=re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", flags=re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _markdown_preview(markdown: str, limit: int = 240) -> str:
    compact = " ".join(markdown.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _diagnose_markdown(markdown: str) -> str | None:
    lower = markdown.lower()
    if all(marker in lower for marker in _PROTECTED_PDF_MARKERS):
        return "protected_pdf_placeholder"
    return None


def _normalize_table_cell(raw: str) -> str:
    text = raw.replace("<br>", "<br />").replace("<br/>", "<br />")
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = " ".join(text.split())
    return text.replace("|", "\\|")


def _html_table_to_markdown(match: re.Match[str]) -> str:
    rows = []
    for row_html in _ROW_RE.findall(match.group(1)):
        cells = [_normalize_table_cell(cell) for cell in _CELL_RE.findall(row_html)]
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    header = normalized_rows[0]
    separator = ["---"] * width
    body = normalized_rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def normalize_markdown_output(markdown: str) -> str:
    cleaned = _PAGE_METADATA_COMMENT_RE.sub("", markdown)
    cleaned = _TABLE_RE.sub(_html_table_to_markdown, cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + ("\n" if cleaned.strip() else "")


class ContentProcessor:
    """Uploads originals to ADLS and converts documents to markdown via Content Understanding."""

    def __init__(self):
        self._adls_account = os.getenv("ADLS_ACCOUNT_NAME")
        self._adls_filesystem = os.getenv("ADLS_FILESYSTEM", "documents")
        self._cu_endpoint = self._derive_cu_endpoint()

        self._credential: DefaultAzureCredential | None = None
        self._adls_client = None  # DataLakeServiceClient
        self._filesystem_client = None  # FileSystemClient
        self._cu_client = None  # ContentUnderstandingClient

    @property
    def enabled(self) -> bool:
        return self._filesystem_client is not None and self._cu_client is not None

    @staticmethod
    def _derive_cu_endpoint() -> str | None:
        """Derive the Content Understanding endpoint from AZURE_ENDPOINT.

        AZURE_ENDPOINT is typically something like
        ``https://myresource.cognitiveservices.azure.com/openai/v1/``
        or ``https://myresource.services.ai.azure.com/openai/v1/``.
        Content Understanding just needs the origin (scheme + host).

        Returns ``None`` if AZURE_ENDPOINT is not set or cannot be parsed.
        """
        raw = os.getenv("AZURE_ENDPOINT")
        if not raw:
            return None
        parsed = urlparse(raw)
        if parsed.scheme and parsed.hostname:
            return f"{parsed.scheme}://{parsed.hostname}/"
        logger.warning("Cannot derive Content Understanding endpoint from AZURE_ENDPOINT=%r", raw)
        return None

    async def initialize(self) -> None:
        if not (self._adls_account and self._cu_endpoint):
            logger.info("Content processing disabled (ADLS or CU endpoint not configured)")
            return

        managed_identity_client_id = os.getenv("AZURE_CLIENT_ID")
        self._credential = DefaultAzureCredential(
            managed_identity_client_id=managed_identity_client_id or None,
        )

        from azure.storage.filedatalake.aio import DataLakeServiceClient

        account_url = f"https://{self._adls_account}.dfs.core.windows.net"
        self._adls_client = DataLakeServiceClient(
            account_url=account_url, credential=self._credential
        )
        self._filesystem_client = self._adls_client.get_file_system_client(
            self._adls_filesystem
        )
        logger.info("ADLS connected (%s/%s)", self._adls_account, self._adls_filesystem)

        from azure.ai.contentunderstanding.aio import ContentUnderstandingClient

        self._cu_client = ContentUnderstandingClient(
            endpoint=self._cu_endpoint, credential=self._credential
        )
        logger.info("Content Understanding connected (%s)", self._cu_endpoint)

    async def close(self) -> None:
        if self._cu_client:
            await self._cu_client.close()
        if self._adls_client:
            await self._adls_client.close()
        if self._credential:
            await self._credential.close()

    async def process_document(
        self,
        session_id: str,
        filename: str,
        file_bytes: bytes,
        content_type: str,
        forward_markdown_fn: Callable[[str, bytes], Awaitable[None]],
        markdown_filename: str | None = None,
    ) -> dict:
        """Process an uploaded document — never raises, returns a result dict."""
        result = {
            "adls_original": False,
            "markdown_produced": False,
            "adls_markdown": False,
            "markdown_forwarded": False,
            "error": None,
            "error_code": None,
            "diagnostic": None,
            "markdown_preview": None,
        }

        if not self.enabled:
            result["error"] = "Content processing is not enabled"
            return result

        # 1. Upload original to ADLS
        result["adls_original"] = await self._upload_to_adls(
            f"originals/{session_id}/{filename}", file_bytes, content_type
        )

        # 2. Convert to markdown
        # Text-based files don't need CU — use content directly as markdown
        TEXT_PREFIXES = ("text/", "application/json", "application/xml", "application/csv")
        is_text = any(content_type.startswith(prefix) for prefix in TEXT_PREFIXES)
        if is_text:
            try:
                markdown = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                logger.warning("UTF-8 decode failed for %s; using replacement characters", filename)
                markdown = file_bytes.decode("utf-8", errors="replace")
        else:
            # Binary file — convert via Content Understanding
            try:
                markdown = await self._analyze_document(file_bytes)
            except Exception:
                logger.warning("Content Understanding failed for %s", filename, exc_info=True)
                markdown = None

        if markdown is None:
            result["error"] = "Content Understanding failed to produce markdown"
            return result

        markdown = normalize_markdown_output(markdown)

        result["markdown_produced"] = True
        md_filename = markdown_filename or normalize_markdown_filename(filename)
        md_bytes = markdown.encode("utf-8")
        result["markdown_size"] = len(md_bytes)
        result["markdown_filename"] = md_filename
        result["markdown_preview"] = _markdown_preview(markdown)
        result["diagnostic"] = _diagnose_markdown(markdown)

        if result["diagnostic"] == "protected_pdf_placeholder":
            result["error_code"] = "protected_pdf"
            result["error"] = (
                "This PDF appears to be protected or rights-managed, so the extracted markdown "
                "only contains a protection notice and not the document content. Upload an accessible "
                "PDF or a text-based source document."
            )
            return result

        # 3. Upload markdown to ADLS
        result["adls_markdown"] = await self._upload_to_adls(
            f"markdown/{session_id}/{md_filename}", md_bytes, "text/markdown"
        )

        # 4. Forward markdown to session container
        try:
            await forward_markdown_fn(md_filename, md_bytes)
            result["markdown_forwarded"] = True
        except Exception:
            logger.warning("Failed to forward markdown for %s", filename, exc_info=True)

        return result

    async def _upload_to_adls(self, path: str, data: bytes, content_type: str) -> bool:
        """Upload data to ADLS. Returns True on success, False on failure."""
        try:
            from azure.storage.filedatalake import ContentSettings

            file_client = self._filesystem_client.get_file_client(path)
            await file_client.upload_data(
                data, overwrite=True, content_settings=ContentSettings(content_type=content_type)
            )
            logger.info("Uploaded to ADLS: %s", path)
            return True
        except Exception:
            logger.warning("ADLS upload failed for %s", path, exc_info=True)
            return False

    async def _analyze_document(self, file_bytes: bytes) -> str | None:
        """Convert document bytes to markdown via Content Understanding.

        Returns the markdown string, or None if no content was produced.
        Raises on transport / API errors or timeout (caller is expected to catch).
        """
        poller = await self._cu_client.begin_analyze_binary(
            analyzer_id="prebuilt-layout",
            binary_input=file_bytes,
        )
        # Hard cap: CU can take 60-90s for large PDFs but should never exceed 3 minutes.
        cu_timeout = float(os.getenv("CU_TIMEOUT_SECONDS", "180"))
        result = await asyncio.wait_for(poller.result(), timeout=cu_timeout)
        if result.contents:
            return result.contents[0].markdown
        return None
