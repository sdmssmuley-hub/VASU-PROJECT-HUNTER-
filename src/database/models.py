"""CRUD helpers used by src/main.py. Kept as plain sqlite3, no ORM."""

import json
from datetime import datetime, timezone

from src.database.db import get_connection

PROJECT_COLUMNS = [
    "project_id", "fingerprint", "project_name", "client", "location", "state",
    "industry", "project_type", "project_status", "civil_status",
    "equipment_name", "equipment_rating", "actual_weight_tonnes",
    "actual_weight_raw", "heaviest_package_weight_raw", "quantity", "oem",
    "epc", "installation_contractor", "heavy_lift_contractor",
    "logistics_contractor", "transporter", "po_status", "dispatch_date",
    "arrival_date", "installation_date", "commissioning_date", "vasu_scope",
    "entry_point", "estimated_contract_value", "confidence", "why_relevant",
    "lead_score", "priority", "source_url", "evidence",
]


def _now():
    return datetime.now(timezone.utc).isoformat()


def get_project_by_fingerprint(fingerprint: str):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM projects WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def upsert_project(record: dict, is_new: bool):
    now = _now()
    conn = get_connection()
    try:
        if is_new:
            record["created_at"] = now
            record["updated_at"] = now
            cols = PROJECT_COLUMNS + ["created_at", "updated_at"]
            placeholders = ", ".join(["?"] * len(cols))
            values = [record.get(c) for c in cols]
            conn.execute(
                f"INSERT INTO projects ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
        else:
            record["updated_at"] = now
            set_cols = PROJECT_COLUMNS + ["updated_at"]
            set_clause = ", ".join(f"{c} = ?" for c in set_cols if c != "fingerprint")
            values = [record.get(c) for c in set_cols if c != "fingerprint"]
            values.append(record["fingerprint"])
            conn.execute(
                f"UPDATE projects SET {set_clause} WHERE fingerprint = ?",
                values,
            )
        conn.commit()
    finally:
        conn.close()


def mark_alerted(fingerprint: str, priority: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE projects SET last_alerted_priority = ?, last_alerted_at = ? "
            "WHERE fingerprint = ?",
            (priority, _now(), fingerprint),
        )
        conn.commit()
    finally:
        conn.close()


def log_alert(project_id, alert_type, message, status, telegram_message_id=None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO alerts (project_id, alert_type, message, status, "
            "telegram_message_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, alert_type, message, status, telegram_message_id, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def log_rejected(source_url, reason):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO rejected_candidates (source_url, reason, created_at) "
            "VALUES (?, ?, ?)",
            (source_url, reason, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def log_run(stats: dict):
    conn = get_connection()
    try:
        cols = [
            "started_at", "finished_at", "queries_run", "queries_failed",
            "urls_discovered", "candidates_analyzed", "qualified", "rejected",
            "duplicates", "new_projects", "schedule_changes", "alerts_sent",
            "hot_count", "high_count", "medium_count", "error",
        ]
        values = [stats.get(c) for c in cols]
        conn.execute(
            f"INSERT INTO runs ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
            values,
        )
        conn.commit()
    finally:
        conn.close()


def get_todays_runs(day_prefix: str):
    """day_prefix like '2026-09-05' (UTC date string prefix on started_at)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM runs WHERE started_at LIKE ? ORDER BY started_at",
            (f"{day_prefix}%",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_open_projects_by_priority(priorities, limit=20):
    conn = get_connection()
    try:
        placeholders = ", ".join(["?"] * len(priorities))
        rows = conn.execute(
            f"SELECT * FROM projects WHERE priority IN ({placeholders}) "
            f"ORDER BY lead_score DESC LIMIT ?",
            (*priorities, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def health_snapshot():
    conn = get_connection()
    try:
        counts = {}
        for table in ["projects", "alerts", "rejected_candidates", "runs"]:
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        last_run = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        priority_counts = {}
        for p in ["HOT", "HIGH", "MEDIUM", "WATCH"]:
            priority_counts[p] = conn.execute(
                "SELECT COUNT(*) FROM projects WHERE priority = ?", (p,)
            ).fetchone()[0]
        return {
            "table_counts": counts,
            "priority_counts": priority_counts,
            "last_run": dict(last_run) if last_run else None,
        }
    finally:
        conn.close()
