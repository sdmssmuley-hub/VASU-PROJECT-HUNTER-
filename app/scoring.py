"""
Business Opportunity Score: 0-100.
Every factor is logged individually to the `scores` table so the reasoning
is auditable on the project detail page — never a black-box number.
"""
import datetime as dt
from app.config import settings

# (factor_name, max_points)
FACTORS = [
    ("equipment_movement_timing", 20),
    ("equipment_weight", 10),
    ("equipment_quantity", 8),
    ("transformer_reactor_relevance", 10),
    ("project_readiness", 10),
    ("civil_progress", 6),
    ("oem_confirmed", 6),
    ("epc_confirmed", 6),
    ("heavy_handling_contractor_unknown", 8),  # gap = opportunity
    ("geographic_priority", 8),
    ("commercial_potential", 8),
]


def _months_between(target_month: str) -> int | None:
    """target_month like '2026-11'. Returns months from now, or None if unparseable."""
    try:
        y, m = target_month.split("-")
        target = dt.date(int(y), int(m), 1)
        today = dt.date.today()
        return (target.year - today.year) * 12 + (target.month - today.month)
    except Exception:
        return None


def score_project(project: dict, equipment_list: list[dict], companies: list[dict]) -> dict:
    """
    project: dict with keys like state, status, civil_status, arrival_month (YYYY-MM or None)
    equipment_list: list of equipment dicts (weight_value, weight_confidence, capacity, quantity)
    companies: list of {role, company_name}
    Returns {"total": int, "breakdown": [{"factor", "points", "max_points", "reason"}]}
    """
    breakdown = []

    # 1. Equipment movement timing — highest priority Oct-Dec 2026
    arrival_month = project.get("arrival_month")
    pts, reason = 0, "Arrival timing unknown — scored 0"
    if arrival_month:
        if arrival_month in settings.HIGH_PRIORITY_MONTHS:
            pts, reason = 20, f"Arrival {arrival_month} is in highest-priority window (Oct-Dec 2026)"
        else:
            months_out = _months_between(arrival_month)
            if months_out is not None and 0 <= months_out <= 8:
                pts = max(4, 20 - months_out * 2)
                reason = f"Arrival {arrival_month}, {months_out} months out"
            elif months_out is not None and months_out < 0:
                pts, reason = 0, f"Arrival {arrival_month} is in the past — likely stale"
    breakdown.append(("equipment_movement_timing", pts, 20, reason))

    # 2. Equipment weight (heavier = more relevant to Vasu's core capability, 40T-1000T+)
    pts, reason = 0, "No confirmed/estimated weight found"
    for eq in equipment_list:
        conf = eq.get("weight_confidence")
        if conf in ("CONFIRMED", "ESTIMATED"):
            pts = 10 if conf == "CONFIRMED" else 6
            reason = f"Weight {conf.lower()}: {eq.get('weight_value', 'n/a')}"
            break
    breakdown.append(("equipment_weight", pts, 10, reason))

    # 3. Equipment quantity (more units = more scope)
    qty_found = any(eq.get("quantity") for eq in equipment_list)
    pts = 8 if qty_found else 0
    breakdown.append(("equipment_quantity", pts, 8,
                       "Quantity documented" if qty_found else "Quantity unknown"))

    # 4. Transformer/reactor relevance (Vasu's strongest niche)
    core_types = {"transformer", "reactor", "hvdc"}
    relevant = any((eq.get("equipment_type") or "").lower() in core_types for eq in equipment_list)
    pts = 10 if relevant else 4
    breakdown.append(("transformer_reactor_relevance", pts, 10,
                       "Core transformer/reactor equipment" if relevant else "Non-core equipment type"))

    # 5. Project readiness (status)
    status = (project.get("status") or "").lower()
    readiness_map = {"awarded": 10, "under-construction": 8, "tender": 4, "commissioned": 0, "cancelled": 0}
    pts = readiness_map.get(status, 3)
    breakdown.append(("project_readiness", pts, 10, f"Status: {project.get('status') or 'UNKNOWN'}"))

    # 6. Civil progress
    civil = (project.get("civil_status") or "").lower()
    pts = 6 if "advanced" in civil or "complete" in civil else (3 if civil else 0)
    breakdown.append(("civil_progress", pts, 6, project.get("civil_status") or "UNKNOWN"))

    # 7 & 8. OEM / EPC confirmed
    oem_confirmed = any(c.get("role") == "OEM" and c.get("company_name") for c in companies)
    epc_confirmed = any(c.get("role") == "EPC" and c.get("company_name") for c in companies)
    breakdown.append(("oem_confirmed", 6 if oem_confirmed else 0, 6,
                       "OEM identified" if oem_confirmed else "OEM unknown"))
    breakdown.append(("epc_confirmed", 6 if epc_confirmed else 0, 6,
                       "EPC identified" if epc_confirmed else "EPC unknown"))

    # 9. Heavy-lift contractor still unknown = Vasu can still enter
    heavy_lift_known = any(c.get("role") == "Heavy-lift" and c.get("company_name") for c in companies)
    pts = 0 if heavy_lift_known else 8
    breakdown.append(("heavy_handling_contractor_unknown", pts, 8,
                       "Heavy-lift contractor already engaged — harder entry" if heavy_lift_known
                       else "No heavy-lift contractor found yet — open opportunity"))

    # 10. Geographic priority
    state = project.get("state") or ""
    tier = settings.GEO_TIER.get(state, 4)
    tier_points = {1: 8, 2: 6, 3: 4, 4: 2}
    pts = tier_points.get(tier, 2)
    breakdown.append(("geographic_priority", pts, 8, f"{state or 'Unknown state'} — Tier {tier}"))

    # 11. Commercial potential (proxy: MVA/tonnage size mentioned at all)
    size_mentioned = any(eq.get("capacity") for eq in equipment_list)
    pts = 8 if size_mentioned else 2
    breakdown.append(("commercial_potential", pts, 8,
                       "Capacity/size documented" if size_mentioned else "Size not documented"))

    total = sum(b[1] for b in breakdown)
    return {
        "total": min(100, total),
        "breakdown": [
            {"factor": f, "points": p, "max_points": m, "reason": r} for f, p, m, r in breakdown
        ],
    }
