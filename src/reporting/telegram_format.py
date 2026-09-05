from datetime import datetime

NOT_PUBLIC = "Not publicly disclosed — requires direct verification."


def _g(record: dict, key: str) -> str:
    val = record.get(key)
    return val if val not in (None, "") else NOT_PUBLIC


def format_project_alert(record: dict) -> str:
    """Section 25 hot/high alert format."""
    priority = record.get("priority", "MEDIUM")
    header = "🚨 VASU ENGINEERING — HOT PROJECT" if priority == "HOT" else \
             f"📌 VASU ENGINEERING — {priority} PRIORITY PROJECT"

    msg = f"{header}\n\n"
    msg += f"Project:\n{_g(record, 'project_name')}\n\n"
    msg += f"Client:\n{_g(record, 'client')}\n\n"
    msg += f"Location:\n{_g(record, 'location')}\n\n"
    msg += f"Industry:\n{_g(record, 'industry')}\n\n"
    msg += f"Current Status:\n{_g(record, 'project_status')}\n\n"
    msg += f"Civil Status:\n{_g(record, 'civil_status')}\n\n"
    msg += f"Heavy Equipment:\n{_g(record, 'equipment_name')}\n\n"
    msg += f"Quantity:\n{_g(record, 'quantity')}\n\n"
    msg += f"Actual Physical Weight:\n{_g(record, 'actual_weight_raw')}\n\n"
    msg += f"Equipment Rating:\n{_g(record, 'equipment_rating')}\n\n"
    msg += f"OEM:\n{_g(record, 'oem')}\n\n"
    msg += f"EPC:\n{_g(record, 'epc')}\n\n"
    msg += f"Installation Contractor:\n{_g(record, 'installation_contractor')}\n\n"
    msg += f"Heavy-Lift Contractor:\n{_g(record, 'heavy_lift_contractor')}\n\n"
    msg += f"Transporter:\n{_g(record, 'transporter')}\n\n"
    msg += f"Expected Dispatch:\n{_g(record, 'dispatch_date')}\n\n"
    msg += f"Expected Site Arrival:\n{_g(record, 'arrival_date')}\n\n"
    msg += f"Expected Installation:\n{_g(record, 'installation_date')}\n\n"
    msg += f"Expected Commissioning:\n{_g(record, 'commissioning_date')}\n\n"
    msg += f"Potential Vasu Scope:\n{_g(record, 'vasu_scope')}\n\n"
    msg += f"Best Entry Point:\n{_g(record, 'entry_point')}\n\n"
    msg += f"Lead Score:\n{record.get('lead_score')}/100\n\n"
    msg += f"Priority:\n{priority}\n\n"
    msg += f"Confidence:\n{_g(record, 'confidence')}\n\n"
    msg += f"Why this lead matters:\n{_g(record, 'why_relevant')}\n\n"
    msg += f"Evidence:\n{_g(record, 'source_url')}\n"
    return msg


def format_schedule_change(record: dict, changes: list) -> str:
    """Section 29 schedule/material-change alert."""
    msg = "⚡ SCHEDULE / DETAIL CHANGE\n\n"
    msg += f"Project:\n{_g(record, 'project_name')}\n\n"
    msg += f"Client:\n{_g(record, 'client')}\n\n"
    for ch in changes:
        msg += f"{ch['field'].replace('_', ' ').title()}:\n"
        msg += f"  Previous: {ch['previous'] or NOT_PUBLIC}\n"
        msg += f"  New: {ch['new']}\n\n"
    msg += f"Source:\n{_g(record, 'source_url')}\n\n"
    msg += f"Vasu Action:\nRe-verify and, if still relevant, contact {_g(record, 'entry_point')}.\n"
    return msg


def format_no_new_leads() -> str:
    return "🔍 VASU LEAD HUNTER\n\nNo new verified Vasu opportunities discovered in this cycle."


def format_daily_digest(hot, high, medium, run_rows) -> str:
    """Section 48 end-of-day digest, sent on the 18:00 IST run."""
    now = datetime.now()
    msg = f"📊 VASU ENGINEERING — DAILY HUNTER DIGEST\n{now.strftime('%d %b %Y')}\n\n"

    def _list(title, rows):
        out = f"### {title}\n"
        if not rows:
            out += "None today.\n\n"
            return out
        for r in rows:
            out += (
                f"- {r.get('project_name', 'Untitled')} | {r.get('client', NOT_PUBLIC)} | "
                f"{r.get('location', NOT_PUBLIC)} | Score {r.get('lead_score')}/100\n"
            )
        return out + "\n"

    msg += _list("HOT LEADS", hot)
    msg += _list("HIGH LEADS", high)
    msg += _list("MEDIUM / WATCH", medium)

    total_queries = sum(r.get("queries_run") or 0 for r in run_rows)
    total_failed = sum(r.get("queries_failed") or 0 for r in run_rows)
    total_scanned = sum(r.get("urls_discovered") or 0 for r in run_rows)
    total_analyzed = sum(r.get("candidates_analyzed") or 0 for r in run_rows)
    total_qualified = sum(r.get("qualified") or 0 for r in run_rows)
    total_alerts = sum(r.get("alerts_sent") or 0 for r in run_rows)
    errors = [r.get("error") for r in run_rows if r.get("error")]

    msg += "### SYSTEM HEALTH TODAY\n"
    msg += f"Runs completed: {len(run_rows)}\n"
    msg += f"Search queries: {total_queries} (failed: {total_failed})\n"
    msg += f"URLs scanned: {total_scanned}\n"
    msg += f"Candidates analyzed: {total_analyzed}\n"
    msg += f"Qualified leads: {total_qualified}\n"
    msg += f"Telegram alerts sent: {total_alerts}\n"
    if errors:
        msg += f"Run errors: {len(errors)} (see Actions logs)\n"
    return msg
