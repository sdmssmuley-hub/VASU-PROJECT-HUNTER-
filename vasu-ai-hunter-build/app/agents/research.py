"""
Agent 2 — RESEARCH & VERIFICATION
For every candidate from the Hunter, digs deeper (additional targeted
searches), and verifies every field with a CONFIRMED / LIKELY / ESTIMATED /
UNKNOWN confidence tag. Never invents a value — UNKNOWN is a valid, expected
and frequent output.
"""
from __future__ import annotations
from app.search_provider import get_fallback_chain
from app.llm_provider import get_llm_provider, safe_json_parse
from app.database import log_audit

RESEARCH_SYSTEM_PROMPT = """You are the RESEARCH & VERIFICATION agent for Vasu Engineering. You are given \
a candidate project plus additional web search results. Verify and structure the following fields. For \
every field, if the source text does not clearly support it, set the value to "UNKNOWN" and confidence to \
"UNKNOWN". NEVER guess or invent a value under any circumstance. Distinguish "project completion date" from \
"equipment arrival/delivery/unloading/installation date" — do not conflate them. Distinguish MVA (electrical \
rating) from physical weight in tonnes — never assume they are equal; if only MVA is known, weight must be \
UNKNOWN or ESTIMATED (never CONFIRMED).

Output strict JSON with this shape:
{
  "name": str, "client": str, "owner_entity": str, "spv": str, "location": str, "state": str,
  "industry": str, "project_type": str, "status": str, "civil_status": str,
  "equipment": [{"equipment_type": str, "oem": str, "model": str, "capacity": str, "quantity": str,
                 "physical_units": str, "weight_value": str, "weight_confidence": "CONFIRMED|ESTIMATED|UNKNOWN",
                 "dimensions": str}],
  "companies": [{"role": "EPC|OEM|Civil|Transporter|Installation|Heavy-lift", "company_name": str,
                 "confidence": "CONFIRMED|LIKELY|ESTIMATED|UNKNOWN"}],
  "tender": {"tender_number": str, "tender_date": str, "award_date": str, "po_date": str, "issuing_authority": str},
  "timeline": [{"event_type": "tender|award|po|manufacturing|testing|dispatch|arrival|installation|commissioning",
                "event_date": str, "confidence": str, "note": str}],
  "arrival_month": "YYYY-MM or UNKNOWN",
  "contacts": [{"name": str, "designation": str, "company": str, "public_profile_url": str}],
  "field_confidence": {"<field_name>": "CONFIRMED|LIKELY|ESTIMATED|UNKNOWN", ...},
  "overall_confidence": int
}
Return ONLY this JSON object, no prose, no markdown fences."""


def deepen_queries(candidate: dict) -> list[str]:
    name = candidate.get("name", "")
    client = candidate.get("client", "")
    base = f"{name} {client}".strip()
    return [
        f"{base} tender number award",
        f"{base} transformer weight tonnes shipping",
        f"{base} dispatch delivery installation schedule",
        f"{base} EPC contractor",
    ]


def run_research(candidate: dict) -> dict:
    providers = get_fallback_chain()
    llm = get_llm_provider()

    extra_results = []
    for q in deepen_queries(candidate):
        for provider in providers:
            try:
                res = provider.search(q, max_results=6)
                if res:
                    extra_results.extend(res)
                    break
            except Exception as e:
                log_audit("research", "WARNING", f"Provider failed on '{q}': {e}")
                continue

    source_blobs = candidate.get("_sources", []) + [r.to_dict() for r in extra_results]
    joined_sources = "\n\n".join(
        f"TITLE: {s.get('title')}\nURL: {s.get('url')}\nSNIPPET: {s.get('snippet')}\nDATE: {s.get('published_date') or 'UNKNOWN'}"
        for s in source_blobs
    )

    user_prompt = f"CANDIDATE (from Hunter agent):\n{candidate}\n\nADDITIONAL SOURCES:\n{joined_sources}"
    raw = llm.complete(RESEARCH_SYSTEM_PROMPT, user_prompt, json_mode=True)
    verified = safe_json_parse(raw, default=None)

    if not isinstance(verified, dict):
        log_audit("research", "WARNING", f"Could not parse research output for candidate: {candidate.get('name')}")
        return {
            "name": candidate.get("name", "UNKNOWN"),
            "client": candidate.get("client", "UNKNOWN"),
            "overall_confidence": 0,
            "equipment": [], "companies": [], "timeline": [], "contacts": [],
            "field_confidence": {}, "_sources": source_blobs, "_parse_failed": True,
        }

    verified["_sources"] = source_blobs
    return verified
