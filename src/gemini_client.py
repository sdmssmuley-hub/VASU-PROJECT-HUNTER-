import os
from tenacity import retry, stop_after_attempt, wait_exponential

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# gemini-2.5-flash is a stable, current, low-cost model that supports the
# google_search tool for real grounded web search.
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_client = None


def _get_client():
    """Lazily create and cache the google-genai Client.

    Uses the current `google-genai` SDK (PyPI package: google-genai, import
    path: `from google import genai`) - the maintained replacement for the
    deprecated `google-generativeai` package.
    """
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY not configured")
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
def ask_gemini(prompt: str, max_tokens: int = 512) -> str:
    """Plain (non-grounded) generation, used for structured JSON extraction."""
    from google.genai import types

    client = _get_client()
    resp = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
        ),
    )
    text = getattr(resp, "text", None)
    if not text:
        raise RuntimeError("Gemini returned an empty response")
    return text


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, max=6))
def web_search(query: str, limit: int = 10):
    """
    Real live web search using Gemini's Google Search grounding tool.

    Calls the model with the `google_search` tool enabled and reads the
    grounding metadata Google's servers attach to the response - real
    search results with real URLs, not model-generated ones.

    Returns a list of dicts: {title, url, snippet}
    Raises RuntimeError if grounding is unavailable or returns nothing.
    """
    from google.genai import types

    client = _get_client()

    resp = client.models.generate_content(
        model=MODEL_NAME,
        contents=(
            f"Find the most recent, specific news, tenders, or project "
            f"announcements about: {query}. Give concrete company/project "
            f"names, locations, and dates where available."
        ),
        config=types.GenerateContentConfig(
            temperature=0.0,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )

    results = []
    summary_text = getattr(resp, "text", "") or ""
    candidates = getattr(resp, "candidates", None) or []

    for cand in candidates:
        gm = getattr(cand, "grounding_metadata", None)
        if not gm:
            continue
        chunks = getattr(gm, "grounding_chunks", None) or []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if not web:
                continue
            url = getattr(web, "uri", None)
            title = getattr(web, "title", None)
            if not url:
                continue
            results.append({
                "title": title or query,
                "url": url,
                "snippet": summary_text[:1500],
            })

    if not results:
        raise RuntimeError(
            "Gemini Search grounding returned no sources for this query "
            "(key/model may not support google_search grounding, or no "
            "relevant results were found)."
        )

    seen = set()
    deduped = []
    for r in results:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        deduped.append(r)
        if len(deduped) >= limit:
            break
    return deduped
