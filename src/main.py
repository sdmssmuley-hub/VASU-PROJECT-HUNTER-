import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

from src import config
from src.database.db import init_db
from src.database import models
from src.hunter.search import discover_candidates
from src.hunter.extraction import (
    build_analysis_prompt, parse_gemini_json, parse_weight_tonnes, months_until,
)
from src.hunter.scoring import compute_score, classify_priority
from src.hunter.deduplication import compute_fingerprint, generate_project_id
from src.hunter.change_detection import detect_material_change
from src.gemini_client import ask_gemini
from src.notifications.telegram import send_telegram_message
from src.reporting.telegram_format import (
    format_project_alert, format_schedule_change, format_no_new_leads,
    format_daily_digest,
)

IST_OFFSET_HOURS = 5.5


def _ist_now():
    from datetime import timedelta
    return datetime.now(timezone.utc) + timedelta(hours=IST_OFFSET_HOURS)


def _int_or_none(text):
    if not text:
        return None
    m = re.search(r"\d+", str(text))
    return int(m.group()) if m else None


def _build_record(parsed: dict, candidate: dict) -> dict:
    actual_weight_raw = parsed.get("actual_weight") or ""
    record = {
        "project_name": parsed.get("project_name") or candidate.get("title"),
        "client": parsed.get("client"),
        "location": parsed.get("location"),
        "state": parsed.get("state"),
        "industry": parsed.get("industry"),
        "project_type": parsed.get("project_type"),
        "project_status": parsed.get("project_status"),
        "civil_status": parsed.get("civil_status"),
        "equipment_name": parsed.get("equipment_name"),
        "equipment_rating": parsed.get("equipment_rating"),
        "actual_weight_raw": actual_weight_raw,
        "actual_weight_tonnes": parse_weight_tonnes(actual_weight_raw),
        "heaviest_package_weight_raw": parsed.get("heaviest_package_weight"),
        "quantity": _int_or_none(parsed.get("quantity")),
        "oem": parsed.get("oem"),
        "epc": parsed.get("epc"),
        "installation_contractor": parsed.get("installation_contractor"),
        "heavy_lift_contractor": parsed.get("heavy_lift_contractor"),
        "logistics_contractor": parsed.get("logistics_contractor"),
        "transporter": parsed.get("transporter"),
        "po_status": parsed.get("po_status"),
        "dispatch_date": parsed.get("dispatch_date"),
        "arrival_date": parsed.get("arrival_date"),
        "installation_date": parsed.get("installation_date"),
        "commissioning_date": parsed.get("commissioning_date"),
        "vasu_scope": parsed.get("vasu_scope"),
        "entry_point": parsed.get("entry_point"),
        "estimated_contract_value": parsed.get("estimated_contract_value"),
        "confidence": parsed.get("confidence"),
        "why_relevant": parsed.get("why_relevant"),
        "source_url": candidate.get("source_url"),
        "evidence": json.dumps({
            "raw_evidence": parsed.get("evidence"),
            "query": candidate.get("query"),
            "snippet": (candidate.get("snippet") or "")[:1000],
        }, ensure_ascii=False),
    }
    record["months_to_arrival"] = months_until(record["arrival_date"])
    return record


def _is_maharashtra(record: dict) -> bool:
    text = f"{record.get('location') or ''} {record.get('state') or ''}".lower()
    if "maharashtra" in text:
        return True
    return any(r.lower() in text for r in config.TIER1_REGIONS)


def run_hunter_cycle():
    stats = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "queries_run": 0, "queries_failed": 0, "urls_discovered": 0,
        "candidates_analyzed": 0, "qualified": 0, "rejected": 0,
        "duplicates": 0, "new_projects": 0, "schedule_changes": 0,
        "alerts_sent": 0, "hot_count": 0, "high_count": 0, "medium_count": 0,
        "error": None,
    }

    bot = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not bot or not chat:
        raise RuntimeError("Telegram secrets not configured")

    candidates, search_stats = discover_candidates()
    stats.update({
        "queries_run": search_stats["queries_run"],
        "queries_failed": search_stats["queries_failed"],
        "urls_discovered": search_stats["urls_discovered"],
    })

    if search_stats["queries_run"] and search_stats["queries_failed"] == search_stats["queries_run"]:
        raise RuntimeError(
            "All search queries failed this run - check GEMINI_API_KEY / "
            "grounding availability before assuming there are simply no leads."
        )

    new_lead_alert_candidates = []   # newly discovered, score >= alert threshold
    schedule_change_alerts = []      # (record, changes) for already-known projects

    for c in candidates:
        stats["candidates_analyzed"] += 1
        prompt = build_analysis_prompt(c.get("snippet", ""), c.get("source_url", ""))
        try:
            raw = ask_gemini(prompt, max_tokens=config.MAX_GEMINI_TOKENS)
        except Exception as e:
            print(f"[analyze] {c.get('source_url')} failed: {e}")
            stats["rejected"] += 1
            models.log_rejected(c.get("source_url"), f"gemini_error: {e}")
            continue

        parsed = parse_gemini_json(raw)
        if not parsed:
            stats["rejected"] += 1
            models.log_rejected(c.get("source_url"), "unparseable_response")
            continue

        try:
            confidence_score = float(parsed.get("confidence_score", 0))
        except (TypeError, ValueError):
            confidence_score = 0.0

        if confidence_score < 4:
            stats["rejected"] += 1
            models.log_rejected(c.get("source_url"), "below_genuine_lead_threshold")
            continue

        record = _build_record(parsed, c)
        record["lead_score"] = compute_score(record)
        record["priority"] = classify_priority(record["lead_score"])

        if record["lead_score"] < config.MIN_SCORE_TO_STORE:
            stats["rejected"] += 1
            models.log_rejected(c.get("source_url"), "score_below_store_threshold")
            continue

        fingerprint = compute_fingerprint(record)
        record["fingerprint"] = fingerprint
        existing = models.get_project_by_fingerprint(fingerprint)

        if existing:
            stats["duplicates"] += 1
            changes = detect_material_change(existing, record)
            record["project_id"] = existing["project_id"]
            # keep previously-known values where the new extraction found nothing new
            for k, v in list(record.items()):
                if v in (None, "") and existing.get(k) not in (None, ""):
                    record[k] = existing[k]
            models.upsert_project(record, is_new=False)
            if changes:
                stats["schedule_changes"] += 1
                schedule_change_alerts.append((record, changes))
        else:
            record["project_id"] = generate_project_id(record, fingerprint, datetime.now().year)
            models.upsert_project(record, is_new=True)
            stats["new_projects"] += 1
            if record["lead_score"] >= config.MIN_SCORE_TO_ALERT:
                new_lead_alert_candidates.append(record)

        stats["qualified"] += 1
        stats[f"{record['priority'].lower()}_count"] = stats.get(f"{record['priority'].lower()}_count", 0) + 1

    # ---- hourly Telegram selection (Sections 23-24, 62-64) ----
    new_lead_alert_candidates.sort(key=lambda r: r["lead_score"], reverse=True)
    mh_leads = [r for r in new_lead_alert_candidates if _is_maharashtra(r)]
    other_leads = [r for r in new_lead_alert_candidates if not _is_maharashtra(r)]

    selected = []
    selected.extend(mh_leads[:2])
    remaining_slots = config.MAX_TELEGRAM_ALERTS_PER_RUN - len(selected)
    selected.extend(other_leads[:remaining_slots])
    remaining_slots = config.MAX_TELEGRAM_ALERTS_PER_RUN - len(selected)
    if remaining_slots > 0:
        already_ids = {r["project_id"] for r in selected}
        for r in new_lead_alert_candidates:
            if remaining_slots <= 0:
                break
            if r["project_id"] not in already_ids:
                selected.append(r)
                remaining_slots -= 1

    for record, changes in schedule_change_alerts[:4]:
        msg = format_schedule_change(record, changes)
        try:
            msg_id = send_telegram_message(bot, chat, msg)
            models.log_alert(record["project_id"], "SCHEDULE_CHANGE", msg, "SENT", msg_id)
            stats["alerts_sent"] += 1
        except Exception as e:
            models.log_alert(record["project_id"], "SCHEDULE_CHANGE", msg, "FAILED")
            print(f"[telegram] schedule-change alert failed: {e}")

    if selected:
        for record in selected:
            msg = format_project_alert(record)
            alert_type = f"NEW_{record['priority']}"
            try:
                msg_id = send_telegram_message(bot, chat, msg)
                models.log_alert(record["project_id"], alert_type, msg, "SENT", msg_id)
                models.mark_alerted(record["fingerprint"], record["priority"])
                stats["alerts_sent"] += 1
            except Exception as e:
                models.log_alert(record["project_id"], alert_type, msg, "FAILED")
                print(f"[telegram] project alert failed: {e}")
    elif not schedule_change_alerts:
        try:
            send_telegram_message(bot, chat, format_no_new_leads())
        except Exception as e:
            print(f"[telegram] 'no new leads' message failed: {e}")

    # ---- daily digest on the last scheduled run of the day (18:00 IST) ----
    ist_now = _ist_now()
    if ist_now.hour == 18:
        day_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        run_rows = models.get_todays_runs(day_prefix)
        hot = models.get_open_projects_by_priority(["HOT"], limit=20)
        high = models.get_open_projects_by_priority(["HIGH"], limit=20)
        medium = models.get_open_projects_by_priority(["MEDIUM", "WATCH"], limit=20)
        digest = format_daily_digest(hot, high, medium, run_rows)
        try:
            send_telegram_message(bot, chat, digest)
        except Exception as e:
            print(f"[telegram] daily digest failed: {e}")

    stats["finished_at"] = datetime.now(timezone.utc).isoformat()
    models.log_run(stats)
    print("RUN SUMMARY:", json.dumps(stats, indent=2))


def test_telegram():
    bot = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not bot or not chat:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set.")
        sys.exit(1)
    send_telegram_message(bot, chat, "✅ Vasu Lead Hunter: Telegram test message. Setup looks good.")
    print("Test message sent.")


def health_check():
    snapshot = models.health_snapshot()
    print(json.dumps(snapshot, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description="Vasu Engineering Project Hunter AI Agent")
    parser.add_argument("--run-once", action="store_true", help="Run a single hunter cycle (default behavior)")
    parser.add_argument("--test-telegram", action="store_true", help="Send a Telegram test message and exit")
    parser.add_argument("--health-check", action="store_true", help="Print DB/health snapshot and exit")
    args = parser.parse_args()

    init_db()

    if args.test_telegram:
        test_telegram()
        return
    if args.health_check:
        health_check()
        return

    run_hunter_cycle()


if __name__ == "__main__":
    main()
