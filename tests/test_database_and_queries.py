import os
import tempfile
import importlib


def _fresh_db(tmp_path):
    """Point settings at a scratch DB before importing database module fresh."""
    os.environ["DATABASE_PATH"] = str(tmp_path / "test.db")
    import app.config as config_module
    importlib.reload(config_module)
    import app.database as db_module
    importlib.reload(db_module)
    return db_module


def test_init_db_creates_all_tables(tmp_path):
    db_module = _fresh_db(tmp_path)
    db_module.init_db()
    with db_module.db_session() as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    expected = {"projects", "equipment", "tenders", "companies", "contacts", "sources",
                "research_runs", "scores", "verification", "notifications",
                "search_queries", "audit_logs", "timeline_events"}
    assert expected.issubset(tables)


def test_audit_log_never_raises_on_missing_db(tmp_path):
    db_module = _fresh_db(tmp_path)
    db_module.init_db()
    # should not raise even if called before init in another context
    db_module.log_audit("test", "INFO", "hello")


def test_query_generation_produces_nonempty_unique_queries():
    from app.agents.hunter import generate_queries
    queries = generate_queries(None, limit=25)
    assert len(queries) > 0
    assert len(queries) == len(set(queries))  # no duplicates


def test_query_generation_respects_category_filter():
    from app.agents.hunter import generate_queries
    q_all = generate_queries(None, limit=100)
    q_category = generate_queries("steel_forging_presses", limit=100)
    assert len(q_category) <= len(q_all)
    assert all("India" in q for q in q_category)
