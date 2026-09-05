"""Section 34 step 1-3: run queries, collect candidate URLs."""

from src import config
from src.gemini_client import web_search


def discover_candidates():
    """
    Runs this run's slice of search queries and returns a de-duplicated
    (by URL) list of candidate dicts: {title, snippet, source_url, query}.
    Returns (candidates, stats) where stats tracks query success/failure
    for the run log / health check.
    """
    queries = config.build_daily_queries()
    candidates_by_url = {}
    failed = 0

    for q in queries:
        try:
            results = web_search(q, limit=config.SEARCH_RESULTS_PER_QUERY)
        except Exception as e:
            print(f"[search] '{q}' failed: {e}")
            failed += 1
            continue
        for r in results:
            url = r.get("url")
            if not url or url in candidates_by_url:
                continue
            candidates_by_url[url] = {
                "title": r.get("title"),
                "snippet": r.get("snippet"),
                "source_url": url,
                "query": q,
            }

    candidates = list(candidates_by_url.values())[: config.MAX_CANDIDATES_PER_RUN]
    stats = {
        "queries_run": len(queries),
        "queries_failed": failed,
        "urls_discovered": len(candidates_by_url),
    }
    return candidates, stats
