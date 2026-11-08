"""Search and extract pins stay independent, and the unpaid extract path stays local."""

import json


def test_searxng_search_does_not_move_extract_onto_firecrawl(monkeypatch):
    from tools import web_tools
    from tools.web_tools_extract import _resolve_extract_provider

    monkeypatch.setattr(web_tools, "_load_web_config", lambda: {
        "backend": "ddgs",
        "search_backend": "searxng",
        "extract_backend": "ddgs",
    })
    assert web_tools._get_search_backend() == "searxng"
    assert web_tools._get_extract_backend() == "ddgs"

    class SearchOnly:
        display_name = "DuckDuckGo (ddgs)"

        def supports_extract(self):
            return False

    monkeypatch.setattr(
        "agent.web_search_registry.get_provider",
        lambda name: SearchOnly() if name == "ddgs" else None,
    )
    provider, error = _resolve_extract_provider("ddgs")
    assert error is None
    assert provider is not None and provider.name == "local-http"


def test_unknown_extract_name_is_not_a_provider(monkeypatch):
    from tools.web_tools_extract import _resolve_extract_provider

    monkeypatch.setattr("tools.web_tools_extract.selection_exists", lambda capability: True)
    monkeypatch.setattr("agent.web_search_registry.get_provider", lambda name: None)
    provider, error = _resolve_extract_provider("ddgs-extract")
    assert provider is None
    payload = json.loads(error)
    assert payload["error"]
    assert "firecrawl" not in payload["error"].lower()
