"""
Telegram integration: outbound alerts (project cards, daily summary, system
alerts) and inbound commands (/start /status /today /top /search /project /help).
Uses plain HTTP calls to the Bot API — no extra dependency needed beyond httpx.
Every outbound message is queued in `notifications` first, then marked
sent/failed — a Telegram outage never loses a lead, it just retries later.
"""
from __future__ import annotations
import httpx
import datetime as dt
from app.config import settings
from app.database import db_session, log_audit, now_iso

API_BASE = "https://api.telegram.org/bot{token}"


def _api_url(method: str) -> str:
    return f"{API_BASE.format(token=settings.TELEGRAM_BOT_TOKEN)}/{method}"


def queue_message(message: str, project_id: str | None = None) -> int:
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO notifications (project_id, channel, message, status, created_at) VALUES (?,?,?,?,?)",
            (project_id, "telegram", message, "pending", now_iso()),
        )
        return cur.lastrowid


def send_pending(max_retries: int = 3) -> dict:
    """Call periodically (or right after queuing) to flush pending notifications."""
    sent, failed = 0, 0
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        log_audit("telegram", "WARNING", "TELEGRAM_BOT_TOKEN/CHAT_ID not set — messages stay queued")
        return {"sent": 0, "failed": 0, "skipped": "not_configured"}

    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE status='pending' AND retry_count < ?", (max_retries,)
        ).fetchall()
        for row in rows:
            try:
                resp = httpx.post(
                    _api_url("sendMessage"),
                    json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": row["message"], "parse_mode": "HTML"},
                    timeout=15,
                )
                resp.raise_for_status()
                conn.execute(
                    "UPDATE notifications SET status='sent', sent_at=? WHERE id=?", (now_iso(), row["id"])
                )
                sent += 1
            except Exception as e:
                conn.execute(
                    "UPDATE notifications SET retry_count = retry_count + 1, status=? WHERE id=?",
                    ("failed" if row["retry_count"] + 1 >= max_retries else "pending", row["id"]),
                )
                log_audit("telegram", "ERROR", f"Send failed for notification {row['id']}: {e}")
                failed += 1
    return {"sent": sent, "failed": failed}


def format_project_card(project: dict) -> str:
    eq = project.get("equipment_summary", "UNKNOWN")
    return (
        "🔥 <b>VASU AI — VERIFIED PROJECT</b>\n\n"
        f"<b>Project:</b> {project.get('name', 'UNKNOWN')}\n"
        f"<b>Client:</b> {project.get('client', 'UNKNOWN')}\n"
        f"<b>Location:</b> {project.get('location', 'UNKNOWN')}\n"
        f"<b>Status:</b> {project.get('status', 'UNKNOWN')}\n"
        f"<b>Equipment:</b> {eq}\n"
        f"<b>Weight:</b> {project.get('weight', 'UNKNOWN')}\n"
        f"<b>Arrival:</b> {project.get('arrival_month', 'UNKNOWN')}\n"
        f"<b>OEM:</b> {project.get('oem', 'UNKNOWN')}\n"
        f"<b>EPC:</b> {project.get('epc', 'UNKNOWN')}\n"
        f"<b>Vasu Scope:</b> {project.get('vasu_scope', 'UNKNOWN')}\n"
        f"<b>Entry Route:</b> {project.get('entry_route', 'UNKNOWN')}\n"
        f"<b>Score:</b> {project.get('score', 0)}/100\n"
        f"<b>Confidence:</b> {project.get('confidence', 0)}/100\n"
        f"<b>Sources:</b> {project.get('source_count', 0)} retained"
    )


def format_system_alert(component: str, problem: str) -> str:
    return (
        "⚠️ <b>VASU AI SYSTEM ALERT</b>\n\n"
        f"<b>Component:</b> {component}\n"
        f"<b>Problem:</b> {problem}\n"
        f"<b>Time:</b> {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


def format_run_report(run: dict) -> str:
    return (
        f"🕐 <b>VASU AI — {run.get('run_label', 'RUN')}</b>\n\n"
        f"Candidates: {run.get('candidates', 0)}\n"
        f"Duplicates: {run.get('duplicates', 0)}\n"
        f"Rejected: {run.get('rejected', 0)}\n"
        f"Verified: {run.get('verified', 0)}\n"
        f"High priority: {run.get('high_priority', 0)}"
    )


def format_daily_report(summary: dict) -> str:
    top = "\n".join(
        f"{i+1}. {p['name']} — {p['score']}/100" for i, p in enumerate(summary.get("top_opportunities", []))
    ) or "None"
    return (
        "📊 <b>VASU AI DAILY REPORT</b>\n\n"
        f"Runs: {summary.get('runs', 0)}\n"
        f"Candidates: {summary.get('candidates', 0)}\n"
        f"Duplicates: {summary.get('duplicates', 0)}\n"
        f"Rejected: {summary.get('rejected', 0)}\n"
        f"Verified: {summary.get('verified', 0)}\n"
        f"High priority: {summary.get('high_priority', 0)}\n\n"
        f"<b>Top opportunities:</b>\n{top}\n\n"
        f"Most promising state: {summary.get('top_state', 'UNKNOWN')}\n"
        f"Most promising industry: {summary.get('top_industry', 'UNKNOWN')}\n"
        f"Most promising equipment: {summary.get('top_equipment', 'UNKNOWN')}\n"
        f"Highest score: {summary.get('highest_score', 0)}"
    )
