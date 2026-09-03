"""
Wires the three agents together for one scheduled run:
  Search -> Research -> Verify -> Score -> QC -> Database -> Telegram
Also builds the 09:00-18:00 rotation (see ROTATION) and the end-of-day
daily report.
"""
from __future__ import annotations
import datetime as dt
from app.database import db_session, log_audit, now_iso
from app.agents.hunter import run_hunter
from app.agents.research import run_research
from app.agents.qc import qc_review, persist_and_score
from app.telegram_bot import (
    queue_message, send_pending, format_project_card,
    format_run_report, format_daily_report, format_system_alert,
)
from app.config import settings

ROTATION = {
    9: "powergrid_msetcl",
    10: "transformer_tenders",
    11: "maharashtra_industrial",
    12: "gujarat_industrial",
    13: "steel_forging_presses",
    14: "power_transmission",
    15: "oem_announcements",
    16: "epc_announcements",
    17: "tender_awards",
    18: "deep_verification",
}


def _project_card_dict(row: dict, equipment_summary: str, weight: str, oem: str, epc: str, source_count: int) -> dict:
    return {
        "name": row["name"], "client": row["client"], "location": row["location"],
        "status": row["status"], "equipment_summary": equipment_summary, "weight": weight,
        "arrival_month": "UNKNOWN", "oem": oem, "epc": epc,
        "vasu_scope": row["vasu_scope"], "entry_route": row["entry_route"],
        "score": row["opportunity_score"], "confidence": row["overall_confidence"],
        "source_count": source_count,
    }


def run_cycle(hour: int | None = None, target_leads: int | None = None) -> dict:
    """
    Executes one full search->research->QC cycle. `hour` selects the rotation
    category (falls back to current local hour); pass None from the manual
    "run now" API to use whatever hour it currently is.
    """
    category = ROTATION.get(hour) if hour is not None else None
    target = target_leads or settings.TARGET_LEADS_PER_RUN
    started = now_iso()
    label = f"{hour:02d}:00 {category}" if hour is not None else "Manual run"

    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO research_runs (run_started_at, run_label, status) VALUES (?,?,?)",
            (started, label, "running"),
        )
        run_id = cur.lastrowid

    stats = {"candidates": 0, "duplicates": 0, "rejected": 0, "verified": 0, "high_priority": 0}
    approved_this_run = []

    try:
        candidates = run_hunter(category, run_id, max_queries=15)
        stats["candidates"] = len(candidates)

        for candidate in candidates:
            if len(approved_this_run) >= target:
                break  # 4 is a target, not a fabrication requirement — stop once met, never pad
            try:
                verified = run_research(candidate)
                decision, reason = qc_review(verified)
                result = persist_and_score(verified, decision, reason)

                if result["is_duplicate"]:
                    stats["duplicates"] += 1
                if decision == "REJECTED":
                    stats["rejected"] += 1
                if decision == "APPROVED":
                    stats["verified"] += 1
                    if result["score"] >= 70:
                        stats["high_priority"] += 1
                    approved_this_run.append(result)
            except Exception as e:
                log_audit("orchestrator", "ERROR", f"Candidate processing failed: {e}")
                stats["rejected"] += 1
                continue

        # send Telegram cards for newly approved, non-duplicate, high/medium-value leads
        with db_session() as conn:
            for result in approved_this_run:
                row = conn.execute("SELECT * FROM projects WHERE id=?", (result["id"],)).fetchone()
                if not row:
                    continue
                eq = conn.execute("SELECT * FROM equipment WHERE project_id=?", (result["id"],)).fetchall()
                companies = conn.execute("SELECT * FROM companies WHERE project_id=?", (result["id"],)).fetchall()
                sources = conn.execute("SELECT * FROM sources WHERE project_id=?", (result["id"],)).fetchall()

                eq_summary = ", ".join(f"{e['equipment_type'] or 'UNKNOWN'} ({e['capacity'] or 'UNKNOWN'})" for e in eq) or "UNKNOWN"
                weight = eq[0]["weight_value"] if eq and eq[0]["weight_value"] else "UNKNOWN"
                oem = next((c["company_name"] for c in companies if c["role"] == "OEM"), "UNKNOWN")
                epc = next((c["company_name"] for c in companies if c["role"] == "EPC"), "UNKNOWN")

                card = _project_card_dict(dict(row), eq_summary, weight, oem or "UNKNOWN", epc or "UNKNOWN", len(sources))
                queue_message(format_project_card(card), project_id=result["id"])

        with db_session() as conn:
            conn.execute(
                """UPDATE research_runs SET run_finished_at=?, candidates=?, duplicates=?, rejected=?,
                   verified=?, high_priority=?, status='completed' WHERE id=?""",
                (now_iso(), stats["candidates"], stats["duplicates"], stats["rejected"],
                 stats["verified"], stats["high_priority"], run_id),
            )

        queue_message(format_run_report({**stats, "run_label": label}))
        send_pending()

    except Exception as e:
        log_audit("orchestrator", "ERROR", f"Run {run_id} failed entirely: {e}")
        with db_session() as conn:
            conn.execute("UPDATE research_runs SET status='failed', run_finished_at=? WHERE id=?", (now_iso(), run_id))
        queue_message(format_system_alert("orchestrator", str(e)))
        send_pending()

    return {"run_id": run_id, **stats}


def run_daily_report() -> dict:
    today = dt.date.today().isoformat()
    with db_session() as conn:
        runs = conn.execute(
            "SELECT * FROM research_runs WHERE run_started_at LIKE ?", (f"{today}%",)
        ).fetchall()
        totals = {"runs": len(runs), "candidates": 0, "duplicates": 0, "rejected": 0, "verified": 0, "high_priority": 0}
        for r in runs:
            for k in ("candidates", "duplicates", "rejected", "verified", "high_priority"):
                totals[k] += r[k] or 0

        top = conn.execute(
            "SELECT * FROM projects WHERE qc_decision='APPROVED' ORDER BY opportunity_score DESC LIMIT 5"
        ).fetchall()
        top_list = [{"name": p["name"], "score": p["opportunity_score"]} for p in top]

        state_row = conn.execute(
            """SELECT state, COUNT(*) c FROM projects WHERE qc_decision='APPROVED'
               GROUP BY state ORDER BY c DESC LIMIT 1"""
        ).fetchone()
        industry_row = conn.execute(
            """SELECT industry, COUNT(*) c FROM projects WHERE qc_decision='APPROVED'
               GROUP BY industry ORDER BY c DESC LIMIT 1"""
        ).fetchone()
        equipment_row = conn.execute(
            """SELECT equipment_type, COUNT(*) c FROM equipment
               JOIN projects ON projects.id = equipment.project_id
               WHERE projects.qc_decision='APPROVED' GROUP BY equipment_type ORDER BY c DESC LIMIT 1"""
        ).fetchone()
        highest = conn.execute("SELECT MAX(opportunity_score) m FROM projects").fetchone()

    summary = {
        **totals,
        "top_opportunities": top_list,
        "top_state": state_row["state"] if state_row else "UNKNOWN",
        "top_industry": industry_row["industry"] if industry_row else "UNKNOWN",
        "top_equipment": equipment_row["equipment_type"] if equipment_row else "UNKNOWN",
        "highest_score": highest["m"] if highest and highest["m"] else 0,
    }
    queue_message(format_daily_report(summary))
    send_pending()
    return summary
