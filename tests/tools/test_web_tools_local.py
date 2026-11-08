"""Local HTTP reader for web_extract. External fetches are mocked.

A sentinel in the fake page is the only accepted proof of a read. A test that
reached the public network would not contain that sentinel.
"""

from __future__ import annotations

_PAGE = (
    "<html><head><title>YUN1_LOCAL_EXTRACT_SENTINEL</title></head>"
    "<body><script>secret()</script><p>synthetic page body</p></body></html>"
)


def test_fetch_goes_through_the_ssrf_safe_client(monkeypatch):
    """The reader must not open a raw HTTP client. A missed patch fails this test."""
    created: dict = {}

    class _Response:
        headers = {"content-type": "text/plain"}
        text = "YUN1_LOCAL_EXTRACT_SENTINEL"

        def raise_for_status(self):
            return None

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url):
            created["url"] = url
            return _Response()

    def _factory(**kwargs):
        created["kwargs"] = kwargs
        return _Client()

    monkeypatch.setattr("tools.url_safety.create_ssrf_safe_client", _factory)
    from tools.web_tools_local import fetch_public_page

    content_type, body = fetch_public_page("https://example.com/page")
    assert created["url"] == "https://example.com/page"
    assert created["kwargs"]["follow_redirects"] is True
    assert body == "YUN1_LOCAL_EXTRACT_SENTINEL"
    assert "text/plain" in content_type


def test_page_text_drops_script_and_keeps_title():
    from tools.web_tools_local import page_text_from_body

    title, text = page_text_from_body(_PAGE, "text/html; charset=utf-8")
    assert title == "YUN1_LOCAL_EXTRACT_SENTINEL"
    assert "synthetic page body" in text
    assert "secret" not in text


def test_web_extract_is_offered_without_search_credentials(monkeypatch):
    """The web toolset must still expose web_extract when no search key is set."""
    from tools import web_tools

    monkeypatch.setattr(web_tools, "check_web_api_key", lambda: False)
    assert web_tools.check_web_extract_available() is True


def test_local_provider_extracts_the_mocked_page_only(monkeypatch):
    from tools.web_tools_local import LocalHttpExtractProvider

    fetched: dict[str, str] = {}

    def _fetch(url, **_kwargs):
        fetched["url"] = url
        return "text/html", _PAGE

    monkeypatch.setattr("tools.web_tools_local.fetch_public_page", _fetch)
    pages = LocalHttpExtractProvider().extract(["https://example.com"])
    assert fetched["url"] == "https://example.com"
    assert pages[0]["title"] == "YUN1_LOCAL_EXTRACT_SENTINEL"
    assert "synthetic page body" in pages[0]["content"]
    assert "error" not in pages[0]


def test_local_reader_does_not_replace_an_extract_capable_backend(monkeypatch):
    """A configured extract provider stays on that provider. The local reader is the fallback."""
    import asyncio
    from agent.web_search_provider import WebSearchProvider
    from tools import web_tools
    from tools.web_tools_extract import _resolve_extract_provider

    class _Extract(WebSearchProvider):
        @property
        def name(self) -> str:
            return "firecrawl"

        @property
        def display_name(self) -> str:
            return "Firecrawl"

        def is_available(self) -> bool:
            return True

        def supports_extract(self) -> bool:
            return True

        async def extract(self, urls, format=None):
            return [{"url": u, "title": "vendor", "content": "from-vendor", "raw_content": "from-vendor", "metadata": {}} for u in urls]

    monkeypatch.setattr(
        "agent.web_search_registry.get_provider",
        lambda name: _Extract() if name == "firecrawl" else None,
    )
    provider, error = _resolve_extract_provider("firecrawl")
    assert error is None
    assert provider.name == "firecrawl"
    assert asyncio.iscoroutinefunction(provider.extract)
