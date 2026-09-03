"""
FastAPI application: dashboard API + static dashboard + Telegram webhook
for commands (/start /status /today /top /search /project /help).
Run with: uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations
import secrets
import datetime as dt
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import httpx

from app.config import settings
from app.database import init_db, db_session, log_audit
from app.scheduler import start_scheduler
from app.orchestrator import run_cycle, run_daily_report, ROTATION
from app.telegram_bot import queue_message, send_pending, _api_url

app = FastAPI(title="VASU AI Project Hunter")
security = HTTPBasic()


@app.on_event("startup")
def startup():
    init_db()
    start_scheduler()
    log_audit("app", "INFO", "Application started")


def check_auth(credentials: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(credentials.username, settings.DASHBOARD_USERNAME)
    ok_pass = secrets.compare_digest(credentials.password, settings.DASHBOARD_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="Invalid credentials", headers={"WWW-Authenticate": "Basic"})
    return True


# ---------------------------------------------------------------- Dashboard
@app.get("/")
def dashboard_page(auth: bool = Depends(check_auth)):
    return FileResponse("app/static/index.html")


app.mount("/static", StaticFiles(directory="app/static"), name="static")


# ---------------------------------------------------------------- API
@app.get("/api/status")
def api_status(auth: bool = Depends(check_auth)):
    with db_session() as conn:
        last_run = conn.execute("SELECT * FROM research_runs ORDER BY id DESC LIMIT 1").fetchone()
        today = dt.date.today().isoformat()
        today_runs = conn.execute(
            "SELECT COUNT(*) c FROM research_runs WHERE run_started_at LIKE ?", (f"{today}%",)
        ).fetchone()["c"]
        found = conn.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"]
        verified = conn.execute("SELECT COUNT(*) c FROM projects WHERE qc_decision='APPROVED'").fetchone()["c"]
        rejected = conn.execute("SELECT COUNT(*) c FROM projects WHERE qc_decision='REJECTED'").fetchone()["c"]
        high_priority = conn.execute(
            "SELECT COUNT(*) c FROM projects WHERE qc_decision='APPROVED' AND opportunity_score>=70"
        ).fetchone()["c"]

    now_hour = dt.datetime.now().hour
    upcoming = [h for h in sorted(settings.RUN_HOURS) if h > now_hour]
    next_run = f"{upcoming[0]:02d}:00" if upcoming else f"{min(settings.RUN_HOURS):02d}:00 (tomorrow)"

    return {
        "last_run": dict(last_run) if last_run else None,
        "next_run": next_run,
        "today_runs": today_runs,
        "projects_found": found,
        "verified_leads": verified,
        "rejected_leads": rejected,
        "high_priority_leads": high_priority,
        "telegram_configured": bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID),
        "search_provider": settings.SEARCH_PROVIDER,
        "llm_provider": settings.LLM_PROVIDER,
    }


@app.get("/api/projects")
def api_projects(
    state: str | None = None, industry: str | None = None, status: str | None = None,
    min_score: int = 0, qc_decision: str | None = None, q: str | None = None,
    auth: bool = Depends(check_auth),
):
    query = "SELECT * FROM projects WHERE opportunity_score >= ?"
    params: list = [min_score]
    if state:
        query += " AND state = ?"; params.append(state)
    if industry:
        query += " AND industry = ?"; params.append(industry)
    if status:
        query += " AND status = ?"; params.append(status)
    if qc_decision:
        query += " AND qc_decision = ?"; params.append(qc_decision)
    if q:
        query += " AND (name LIKE ? OR client LIKE ? OR location LIKE ?)"
        like = f"%{q}%"; params.extend([like, like, like])
    query += " ORDER BY opportunity_score DESC, last_updated_at DESC LIMIT 200"

    with db_session() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/projects/{project_id}")
def api_project_detail(project_id: str, auth: bool = Depends(check_auth)):
    with db_session() as conn:
        project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(404, "Project not found")
        equipment = conn.execute("SELECT * FROM equipment WHERE project_id=?", (project_id,)).fetchall()
        companies = conn.execute("SELECT * FROM companies WHERE project_id=?", (project_id,)).fetchall()
        tenders = conn.execute("SELECT * FROM tenders WHERE project_id=?", (project_id,)).fetchall()
        timeline = conn.execute("SELECT * FROM timeline_events WHERE project_id=?", (project_id,)).fetchall()
        contacts = conn.execute("SELECT * FROM contacts WHERE project_id=?", (project_id,)).fetchall()
        sources = conn.execute("SELECT * FROM sources WHERE project_id=?", (project_id,)).fetchall()
        verification = conn.execute("SELECT * FROM verification WHERE project_id=?", (project_id,)).fetchall()
        scores = conn.execute("SELECT * FROM scores WHERE project_id=?", (project_id,)).fetchall()

    return {
        "project": dict(project),
        "equipment": [dict(r) for r in equipment],
        "companies": [dict(r) for r in companies],
        "tenders": [dict(r) for r in tenders],
        "timeline": [dict(r) for r in timeline],
        "contacts": [dict(r) for r in contacts],
        "sources": [dict(r) for r in sources],
        "verification": [dict(r) for r in verification],
        "scores": [dict(r) for r in scores],
    }


@app.post("/api/run-now")
def api_run_now(hour: int | None = None, auth: bool = Depends(check_auth)):
    """Manually trigger a cycle — useful for testing without waiting for the schedule."""
    result = run_cycle(hour=hour)
    return result


@app.post("/api/daily-report/run-now")
def api_daily_report_now(auth: bool = Depends(check_auth)):
    return run_daily_report()


@app.get("/api/logs")
def api_logs(limit: int = 100, auth: bool = Depends(check_auth)):
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/rotation")
def api_rotation(auth: bool = Depends(check_auth)):
    return ROTATION


# ---------------------------------------------------------------- Telegram webhook (commands)
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    payload = await request.json()
    message = payload.get("message", {})
    text = (message.get("text") or "").strip()
    chat_id = str(message.get("chat", {}).get("id", ""))

    if chat_id != str(settings.TELEGRAM_CHAT_ID):
        return JSONResponse({"ok": True})  # ignore messages from anyone but the owner's chat

    reply = _handle_command(text)
    if reply:
        try:
            httpx.post(_api_url("sendMessage"), json={"chat_id": chat_id, "text": reply, "parse_mode": "HTML"}, timeout=15)
        except Exception as e:
            log_audit("telegram_webhook", "ERROR", f"Reply failed: {e}")
    return JSONResponse({"ok": True})


def _handle_command(text: str) -> str:
    cmd = text.split()[0].lower() if text else ""
    with db_session() as conn:
        if cmd == "/start":
            return "VASU AI Project Hunter is online. Try /status, /today, /top, /help."
        if cmd == "/status":
            last_run = conn.execute("SELECT * FROM research_runs ORDER BY id DESC LIMIT 1").fetchone()
            return (
                "<b>System Status</b>\n"
                f"Search provider: {settings.SEARCH_PROVIDER}\n"
                f"LLM provider: {settings.LLM_PROVIDER}\n"
                f"Last run: {dict(last_run) if last_run else 'none yet'}\n"
                f"Scheduled hours: {settings.RUN_HOURS}"
            )
        if cmd == "/today":
            today = dt.date.today().isoformat()
            rows = conn.execute(
                "SELECT name, opportunity_score FROM projects WHERE qc_decision='APPROVED' AND last_updated_at LIKE ? ORDER BY opportunity_score DESC LIMIT 10",
                (f"{today}%",),
            ).fetchall()
            if not rows:
                return "No qualified opportunities found yet today."
            return "<b>Today's opportunities</b>\n" + "\n".join(f"- {r['name']} ({r['opportunity_score']}/100)" for r in rows)
        if cmd == "/top":
            rows = conn.execute(
                "SELECT name, opportunity_score FROM projects WHERE qc_decision='APPROVED' ORDER BY opportunity_score DESC LIMIT 10"
            ).fetchall()
            if not rows:
                return "No approved leads yet."
            return "<b>Top opportunities</b>\n" + "\n".join(f"- {r['name']} ({r['opportunity_score']}/100)" for r in rows)
        if cmd == "/help":
            return "/start /status /today /top /search <term> /project <id> /help"
        if cmd == "/search":
            term = text[len("/search"):].strip()
            if not term:
                return "Usage: /search <term>"
            rows = conn.execute(
                "SELECT name, id FROM projects WHERE name LIKE ? LIMIT 10", (f"%{term}%",)
            ).fetchall()
            if not rows:
                return f"No projects matching '{term}'."
            return "\n".join(f"{r['name']} — id:{r['id']}" for r in rows)
        if cmd == "/project":
            pid = text[len("/project"):].strip()
            row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
            if not row:
                return "Project not found. Use /search to find the id."
            return (
                f"<b>{row['name']}</b>\nClient: {row['client']}\nLocation: {row['location']}\n"
                f"Status: {row['status']}\nScore: {row['opportunity_score']}/100\n"
                f"Confidence: {row['overall_confidence']}/100\nQC: {row['qc_decision']} — {row['qc_reason']}"
            )
    return ""
