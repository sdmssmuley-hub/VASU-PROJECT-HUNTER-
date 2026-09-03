"""
SQLite database layer. Stdlib sqlite3 only — zero extra cost, zero server to run.
Schema covers: projects, equipment, tenders, companies, contacts, sources,
research_runs, scores, verification, notifications, search_queries, audit_logs.
"""
import sqlite3
import os
import json
import datetime as dt
from contextlib import contextmanager
from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,               -- fingerprint hash, see dedup.py
    name TEXT NOT NULL,
    client TEXT,
    owner_entity TEXT,
    spv TEXT,
    location TEXT,
    state TEXT,
    industry TEXT,
    project_type TEXT,
    status TEXT,                       -- e.g. tender, awarded, under-construction, commissioned, cancelled
    civil_status TEXT,
    lead_status TEXT DEFAULT 'NEW',    -- NEW/RESEARCHING/VERIFIED/CONTACTED/FOLLOW-UP/QUOTATION/NEGOTIATION/WON/LOST/REJECTED
    qc_decision TEXT,                  -- APPROVED / HOLD / REJECTED
    qc_reason TEXT,
    overall_confidence INTEGER,        -- 0-100
    opportunity_score INTEGER,         -- 0-100
    vasu_scope TEXT,                   -- JSON list of scope items
    entry_route TEXT,
    first_seen_at TEXT,
    last_updated_at TEXT,
    is_duplicate_of TEXT,
    raw_notes TEXT
);

CREATE TABLE IF NOT EXISTS equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    equipment_type TEXT,               -- transformer, reactor, press, etc.
    oem TEXT,
    model TEXT,
    capacity TEXT,                     -- e.g. "500 MVA"
    quantity TEXT,
    physical_units TEXT,
    weight_value TEXT,
    weight_confidence TEXT,            -- CONFIRMED / ESTIMATED / UNKNOWN
    dimensions TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS tenders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    tender_number TEXT,
    tender_date TEXT,
    award_date TEXT,
    po_date TEXT,
    issuing_authority TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    role TEXT,                         -- EPC / OEM / Civil / Transporter / Installation / Heavy-lift
    company_name TEXT,
    confidence TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    name TEXT,
    designation TEXT,
    company TEXT,
    public_profile_url TEXT,
    note TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    url TEXT,
    title TEXT,
    source_type TEXT,
    reliability_level TEXT,            -- A/B/C/D
    published_date TEXT,
    retrieved_at TEXT,
    snippet TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    event_type TEXT,                   -- tender/award/po/manufacturing/testing/dispatch/arrival/installation/commissioning
    event_date TEXT,
    confidence TEXT,
    note TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS research_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_started_at TEXT,
    run_finished_at TEXT,
    run_label TEXT,                    -- e.g. "10:00 Transformer tenders"
    candidates INTEGER DEFAULT 0,
    duplicates INTEGER DEFAULT 0,
    rejected INTEGER DEFAULT 0,
    verified INTEGER DEFAULT 0,
    high_priority INTEGER DEFAULT 0,
    status TEXT DEFAULT 'completed'
);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    factor TEXT,
    points INTEGER,
    max_points INTEGER,
    reason TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS verification (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    field_name TEXT,
    field_value TEXT,
    confidence TEXT,                   -- CONFIRMED/LIKELY/ESTIMATED/UNKNOWN
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT,
    channel TEXT DEFAULT 'telegram',
    message TEXT,
    status TEXT DEFAULT 'pending',     -- pending/sent/failed
    created_at TEXT,
    sent_at TEXT,
    retry_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS search_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    query TEXT,
    category TEXT,
    executed_at TEXT,
    result_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component TEXT,
    level TEXT,                        -- INFO/WARNING/ERROR
    message TEXT,
    created_at TEXT
);
"""


def get_connection():
    os.makedirs(os.path.dirname(settings.DATABASE_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(settings.DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db_session() as conn:
        conn.executescript(SCHEMA)


def log_audit(component: str, level: str, message: str):
    """Never let a failure here crash the caller."""
    try:
        with db_session() as conn:
            conn.execute(
                "INSERT INTO audit_logs (component, level, message, created_at) VALUES (?,?,?,?)",
                (component, level, message, dt.datetime.utcnow().isoformat()),
            )
    except Exception:
        pass


def now_iso() -> str:
    return dt.datetime.utcnow().isoformat()
