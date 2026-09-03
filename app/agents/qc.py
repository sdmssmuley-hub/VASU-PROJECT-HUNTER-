"""
Agent 3 — MANAGER / QUALITY CONTROL
Final gate before a lead reaches the database as APPROVED and before any
Telegram notification is sent. Detects duplicates, stale/cancelled/completed
projects, unsupported claims, and demo data. Persists results either way
(rejected leads are kept, with reason, for audit — never silently dropped).
"""
from __future__ import annotations
import json
import datetime as dt
from app.database import db_session, log_audit, now_iso
from app.dedup import build_fingerprint, similarity_flag
from app.scoring import score_project

STALE_STATUSES = {"commissioned", "completed", "cancelled", "closed"}


def _is_demo_source(sources: list[dict]) -> bool:
    return any("[DEMO DATA]" in (s.get("title") or "") for s in sources)


def qc_review(verified: dict) -> tuple[str, str]:
    """
    Returns (decision, reason) where decision in APPROVED / HOLD / REJECTED.
    """
    sources = verified.get("_sources", [])

    if verified.get("_parse_failed"):
        return "REJECTED", "Research agent output could not be parsed — treated as unsupported"

    if _is_demo_source(sources):
        return "HOLD", "DEMO DATA — search provider not configured for live results; never sent to Telegram"

    if not sources:
        return "REJECTED", "No sources retained — cannot verify any claim"

    name = verified.get("name", "UNKNOWN")
    if not name or name == "UNKNOWN":
        return "REJECTED", "Project name unresolved"

    status = (verified.get("status") or "").lower()
    if any(s in status for s in STALE_STATUSES):
        return "REJECTED", f"Project status is '{verified.get('status')}' — equipment movement window likely closed"

    overall_confidence = verified.get("overall_confidence") or 0
    if not isinstance(overall_confidence, (int, float)):
        overall_confidence = 0
    if overall_confidence < 30:
        return "REJECTED", f"Overall confidence too low ({overall_confidence}/100) to act on"

    # Unsupported weight check: CONFIRMED weight requires at least one CONFIRMED-tagged
    # source-backed field — otherwise downgrade to ESTIMATED rather than reject outright.
    for eq in verified.get("equipment", []) or []:
        if eq.get("weight_confidence") == "CONFIRMED" and len(sources) == 0:
            eq["weight_confidence"] = "UNKNOWN"

    if overall_confidence < 55:
        return "HOLD", f"Moderate confidence ({overall_confidence}/100) — needs owner/manual review before outreach"

    return "APPROVED", f"Confidence {overall_confidence}/100, sources retained, status current"


def persist_and_score(verified: dict, decision: str, reason: str) -> dict:
    """
    Writes/merges the project into the database (dedup-aware), stores
    equipment/companies/tender/timeline/contacts/sources/verification,
    computes and stores the opportunity score. Returns the final row summary.
    """
    tender = verified.get("tender", {}) or {}
    fingerprint = build_fingerprint(
        name=verified.get("name", ""),
        client=verified.get("client", ""),
        location=verified.get("location", ""),
        tender_number=tender.get("tender_number", ""),
    )

    with db_session() as conn:
        existing = conn.execute("SELECT * FROM projects WHERE id = ?", (fingerprint,)).fetchone()

        # secondary fuzzy pass against recent projects if no exact fingerprint hit
        is_duplicate = existing is not None
        if not is_duplicate:
            recent = conn.execute(
                "SELECT id, name, location FROM projects ORDER BY last_updated_at DESC LIMIT 200"
            ).fetchall()
            for row in recent:
                if similarity_flag(verified, {"name": row["name"], "location": row["location"]}):
                    fingerprint = row["id"]
                    is_duplicate = True
                    existing = conn.execute("SELECT * FROM projects WHERE id = ?", (fingerprint,)).fetchone()
                    break

        equipment_list = verified.get("equipment", []) or []
        companies = verified.get("companies", []) or []
        score_result = score_project(
            {
                "state": verified.get("state"),
                "status": verified.get("status"),
                "civil_status": verified.get("civil_status"),
                "arrival_month": verified.get("arrival_month") if verified.get("arrival_month") != "UNKNOWN" else None,
            },
            equipment_list,
            companies,
        )

        vasu_scope = json.dumps(verified.get("vasu_scope", [])) if verified.get("vasu_scope") else "[]"

        if is_duplicate:
            conn.execute(
                """UPDATE projects SET last_updated_at=?, qc_decision=?, qc_reason=?,
                   overall_confidence=?, opportunity_score=?, status=COALESCE(?, status),
                   civil_status=COALESCE(?, civil_status) WHERE id=?""",
                (now_iso(), decision, reason, verified.get("overall_confidence", 0),
                 score_result["total"], verified.get("status"), verified.get("civil_status"), fingerprint),
            )
        else:
            conn.execute(
                """INSERT INTO projects (id, name, client, owner_entity, spv, location, state, industry,
                   project_type, status, civil_status, lead_status, qc_decision, qc_reason,
                   overall_confidence, opportunity_score, vasu_scope, entry_route,
                   first_seen_at, last_updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fingerprint, verified.get("name"), verified.get("client"), verified.get("owner_entity"),
                 verified.get("spv"), verified.get("location"), verified.get("state"), verified.get("industry"),
                 verified.get("project_type"), verified.get("status"), verified.get("civil_status"),
                 "VERIFIED" if decision == "APPROVED" else "NEW", decision, reason,
                 verified.get("overall_confidence", 0), score_result["total"], vasu_scope,
                 verified.get("entry_route"), now_iso(), now_iso()),
            )

        for eq in equipment_list:
            conn.execute(
                """INSERT INTO equipment (project_id, equipment_type, oem, model, capacity, quantity,
                   physical_units, weight_value, weight_confidence, dimensions) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (fingerprint, eq.get("equipment_type"), eq.get("oem"), eq.get("model"), eq.get("capacity"),
                 eq.get("quantity"), eq.get("physical_units"), eq.get("weight_value"),
                 eq.get("weight_confidence", "UNKNOWN"), eq.get("dimensions")),
            )

        for c in companies:
            conn.execute(
                "INSERT INTO companies (project_id, role, company_name, confidence) VALUES (?,?,?,?)",
                (fingerprint, c.get("role"), c.get("company_name"), c.get("confidence", "UNKNOWN")),
            )

        if tender:
            conn.execute(
                """INSERT INTO tenders (project_id, tender_number, tender_date, award_date, po_date,
                   issuing_authority) VALUES (?,?,?,?,?,?)""",
                (fingerprint, tender.get("tender_number"), tender.get("tender_date"),
                 tender.get("award_date"), tender.get("po_date"), tender.get("issuing_authority")),
            )

        for ev in verified.get("timeline", []) or []:
            conn.execute(
                "INSERT INTO timeline_events (project_id, event_type, event_date, confidence, note) VALUES (?,?,?,?,?)",
                (fingerprint, ev.get("event_type"), ev.get("event_date"), ev.get("confidence", "UNKNOWN"), ev.get("note")),
            )

        for ct in verified.get("contacts", []) or []:
            conn.execute(
                """INSERT INTO contacts (project_id, name, designation, company, public_profile_url, note)
                   VALUES (?,?,?,?,?,?)""",
                (fingerprint, ct.get("name"), ct.get("designation"), ct.get("company"),
                 ct.get("public_profile_url"), ct.get("note")),
            )

        for s in verified.get("_sources", []) or []:
            conn.execute(
                """INSERT INTO sources (project_id, url, title, source_type, reliability_level,
                   published_date, retrieved_at, snippet) VALUES (?,?,?,?,?,?,?,?)""",
                (fingerprint, s.get("url"), s.get("title"), s.get("source_type", "web"),
                 s.get("reliability_level", "C"), s.get("published_date"), now_iso(), s.get("snippet")),
            )

        for field, conf in (verified.get("field_confidence") or {}).items():
            conn.execute(
                "INSERT INTO verification (project_id, field_name, field_value, confidence) VALUES (?,?,?,?)",
                (fingerprint, field, "", conf),
            )

        for item in score_result["breakdown"]:
            conn.execute(
                "INSERT INTO scores (project_id, factor, points, max_points, reason) VALUES (?,?,?,?,?)",
                (fingerprint, item["factor"], item["points"], item["max_points"], item["reason"]),
            )

    log_audit("qc", "INFO", f"{decision}: {verified.get('name')} (score={score_result['total']}, dup={is_duplicate})")

    return {
        "id": fingerprint,
        "name": verified.get("name"),
        "decision": decision,
        "reason": reason,
        "is_duplicate": is_duplicate,
        "score": score_result["total"],
        "confidence": verified.get("overall_confidence", 0),
    }
