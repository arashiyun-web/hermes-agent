"""Read a public page with the core HTTP client when no extract backend can.

Search backends (SearXNG, DuckDuckGo, Brave free) do not fetch the URL the
user asked to read. Offering ``web_extract`` only when one of those is
configured left the tool either hidden or answering with a "search-only"
error, and the model then wrote the page as prose. This reader is the
fallback for that case. It does not replace a configured extract provider,
and it does not change a search backend's endpoint.
"""

from __future__ import annotations

import importlib.util
import logging
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)

_MAX_BODY_CHARS = 1_000_000
_FETCH_TIMEOUT_S = 20.0
_USER_AGENT = "HermesAgent/web-extract"


def local_extract_available() -> bool:
    """True when the core HTTP client can be imported. No network."""
    try:
        return importlib.util.find_spec("httpx") is not None
    except (ImportError, ValueError, AttributeError):
        return False


class _PageText(HTMLParser):
    """Title plus visible text. Skips script and style bodies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip or not data or not data.strip():
            return
        if self._in_title:
            self.title_parts.append(data.strip())
        else:
            self.text_parts.append(data.strip())


def page_text_from_body(body: str, content_type: str) -> tuple[str, str]:
    """``(title, text)`` from an HTTP body. Non-HTML is returned as plain text."""
    kind = (content_type or "").split(";", 1)[0].strip().lower()
    if kind and kind not in {"text/html", "application/xhtml+xml"}:
        text = body.strip()
        return "", text[:_MAX_BODY_CHARS]
    parser = _PageText()
    parser.feed(body[:_MAX_BODY_CHARS])
    parser.close()
    title = " ".join(parser.title_parts).strip()
    text = "\n".join(parser.text_parts).strip()
    return title, text[:_MAX_BODY_CHARS]


def fetch_public_page(url: str, *, timeout: float = _FETCH_TIMEOUT_S) -> tuple[str, str]:
    """GET ``url`` through the SSRF-safe client. Returns ``(content_type, body)``.

    Raises ``httpx.HTTPError`` on transport or status failure. Callers that
    already passed ``async_is_safe_url`` still use this client so a redirect
    cannot land on a private address.
    """
    from tools.url_safety import create_ssrf_safe_client

    headers = {"Accept": "text/html, text/plain;q=0.9, */*;q=0.1", "User-Agent": _USER_AGENT}
    with create_ssrf_safe_client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        return content_type, response.text[:_MAX_BODY_CHARS]


class LocalHttpExtractProvider(WebSearchProvider):
    """Extract-only reader. Not registered, so it never becomes the search backend."""

    def is_available(self) -> bool:
        return local_extract_available()

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "local-http"

    @property
    def display_name(self) -> str:
        return "Local HTTP"

    def extract(self, urls: List[str], format: Optional[str] = None) -> List[Dict[str, Any]]:
        from plugins.web._common import document, page_error

        import httpx

        pages: List[Dict[str, Any]] = []
        for url in urls:
            try:
                content_type, body = fetch_public_page(url)
                title, text = page_text_from_body(body, content_type)
            except (httpx.HTTPError, OSError, UnicodeError, ValueError) as exc:
                logger.info("local web extract failed for %s: %s", url, exc)
                pages.append(page_error(url, f"Local fetch failed: {exc}"))
                continue
            if not text and not title:
                pages.append(page_error(url, "Page returned no readable text"))
            else:
                pages.append(document(url, title, text or title))
        return pages


def local_http_extract_provider() -> Optional[LocalHttpExtractProvider]:
    """The local reader, or None when the HTTP client cannot be imported."""
    if not local_extract_available():
        return None
    return LocalHttpExtractProvider()
