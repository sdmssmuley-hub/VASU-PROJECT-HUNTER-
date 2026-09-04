"""
Agent 1 — PROJECT HUNTER
Generates search queries dynamically, runs them through the configured
search provider (with fallback chain), and extracts CANDIDATE projects
using the LLM. Does NOT approve/reject — that is the QC agent's job.

FIX: previously, if the LLM returned unparseable JSON or an empty list,
this loop just did `continue` with zero logging, so a "0 candidates" run
looked identical whether the LLM found nothing OR the LLM's response never
parsed at all. Now every query logs its own outcome, so audit_logs will
show exactly which queries had results but produced no usable candidates,
and why.
"""
from __future__ import annotations
import itertools
from app.config import settings
from app.search_provider import get_fallback_chain
from app.llm_provider import get_llm_provider, safe_json_parse
from app.database import log_audit, db_session, now_iso

EQUIPMENT_TERMS = [
    "500 MVA transformer", "750 MVA transformer", "1000 MVA transformer",
    "765kV transformer", "400kV transformer", "shunt reactor", "HVDC transformer",
    "forging press", "hydraulic press", "rolling mill equipment", "stamping press",
]

PROJECT_STAGE_TERMS = [
    "tender", "LOA awarded", "PO issued", "dispatch", "delivery",
    "erection", "installation", "commissioning schedule",
]

INDUSTRY_TERMS = [
    "substation", "power plant", "steel plant", "cement plant", "refinery",
    "battery gigafactory", "data centre", "petrochemical plant", "fertilizer plant",
]

REGIONS = settings.PRIMARY_REGIONS + settings.SECONDARY_REGIONS + settings.TERTIARY_REGIONS

ORG_TERMS = ["POWERGRID", "MSETCL", "NTPC", "NHPC", "CEA", "state transmission utility"]

YEARS = ["2026", "2027"]


def generate_queries(category: str | None = None, limit: int = 25) -> list[str]:
    """
    Dynamic query generation — combinations of equipment/industry/stage/region/year.
    `category` narrows generation to match the hourly rotation (see scheduler.py).
    """
    queries: list[str] = []

    if category in (None, "powergrid_msetcl"):
        for org in ORG_TERMS:
            for term in EQUIPMENT_TERMS[:4]:
                queries.append(f"{org} {term} India {YEARS[0]}")

    if category in (None, "transformer_tenders"):
        for term in EQUIPMENT_TERMS:
            for stage in PROJECT_STAGE_TERMS[:3]:
                queries.append(f'"{term}" {stage} India {YEARS[0]}')

    if category in (None, "maharashtra_industrial"):
        for term in INDUSTRY_TERMS:
            queries.append(f"{term} Maharashtra project {YEARS[0]}")

    if category in (None, "gujarat_industrial"):
        for term in INDUSTRY_TERMS:
            queries.append(f"{term} Gujarat project {YEARS[0]}")

    if category in (None, "steel_forging_presses"):
        for term in ["forging press", "hydraulic press", "rolling mill expansion", "steel plant expansion"]:
            queries.append(f"{term} India {YEARS[0]}")

    if category in (None, "power_transmission"):
        for term in ["substation tender", "grid expansion", "transformer augmentation"]:
            for region in REGIONS[:5]:
                queries.append(f"{term} {region} {YEARS[0]}")

    if category in (None, "oem_announcements"):
        for term in ["transformer factory dispatch", "OEM delivery schedule", "equipment manufacturing complete"]:
            queries.append(f"{term} India {YEARS[0]}")

    if category in (None, "epc_announcements"):
        for term in ["EPC contract awarded", "project execution update", "construction milestone"]:
            queries.append(f"{term} India heavy equipment {YEARS[0]}")

    if category in (None, "tender_awards"):
        for term in ["tender awarded", "LOA issued", "PO issued"]:
            for eq in EQUIPMENT_TERMS[:4]:
                queries.append(f"{eq} {term} India")

    if category in (None, "deep_verification"):
        queries.append("heavy equipment erection support India tender 2026 2027")
        queries.append("transformer unloading jacking skidding contract India")

    # de-dup, cap
    seen, out = set(), []
    for q in queries:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out[:limit]


EXTRACTION_SYSTEM_PROMPT = """You are the PROJECT HUNTER agent for Vasu Engineering, a heavy machinery \
shifting/rigging/erection-support contractor in India. Given raw web search results, extract CANDIDATE \
projects that might need heavy equipment handling (40T-1000T+ transformers, reactors, presses, industrial \
machinery). For each candidate, output strict JSON: a list of objects with fields: name, client, location, \
state, industry, equipment_type, status, tender_number, notes. If a field is not in the source text, use \
"UNKNOWN" — never invent it. Only extract if there is a real signal of heavy equipment movement, tender, \
award, or installation. Return ONLY a JSON array, no prose, no markdown fences. If there is genuinely no \
qualifying project in the results, return an empty array: []"""


def run_hunter(category: str | None, run_id: int, max_queries: int = 15) -> list[dict]:
    """
    Executes the search + extraction pass for one scheduler run.
    Returns list of raw candidate dicts (not yet verified).
    """
    queries = generate_queries(category, limit=max_queries)
    providers = get_fallback_chain()
    llm = get_llm_provider()
    candidates: list[dict] = []

    # Per-run counters so the final summary log tells you WHERE candidates were lost,
    # not just that the total was zero.
    stats = {
        "queries_with_results": 0,
        "llm_calls_empty_response": 0,
        "llm_calls_unparseable": 0,
        "llm_calls_parsed_but_no_valid_items": 0,
        "llm_calls_ok": 0,
    }

    with db_session() as conn:
        for q in queries:
            results = []
            for provider in providers:
                try:
                    results = provider.search(q, max_results=8)
                    if results:
                        break
                except Exception as e:
                    log_audit("hunter", "WARNING", f"Provider {provider.__class__.__name__} failed on '{q}': {e}")
                    continue

            conn.execute(
                "INSERT INTO search_queries (run_id, query, category, executed_at, result_count) VALUES (?,?,?,?,?)",
                (run_id, q, category or "general", now_iso(), len(results)),
            )

            if not results:
                continue

            stats["queries_with_results"] += 1

            joined = "\n\n".join(
                f"TITLE: {r.title}\nURL: {r.url}\nSNIPPET: {r.snippet}\nDATE: {r.published_date or 'UNKNOWN'}"
                for r in results
            )
            raw = llm.complete(EXTRACTION_SYSTEM_PROMPT, joined, json_mode=True)

            if not raw:
                stats["llm_calls_empty_response"] += 1
                log_audit("hunter", "WARNING", f"Empty LLM response for query '{q}' ({len(results)} search results were available).")
                continue

            parsed = safe_json_parse(raw, default=None)
            if parsed is None:
                stats["llm_calls_unparseable"] += 1
                log_audit("hunter", "WARNING", f"LLM response for '{q}' was not valid/recoverable JSON.")
                continue

            if not isinstance(parsed, list):
                stats["llm_calls_unparseable"] += 1
                log_audit("hunter", "WARNING", f"LLM response for '{q}' parsed but was not a JSON list (got {type(parsed).__name__}).")
                continue

            valid_items = 0
            for item in parsed:
                if not isinstance(item, dict) or not item.get("name") or item.get("name") == "UNKNOWN":
                    continue
                item["_sources"] = [r.to_dict() for r in results]
                item["_query"] = q
                candidates.append(item)
                valid_items += 1

            if valid_items == 0:
                stats["llm_calls_parsed_but_no_valid_items"] += 1
                log_audit("hunter", "INFO", f"LLM for '{q}' returned valid JSON but no qualifying candidates (this can be legitimate).")
            else:
                stats["llm_calls_ok"] += 1

    log_audit(
        "hunter", "INFO",
        f"Run {run_id} ({category}): {len(candidates)} raw candidates from {len(queries)} queries. "
        f"Breakdown: {stats}",
    )
    return candidates
