# VASU ENGINEERING — PROJECT HUNTER MASTER CONTEXT (reference)

This is a condensed reference copy of the brief this system is built
against. The version actually sent to Gemini on every analysis call is
`src/master_context.py` (kept short deliberately, since it's included in
every per-candidate prompt). Structured data (regions, industries,
equipment, OEM/EPC/PSU lists, search-signal phrases) lives in
`src/config.py`. If you have the original full 90-section brief, keep a
copy of it alongside this file for future prompt-tuning reference.

## Mission
Find real Indian projects where heavy equipment (~80T+ single package, or
5+ packages of 40-80T+) will need transport/unloading/rigging/jacking/
skidding/shifting/positioning/erection/dismantling/relocation support, and
surface them BEFORE or near the time the equipment reaches site.

## No-fake-lead policy
Never invent equipment, weight, OEM, EPC, contractor, transporter, or
dates. Mark unknowns as "Not publicly disclosed — requires direct
verification." Never upgrade an inference to a confirmed fact.

## Weight vs. rating
Press tonnage, transformer MVA, turbine MW, and crane lifting capacity are
NOT physical weight. Always extract/report actual shipping/transport
weight separately, or mark it not disclosed.

## Scoring (100 points) — implemented in src/hunter/scoring.py
- Weight: 80-150T=10, 150-300T=14, 300-500T=17, 500T+=20 (20 pts)
- Quantity: 1=3, 2-4=7, 5-9=12, 10+=15 (15 pts)
- Arrival urgency: 0-2mo=20, 2-4mo=15, 4-6mo=10, 6-12mo=5 (20 pts)
- Civil readiness: active foundation=10, construction active=8,
  pre-construction=4 (10 pts)
- OEM known: confirmed=10, likely=5, unknown=0 (10 pts)
- EPC known: confirmed=10, likely=5, unknown=0 (10 pts)
- Vasu scope fit: direct heavy handling=10, general=6, weak=2 (10 pts)
- Geography: Maharashtra=5, Gujarat=4, other industrial state=3,
  other=1 (5 pts)

## Priority tiers — implemented in src/hunter/scoring.py
- 🔴 HOT: 85-100 — immediate commercial action
- 🟠 HIGH: 70-84 — strong lead
- 🟡 MEDIUM: 55-69 — track / early approach
- 🔵 WATCH: below 55 — stored, not sent to Telegram

## Hourly Telegram rule — implemented in src/main.py
Up to 4 new-project alerts per run, preferring 1-2 Maharashtra + 2-3
PAN-India, never padded with fabricated leads. If nothing qualifies, send
"No new verified Vasu opportunities discovered in this cycle." Separately,
already-known projects with a material change (new weight/OEM/EPC/
quantity/contractor/date/status) get a "SCHEDULE / DETAIL CHANGE" alert
regardless of the 4-lead cap.

## Daily digest — implemented in src/reporting/telegram_format.py
Sent on the 18:00 IST run: HOT/HIGH/MEDIUM lists for the day plus a system
health summary (queries run, URLs scanned, candidates analyzed, qualified
leads, alerts sent, errors).

## What is deliberately NOT built in this version
See the "Honest limitations" section of README.md.
