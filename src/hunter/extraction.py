"""Section 16/17/59: equipment + project field extraction via Gemini."""

import json
import re
from datetime import datetime

from src.master_context import SYSTEM_INSTRUCTION

NOT_PUBLIC = "Not publicly disclosed — requires direct verification."

# Subset of Section 59's full field list that is practically extractable
# from a single web source in one LLM call. Contact-level personal data
# (Section 51/23) is deliberately excluded - this agent reports
# company-level entry points only.
LEAD_FIELDS = [
    "project_name", "client", "location", "state", "industry", "project_type",
    "project_status", "civil_status",
    "equipment_name", "equipment_rating", "actual_weight",
    "heaviest_package_weight", "quantity",
    "oem", "epc", "installation_contractor", "heavy_lift_contractor",
    "logistics_contractor", "transporter",
    "po_status", "dispatch_date", "arrival_date", "installation_date",
    "commissioning_date",
    "vasu_scope", "entry_point", "estimated_contract_value",
    "confidence", "why_relevant", "evidence",
]

MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def build_analysis_prompt(snippet: str, url: str) -> str:
    field_list = ", ".join(LEAD_FIELDS)
    return (
        f"{SYSTEM_INSTRUCTION}\n\n"
        "---\n"
        "TASK: Analyze the following web source and extract a single lead "
        "record as one JSON object.\n\n"
        f"Required JSON keys (use exactly these names): {field_list}, "
        "confidence_score.\n\n"
        "Rules:\n"
        f"- If a field is not stated in the source, set it to \"{NOT_PUBLIC}\"\n"
        "- Never invent equipment weight, OEM, EPC, contractor names, or dates.\n"
        "- Put equipment RATING (MVA / tonnage capacity / MW) and ACTUAL "
        "PHYSICAL/SHIPPING WEIGHT in their separate fields - never mix them.\n"
        "- Normalize dates to YYYY-MM-DD if a day is known, YYYY-MM if only "
        "the month is known, or \"Q_ YYYY\" if only a quarter/fiscal period "
        "is known - and keep the original wording inside that same field in "
        "parentheses, e.g. \"2026-11 (November 2026)\". Do not fabricate a "
        "day-level date from month-level evidence.\n"
        "- confidence field: one of CONFIRMED, LIKELY, ESTIMATED, NOT PUBLIC, "
        "describing your overall confidence in this lead's key facts.\n"
        "- confidence_score: your own 0-10 numeric self-rating (plain "
        "number) of how strong and actionable this lead is, using the "
        "genuine-lead test above. If the source describes no plausible "
        "heavy-equipment movement opportunity, set confidence_score to 0.\n"
        "- Output ONLY the JSON object - no markdown fences, no commentary.\n\n"
        f"SOURCE URL: {url}\n"
        f"SOURCE CONTENT:\n{snippet}\n"
    )


def parse_gemini_json(text: str) -> dict:
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def parse_weight_tonnes(text):
    """Section 37: normalize tonne/ton/MT/metric ton(ne) wording to a float."""
    if not text:
        return None
    t = str(text).lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mt\b|metric ton(?:ne)?s?|tonnes?|tons?|t\b)", t)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def months_until(date_text, now=None):
    """Approximate months-to-arrival from a normalized/free-text date field."""
    if not date_text:
        return None
    now = now or datetime.utcnow()
    t = str(date_text).lower()

    m = re.search(r"(20\d{2})-(\d{1,2})", t)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
    else:
        m2 = re.search(r"([a-z]+)\s+(20\d{2})", t)
        if m2 and m2.group(1) in MONTH_NAMES:
            year, month = int(m2.group(2)), MONTH_NAMES[m2.group(1)]
        else:
            return None

    return (year - now.year) * 12 + (month - now.month)
