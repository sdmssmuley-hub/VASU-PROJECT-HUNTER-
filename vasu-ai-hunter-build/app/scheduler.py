"""
Scheduler: runs the hunt cycle at each configured hour (default 9-18 IST),
and the daily report right after the 18:00 run. Uses APScheduler's
BackgroundScheduler so it runs inside the same process as the FastAPI app —
one process to keep alive (systemd/pm2/docker restart-policy handles that).
"""
from __future__ import annotations
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.config import settings
from app.database import log_audit
from app.orchestrator import run_cycle, run_daily_report

_scheduler: BackgroundScheduler | None = None


def _safe_run_cycle(hour: int):
    try:
        run_cycle(hour=hour)
    except Exception as e:
        log_audit("scheduler", "ERROR", f"Scheduled run for hour {hour} crashed: {e}")


def _safe_daily_report():
    try:
        run_daily_report()
    except Exception as e:
        log_audit("scheduler", "ERROR", f"Daily report crashed: {e}")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    sched = BackgroundScheduler(timezone=settings.TIMEZONE)
    for hour in settings.RUN_HOURS:
        sched.add_job(
            _safe_run_cycle, CronTrigger(hour=hour, minute=0),
            args=[hour], id=f"run_{hour}", replace_existing=True,
        )

    last_hour = max(settings.RUN_HOURS) if settings.RUN_HOURS else 18
    sched.add_job(
        _safe_daily_report, CronTrigger(hour=last_hour, minute=30),
        id="daily_report", replace_existing=True,
    )

    sched.start()
    log_audit("scheduler", "INFO", f"Scheduler started — runs at hours {settings.RUN_HOURS} {settings.TIMEZONE}")
    _scheduler = sched
    return sched


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
