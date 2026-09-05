"""
Section 30 persistence, scoped down to SQLite (as the brief allows for a
GitHub-first deployment) with four tables: projects, alerts,
rejected_candidates, runs. The DB file is committed back to the repo by
the GitHub Actions workflow after each run so state survives across the
stateless runners.
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("VASU_DB_PATH", "data/vasu_hunter.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    fingerprint TEXT UNIQUE NOT NULL,
    project_name TEXT,
    client TEXT,
    location TEXT,
    state TEXT,
    industry TEXT,
    project_type TEXT,
    project_status TEXT,
    civil_status TEXT,
    equipment_name TEXT,
    equipment_rating TEXT,
    actual_weight_tonnes REAL,
    actual_weight_raw TEXT,
    heaviest_package_weight_raw TEXT,
    quantity INTEGER,
    oem TEXT,
    epc TEXT,
    installation_contractor TEXT,
    heavy_lift_contractor TEXT,
    logistics_contractor TEXT,
    transporter TEXT,
    po_status TEXT,
    dispatch_date TEXT,
    arrival_date TEXT,
    installation_date TEXT,
    commissioning_date TEXT,
    vasu_scope TEXT,
    entry_point TEXT,
    estimated_contract_value TEXT,
    confidence TEXT,
    why_relevant TEXT,
    lead_score INTEGER,
    priority TEXT,
    source_url TEXT,
    evidence TEXT,
    last_alerted_priority TEXT,
    last_alerted_at TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT,
    alert_type TEXT,        -- NEW_HOT | NEW_HIGH | SCHEDULE_CHANGE | DIGEST
    message TEXT,
    status TEXT,            -- PENDING | SENT | FAILED
    telegram_message_id TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS rejected_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT,
    reason TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    finished_at TEXT,
    queries_run INTEGER,
    queries_failed INTEGER,
    urls_discovered INTEGER,
    candidates_analyzed INTEGER,
    qualified INTEGER,
    rejected INTEGER,
    duplicates INTEGER,
    new_projects INTEGER,
    schedule_changes INTEGER,
    alerts_sent INTEGER,
    hot_count INTEGER,
    high_count INTEGER,
    medium_count INTEGER,
    error TEXT
);
"""


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
