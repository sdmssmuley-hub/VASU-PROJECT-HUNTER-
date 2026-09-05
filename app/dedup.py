"""
Duplicate detection. Builds a stable fingerprint from normalized
project name + client + location (+ tender number / equipment when present)
so the same project reported by 10 different websites collapses to ONE row,
with all sources merged onto it.
"""
import hashlib
import re


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # drop generic filler words that cause false negatives/positives
    for stop in [" limited", " ltd", " pvt", " private", " project", " substation", " the "]:
        text = text.replace(stop, " ")
    return re.sub(r"\s+", " ", text).strip()


def build_fingerprint(name: str, client: str = "", location: str = "",
                       tender_number: str = "", equipment: str = "") -> str:
    """
    Primary key: tender_number if we have one (most reliable unique identifier).
    Otherwise: normalized name + client + location.
    """
    tender_norm = _normalize(tender_number)
    if tender_norm:
        basis = f"tender::{tender_norm}"
    else:
        basis = "|".join([_normalize(name), _normalize(client), _normalize(location)])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def similarity_flag(a: dict, b: dict) -> bool:
    """
    Secondary fuzzy check for near-duplicates that don't share a tender number
    (e.g. slightly different name spellings). Simple token-overlap heuristic —
    intentionally conservative to avoid merging genuinely different projects.
    """
    name_a, name_b = _normalize(a.get("name")), _normalize(b.get("name"))
    loc_a, loc_b = _normalize(a.get("location")), _normalize(b.get("location"))
    if not name_a or not name_b:
        return False
    tokens_a, tokens_b = set(name_a.split()), set(name_b.split())
    if not tokens_a or not tokens_b:
        return False
    overlap = len(tokens_a & tokens_b) / max(1, min(len(tokens_a), len(tokens_b)))
    return overlap >= 0.7 and loc_a == loc_b
