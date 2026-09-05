"""Section 28: persistent project fingerprint + human-readable project_id."""

import hashlib
import re

from src import config


def _slug(text, max_len=12):
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "", text)
    return (text or "unknown")[:max_len]


def compute_fingerprint(record: dict) -> str:
    """
    Identity for deduplication: project name + client + equipment + location.
    Deliberately excludes volatile fields (dates, contractors) so the SAME
    project with an UPDATED schedule is recognized as the same project
    (triggering change_detection) rather than being stored as a new lead.
    """
    key_src = "|".join([
        (record.get("project_name") or "").strip().lower(),
        (record.get("client") or "").strip().lower(),
        (record.get("equipment_name") or "").strip().lower(),
        (record.get("location") or "").strip().lower(),
    ])
    return hashlib.sha256(key_src.encode("utf-8")).hexdigest()


def generate_project_id(record: dict, fingerprint: str, year: int) -> str:
    state = (record.get("state") or record.get("location") or "").lower()
    state_code = "IN"
    for name, code in config.STATE_CODES.items():
        if name in state:
            state_code = code
            break
    client_slug = _slug(record.get("client"))
    equip_slug = _slug(record.get("equipment_name"), max_len=8)
    short_hash = fingerprint[:6].upper()
    return f"VASU-{year}-{state_code}-{client_slug}-{equip_slug}-{short_hash}"
