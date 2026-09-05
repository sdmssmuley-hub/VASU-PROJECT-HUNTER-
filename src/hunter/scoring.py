"""
Section 21/22 scoring: exact 100-point rubric (weight 20 + quantity 15 +
arrival urgency 20 + civil readiness 10 + OEM known 10 + EPC known 10 +
Vasu scope 10 + geography 5) and priority tiers (HOT/HIGH/MEDIUM/WATCH).
"""

from src import config

NOT_PUBLIC_MARKER = "not publicly disclosed"


def _known_level(value_text):
    """CONFIRMED / LIKELY / UNKNOWN based on the field's own wording."""
    t = (value_text or "").lower()
    if not t.strip() or NOT_PUBLIC_MARKER in t:
        return "unknown"
    if "likely" in t or "estimated" in t or "[likely]" in t:
        return "likely"
    return "confirmed"


def score_weight_tonnes(tonnes):
    if tonnes is None:
        return 0
    if tonnes >= 500:
        return 20
    if tonnes >= 300:
        return 17
    if tonnes >= 150:
        return 14
    if tonnes >= 80:
        return 10
    if tonnes >= 40:
        return 4
    return 0


def score_quantity(qty):
    if not qty:
        return 0
    if qty >= 10:
        return 15
    if qty >= 5:
        return 12
    if qty >= 2:
        return 7
    return 3


def score_arrival(months):
    if months is None:
        return 0
    if months < 0:
        return 0  # already past due / likely stale
    if months <= 2:
        return 20
    if months <= 4:
        return 15
    if months <= 6:
        return 10
    return 5


def score_civil(status_text):
    t = (status_text or "").lower()
    if NOT_PUBLIC_MARKER in t or not t.strip():
        return 0
    if any(k in t for k in ["foundation", "piling", "excavation", "anchor bolt"]):
        return 10
    if any(k in t for k in ["construction", "civil work", "structural", "mobiliz"]):
        return 8
    if any(k in t for k in ["pre-construction", "planned", "approval"]):
        return 4
    return 4


def score_known(value_text):
    level = _known_level(value_text)
    return {"confirmed": 10, "likely": 5, "unknown": 0}[level]


def score_vasu_scope(scope_text):
    t = (scope_text or "").lower()
    if NOT_PUBLIC_MARKER in t or not t.strip():
        return 2
    strong = ["unload", "jack", "skid", "rigging", "erection", "shift",
              "position", "upend", "handling"]
    if any(k in t for k in strong):
        return 10
    return 6


def score_geography(location_text, state_text=None):
    t = f"{location_text or ''} {state_text or ''}".lower()
    if any(r.lower() in t for r in config.TIER1_REGIONS) or "maharashtra" in t:
        return 5
    if any(r.lower() in t for r in config.TIER2_REGIONS) or "gujarat" in t:
        return 4
    if t.strip() and NOT_PUBLIC_MARKER not in t:
        return 3
    return 1


def compute_score(record: dict) -> int:
    score = (
        score_weight_tonnes(record.get("actual_weight_tonnes"))
        + score_quantity(record.get("quantity"))
        + score_arrival(record.get("months_to_arrival"))
        + score_civil(record.get("civil_status"))
        + score_known(record.get("oem"))
        + score_known(record.get("epc"))
        + score_vasu_scope(record.get("vasu_scope"))
        + score_geography(record.get("location"), record.get("state"))
    )
    return max(0, min(100, score))


def classify_priority(score: int) -> str:
    if score >= 85:
        return "HOT"
    if score >= 70:
        return "HIGH"
    if score >= 55:
        return "MEDIUM"
    return "WATCH"
