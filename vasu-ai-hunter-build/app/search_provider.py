"""
SearchProvider abstraction — swap search backends without touching the rest
of the app. Add a new provider by subclassing SearchProvider and registering
it in get_search_provider().

Ship with:
  - DemoSearchProvider: returns clearly-labelled DEMO DATA, for testing only.
  - SerpApiProvider / TavilyProvider / BraveProvider: real providers, require
    SEARCH_API_KEY. Implement the TODOs with your chosen provider's HTTP API.
"""
from __future__ import annotations
import abc
import httpx
from app.config import settings
from app.database import log_audit


class SearchResult:
    def __init__(self, title: str, url: str, snippet: str, published_date: str | None = None):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.published_date = published_date

    def to_dict(self):
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "published_date": self.published_date,
        }


class SearchProvider(abc.ABC):
    @abc.abstractmethod
    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        ...


class DemoSearchProvider(SearchProvider):
    """
    Returns clearly labelled DEMO DATA. Use only for exercising the pipeline
    (dedup, scoring, QC, Telegram formatting) before a real API key is set.
    NEVER let demo output reach Telegram/production without the DEMO DATA tag —
    the QC agent enforces this (see agents/qc.py).
    """

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        return [
            SearchResult(
                title=f"[DEMO DATA] Sample tender notice matching: {query}",
                url="https://example.invalid/demo-source",
                snippet=(
                    "This is placeholder demo content because SEARCH_PROVIDER=demo. "
                    "Configure a real provider in .env to get live results."
                ),
                published_date=None,
            )
        ]


class DuckDuckGoProvider(SearchProvider):
    """Free, zero-cost, no-API-key search using the `ddgs` package (DuckDuckGo).
    This is the default provider so the system produces real (non-demo) leads
    without requiring any paid search API key. DuckDuckGo may rate-limit or
    block heavy automated use over time — if that happens, set SEARCH_PROVIDER
    to tavily/serpapi/brave in the environment and add the matching
    SEARCH_API_KEY secret; no code changes needed."""

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        try:
            from ddgs import DDGS
        except Exception as e:
            log_audit("search_provider", "ERROR", f"ddgs package not installed: {e}")
            return []
        try:
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append(SearchResult(
                        title=r.get("title", ""),
                        url=r.get("href", "") or r.get("url", ""),
                        snippet=r.get("body", "") or r.get("snippet", ""),
                        published_date=None,
                    ))
            return results
        except Exception as e:
            log_audit("search_provider", "ERROR", f"DuckDuckGo search failed for '{query}': {e}")
            return []


class TavilyProvider(SearchProvider):
    """Real provider example: https://tavily.com — set SEARCH_API_KEY."""

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        if not settings.SEARCH_API_KEY:
            log_audit("search_provider", "ERROR", "Tavily selected but SEARCH_API_KEY missing")
            return []
        try:
            resp = httpx.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.SEARCH_API_KEY,
                    "query": query,
                    "max_results": max_results,
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for r in data.get("results", []):
                results.append(SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                    published_date=r.get("published_date"),
                ))
            return results
        except Exception as e:
            log_audit("search_provider", "ERROR", f"Tavily search failed: {e}")
            return []


class SerpApiProvider(SearchProvider):
    """Real provider example: https://serpapi.com — set SEARCH_API_KEY."""

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        if not settings.SEARCH_API_KEY:
            log_audit("search_provider", "ERROR", "SerpApi selected but SEARCH_API_KEY missing")
            return []
        try:
            resp = httpx.get(
                "https://serpapi.com/search",
                params={"q": query, "api_key": settings.SEARCH_API_KEY, "num": max_results},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for r in data.get("organic_results", [])[:max_results]:
                results.append(SearchResult(
                    title=r.get("title", ""),
                    url=r.get("link", ""),
                    snippet=r.get("snippet", ""),
                    published_date=r.get("date"),
                ))
            return results
        except Exception as e:
            log_audit("search_provider", "ERROR", f"SerpApi search failed: {e}")
            return []


class BraveProvider(SearchProvider):
    """Real provider example: https://brave.com/search/api — set SEARCH_API_KEY."""

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        if not settings.SEARCH_API_KEY:
            log_audit("search_provider", "ERROR", "Brave selected but SEARCH_API_KEY missing")
            return []
        try:
            resp = httpx.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={"X-Subscription-Token": settings.SEARCH_API_KEY},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for r in data.get("web", {}).get("results", [])[:max_results]:
                results.append(SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("description", ""),
                    published_date=r.get("age"),
                ))
            return results
        except Exception as e:
            log_audit("search_provider", "ERROR", f"Brave search failed: {e}")
            return []


_PROVIDERS = {
    "demo": DemoSearchProvider,
    "duckduckgo": DuckDuckGoProvider,
    "tavily": TavilyProvider,
    "serpapi": SerpApiProvider,
    "brave": BraveProvider,
}


def get_search_provider() -> SearchProvider:
    cls = _PROVIDERS.get(settings.SEARCH_PROVIDER, DemoSearchProvider)
    return cls()


def get_fallback_chain() -> list[SearchProvider]:
    """
    Used by the scheduler: if the primary provider fails or is unconfigured,
    fall through to the next configured one. Demo is always the last resort
    so a run never hard-crashes — but demo output is never sent to Telegram.
    """
    chain = []
    primary = settings.SEARCH_PROVIDER
    order = [primary] + [p for p in _PROVIDERS if p != primary and p != "demo"] + ["demo"]
    seen = set()
    for name in order:
        if name in seen:
            continue
        seen.add(name)
        chain.append(_PROVIDERS[name]())
    return chain
