"""
One-shot entrypoint for running VASU AI Project Hunter inside GitHub Actions.

Why this exists: app/main.py + app/scheduler.py were built for an always-on
server (FastAPI + APScheduler) that needs a process kept alive 24/7. GitHub
Actions runners are ephemeral — they start, run one job, and stop. So instead
of starting a server, this script does ONE thing and exits:

    init database -> run one hunt cycle for the current/given hour -> exit

GitHub Actions' own cron schedule decides *when* to run this (see
.github/workflows/hourly-hunt.yml); this script just decides *what* to do
once it's running.

Usage:
    python -m app.run_once                  # uses current IST hour
    python -m app.run_once --hour 9          # forces a specific rotation hour
    python -m app.run_once --daily-report    # sends the end-of-day summary
"""
from __future__ import annotations
import argparse
import datetime as dt
import sys

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 fallback, not expected here
    ZoneInfo = None

from app.database import init_db, log_audit
from app.orchestrator import run_cycle, run_daily_report, ROTATION
from app.config import settings


def _current_configured_hour() -> int:
    """Current hour in the configured TIMEZONE (default Asia/Kolkata / IST)."""
    if ZoneInfo is not None:
        try:
            return dt.datetime.now(ZoneInfo(settings.TIMEZONE)).hour
        except Exception as e:
            log_audit("run_once", "WARNING", f"Timezone lookup failed ({e}), falling back to UTC+5:30")
    # Fallback: assume IST (UTC+5:30) if zoneinfo/tzdata isn't available.
    return (dt.datetime.utcnow() + dt.timedelta(hours=5, minutes=30)).hour


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one VASU AI Project Hunter cycle and exit.")
    parser.add_argument("--hour", type=int, default=None,
                         help="Rotation hour (9-18). Defaults to the current hour in TIMEZONE.")
    parser.add_argument("--daily-report", action="store_true",
                         help="Send the end-of-day summary instead of running a hunt cycle.")
    args = parser.parse_args()

    init_db()
    log_audit("run_once", "INFO", "GitHub Actions run started")

    if args.daily_report:
        result = run_daily_report()
        print(f"Daily report sent: {result}")
        return 0

    hour = args.hour if args.hour is not None else _current_configured_hour()
    if hour not in ROTATION:
        print(f"Hour {hour} is outside the configured rotation {sorted(ROTATION)} "
              f"-> running a general (non category-specific) cycle instead.")
        hour = None

    result = run_cycle(hour=hour)
    print(f"Cycle complete: {result}")

    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        print("WARNING: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — results were saved to the "
              "database but nothing was sent to Telegram.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
