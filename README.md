# Vasu Project Hunter — Vasu Engineering Autonomous Heavy-Equipment Lead Hunter

An autonomous AI agent that searches the live web for Indian industrial/
construction projects, identifies genuine heavy-equipment-handling
opportunities (~80T+ or 5+ medium-heavy packages), scores and prioritizes
them, tracks changes over time, and sends structured alerts to Telegram —
built specifically for Vasu Engineering's business-development team.

## Architecture

```text
vasu-project-hunter/
├── README.md
├── .env.example
├── requirements.txt
├── .gitignore
├── docs/
│   └── MASTER_CONTEXT.md        # condensed reference of the governing brief
├── src/
│   ├── main.py                  # CLI entrypoint + run orchestration
│   ├── config.py                # regions/industries/equipment/OEM/EPC lists, query generator
│   ├── master_context.py        # system instruction sent to Gemini
│   ├── gemini_client.py         # google-genai SDK wrapper + Google Search grounding
│   ├── hunter/
│   │   ├── search.py            # runs this run's query slice, collects candidate URLs
│   │   ├── extraction.py        # builds the extraction prompt, parses structured JSON
│   │   ├── scoring.py           # 100-point scoring + HOT/HIGH/MEDIUM/WATCH tiering
│   │   ├── deduplication.py     # project fingerprint + human-readable project_id
│   │   └── change_detection.py # diffs a known project against a fresh extraction
│   ├── database/
│   │   ├── db.py                # SQLite schema + connection
│   │   └── models.py            # CRUD helpers (projects, alerts, rejected, runs)
│   ├── notifications/
│   │   └── telegram.py          # send + retry + message splitting
│   └── reporting/
│       └── telegram_format.py   # hot-lead / schedule-change / digest message formats
├── data/
│   └── vasu_hunter.db           # created on first run; committed back by CI
└── .github/workflows/
    └── hunter.yml               # hourly 09:00-18:00 IST schedule
```

## How a run works

1. **Discovery** (`hunter/search.py`) — generates a rotating slice of
   search queries (equipment×timing, region×industry, OEM×equipment,
   EPC×signal, PSU×tender-signal) seeded by the current hour, and runs
   them through Gemini's real Google Search grounding.
2. **Extraction** (`hunter/extraction.py`) — for each new candidate URL,
   asks Gemini to extract a structured lead record under the master
   context's no-fake-lead policy and weight-vs-rating rule.
3. **Scoring** (`hunter/scoring.py`) — applies the fixed 100-point rubric
   and classifies the lead HOT / HIGH / MEDIUM / WATCH.
4. **Deduplication & change detection** — a fingerprint (project name +
   client + equipment + location) identifies repeat projects; if a
   previously-stored project's equipment/weight/OEM/EPC/quantity/
   contractor/dates/status changed, that's flagged as a material change
   instead of being silently ignored or re-sent as if new.
5. **Alerts** — up to 4 new-lead Telegram alerts per run (preferring 1-2
   Maharashtra + rest PAN-India, never padded to reach 4), plus separate
   schedule-change alerts for existing projects, plus a full digest on the
   18:00 IST run.
6. **Persistence** — everything is written to `data/vasu_hunter.db`
   (SQLite), which the GitHub Actions workflow commits back to the repo
   after each run so state survives the stateless runner.

## Required GitHub Actions secrets

- `GEMINI_API_KEY` — from https://aistudio.google.com/apikey
- `TELEGRAM_BOT_TOKEN` — from @BotFather
- `TELEGRAM_CHAT_ID` — numeric chat/channel ID to receive alerts

## First run

1. Push this repository to GitHub.
2. Add the three secrets above (Settings → Secrets and variables →
   Actions).
3. Actions → "Vasu Project Hunter" → **Run workflow** → mode
   `test-telegram` first, to confirm the bot can message your chat.
4. Run again with mode `run-once` (or just wait for the hourly schedule)
   and check the Actions log for `RUN SUMMARY`, plus your Telegram chat.
5. Run with mode `health-check` any time to see DB counts and the last
   run's stats without doing a full search cycle.

## Running locally

```bash
cp .env.example .env   # fill in the three values
pip install -r requirements.txt
python -m src.main --test-telegram
python -m src.main --run-once
python -m src.main --health-check
```

## Tuning / cost control

All in `src/config.py`:

- `MAX_QUERIES_PER_RUN` (24) — search calls per run
- `MAX_CANDIDATES_PER_RUN` (40) — Gemini analysis calls per run
- `MAX_TELEGRAM_ALERTS_PER_RUN` (4) — per Section 24's hourly cap
- `MIN_SCORE_TO_STORE` (30) / `MIN_SCORE_TO_ALERT` (55) — quality bars

## Honest limitations (please read before relying on this commercially)

This implements the core engine — discovery, extraction, 100-point
scoring, tiering, deduplication, change detection, SQLite persistence,
hourly Maharashtra/PAN-India-balanced alerts, and an 18:00 IST digest. It
deliberately does **not** implement everything in the full 90-section
brief in this pass:

- **Single search provider.** Only Gemini's Google Search grounding is
  wired up. The brief's multi-provider abstraction-with-fallback
  (`SearchProvider`) isn't built — if Gemini grounding has an outage,
  this run fails loudly rather than falling back to a second provider.
- **No Docker / multi-deployment target.** This is built for GitHub
  Actions only. Docker, Railway/Render/Fly.io options aren't included.
- **No weekly report, OEM/EPC profile tracking, or learning loop.** The
  brief's Sections on weekly pipeline reports, persistent OEM/EPC
  intelligence profiles, and outcome-based scoring adjustment (contacted →
  won/lost feedback loop) aren't built.
- **No personal-contact research.** By design, this agent reports
  company-level entry points only — it does not look up or guess
  individual names, emails, or phone numbers.
- **Simplified "run lock."** GitHub's own `concurrency` group (in
  `hunter.yml`) prevents overlapping runs, which covers the practical
  need, but there's no in-app lock file / resume-safely mechanism beyond
  that.
- **Simplified outbox.** Telegram sends retry within a single run
  (via `tenacity`) and failures are logged to the `alerts` table as
  `FAILED`, but there's no separate background retry queue that revisits
  failed sends on a later run.
- **Date/quarter normalization relies on the model.** Gemini is
  instructed to normalize dates and preserve fiscal-year wording, but
  there's no independent rule-based date parser cross-checking it.
- **Confidence is still a model self-rating.** `confidence_score` and the
  CONFIRMED/LIKELY/ESTIMATED/NOT-PUBLIC tags reflect what Gemini believes
  the source says, not an independently verified fact-check. Treat every
  alert as "worth a human looking into," not as verified truth, before
  using it commercially.

If you want any of these added next (most reasonable next step: a second
search provider for fallback, or the weekly pipeline report), say so and
they can be built incrementally on top of this.

## Security

Never commit `.env` or real secrets. `.gitignore` excludes `.env`,
`__pycache__/`, and virtual environments. `data/vasu_hunter.db` **is**
committed intentionally — it's the persistence layer, not a secret.
