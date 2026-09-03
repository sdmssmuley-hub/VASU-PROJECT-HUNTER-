# VASU AI Project Hunter

An automated research system for **Vasu Engineering** (heavy machinery
shifting, rigging, transformer handling, erection support — Maharashtra, PAN
India) that hunts for real, verifiable heavy-equipment-handling opportunities,
scores and quality-checks them, and alerts the owner on Telegram.

**Pipeline:** Search → Research & Verify → Score → QC → Database → Telegram,
on an hourly rotation (default 09:00–18:00), with a daily summary report.

**Hard rule baked into the code:** the system never fabricates data. Every
field that can't be verified from a real source is marked `UNKNOWN` — never
guessed. Demo/placeholder search results are explicitly tagged `[DEMO DATA]`
and are blocked from ever reaching Telegram by the QC agent (see
`app/agents/qc.py`).

---

## ⚠️ Important: what this is and isn't

This is a **real, runnable codebase** — FastAPI backend, SQLite database,
three AI agents, scoring/dedup engines, Telegram bot, scheduler, dashboard,
and tests. It is **not** currently running anywhere; you need to deploy it
(a laptop left on, a small VPS, or a free-tier cloud box) so the 09:00–18:00
schedule keeps firing. It also ships with `SEARCH_PROVIDER=demo` and
`LLM_PROVIDER=ollama` by default — you must configure a real search provider
and a real (or local Ollama) LLM before it will find real projects. See
**Setup** below.

---

## Folder structure

```
vasu-ai-hunter/
├── app/
│   ├── main.py              # FastAPI app: dashboard API + Telegram webhook
│   ├── config.py            # all settings, loaded from .env
│   ├── database.py          # SQLite schema + connection helpers
│   ├── search_provider.py   # SearchProvider abstraction (demo/tavily/serpapi/brave)
│   ├── llm_provider.py      # LLMProvider abstraction (ollama/openai-compatible)
│   ├── dedup.py             # fingerprint-based duplicate detection
│   ├── scoring.py           # 100-point opportunity scoring engine
│   ├── telegram_bot.py      # message formatting + send queue
│   ├── orchestrator.py      # wires the 3 agents together per run
│   ├── scheduler.py         # APScheduler cron jobs (09:00-18:00 + daily report)
│   ├── agents/
│   │   ├── hunter.py        # Agent 1: query generation + candidate extraction
│   │   ├── research.py      # Agent 2: deep verification, CONFIRMED/ESTIMATED/UNKNOWN
│   │   └── qc.py            # Agent 3: final APPROVED/HOLD/REJECTED gate + persistence
│   └── static/index.html    # dashboard UI (single file, no build step)
├── tests/                   # pytest suite (dedup, scoring, QC, telegram, db)
├── data/                    # SQLite database file lives here (gitignored)
├── requirements.txt
├── .env.example
├── pytest.ini
└── README.md (this file)
```

---

## Setup

### 1. Python environment

```bash
cd vasu-ai-hunter
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env`:

- **Telegram** (required for alerts):
  1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → copy the token into `TELEGRAM_BOT_TOKEN`.
  2. Message your new bot once, then visit
     `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat.id` →
     put it in `TELEGRAM_CHAT_ID`.
  3. To receive `/status /today /top` command replies, set a webhook once the
     app is deployed with a public HTTPS URL:
     ```bash
     curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://yourdomain.com/telegram/webhook"
     ```
     (No public URL yet? Skip this — outbound alerts still work without it.)

- **Search provider** (required for real results — default is a labelled demo
  provider that returns no real data):
  Pick one of `tavily` / `serpapi` / `brave`, get a free/low-cost API key from
  that provider's site, set `SEARCH_PROVIDER` and `SEARCH_API_KEY`. All three
  have free trial tiers. Swapping providers later is a one-line `.env` change
  — the code never needs to change (`app/search_provider.py`).

- **LLM provider** (used to extract/verify project data from search results):
  - Free/local: install [Ollama](https://ollama.com), run `ollama pull llama3.1`,
    leave `LLM_PROVIDER=ollama` (default).
  - Or set `LLM_PROVIDER=openai_compatible` with `LLM_API_KEY` for OpenAI or
    any OpenAI-compatible gateway.

- **Dashboard login**: set `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` — the
  dashboard uses HTTP Basic Auth.

### 3. Run tests

```bash
pytest -v
```

### 4. Run in development

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` (enter your dashboard username/password).

The scheduler starts automatically with the app — it will fire hunt cycles at
each hour listed in `RUN_HOURS` (default `9,10,11,...,18`, timezone
`Asia/Kolkata`), and a daily report 30 minutes after the last run.

You can also trigger a run immediately from the dashboard's **"Run now"**
button, or via:
```bash
curl -u owner:change-me -X POST "http://localhost:8000/api/run-now"
```

### 5. Run in production

Keep the process alive with a process manager, e.g. `systemd`:

```ini
# /etc/systemd/system/vasu-ai-hunter.service
[Unit]
Description=Vasu AI Project Hunter
After=network.target

[Service]
WorkingDirectory=/path/to/vasu-ai-hunter
ExecStart=/path/to/vasu-ai-hunter/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
EnvironmentFile=/path/to/vasu-ai-hunter/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now vasu-ai-hunter
```

Or with `pm2`: `pm2 start "venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000" --name vasu-ai-hunter`.

Put it behind a reverse proxy (Caddy/Nginx) with HTTPS if you want the
Telegram webhook (`/telegram/webhook`) to work, since Telegram requires HTTPS.

---

## How the pipeline works

1. **Hunter agent** (`app/agents/hunter.py`) generates dynamic search queries
   (equipment × stage × region × year combinations, see `ROTATION` in
   `orchestrator.py` for the hourly category), runs them through the
   configured search provider (with automatic fallback if one fails), and
   asks the LLM to extract candidate projects as structured JSON.
2. **Research agent** (`app/agents/research.py`) runs additional targeted
   searches per candidate and asks the LLM to verify every field, tagging
   each with `CONFIRMED` / `LIKELY` / `ESTIMATED` / `UNKNOWN`. It explicitly
   never lets MVA rating stand in for physical weight, and never confuses a
   project completion date with an equipment arrival date.
3. **QC agent** (`app/agents/qc.py`) makes the final call: `APPROVED` / `HOLD`
   / `REJECTED`, with a logged reason. It rejects stale/cancelled/commissioned
   projects, unsupported claims, and demo data; holds moderate-confidence
   leads for manual review; and only lets high-confidence, source-backed,
   de-duplicated leads through to Telegram.
4. **Scoring** (`app/scoring.py`) computes a 0–100 opportunity score across
   11 weighted factors (timing, weight, OEM/EPC confirmation, geography,
   etc.), fully itemized on the project detail page.
5. **Dedup** (`app/dedup.py`) fingerprints projects by tender number (or
   normalized name+client+location) so the same project reported by 10
   sources becomes one row with merged sources.
6. Approved leads are queued and sent to Telegram
   (`app/telegram_bot.py`), formatted per the spec's message template, with
   `UNKNOWN` shown explicitly for any missing field.

The owner never has the AI auto-send quotes, accept contracts, or commit
price/manpower — the system only researches, verifies, scores, and
recommends (`lead_status` starts at `NEW`; moving it to `CONTACTED` /
`QUOTATION` / etc. is a manual dashboard/DB action, intentionally not
automated).

---

## Telegram commands

`/start` `/status` `/today` `/top` `/search <term>` `/project <id>` `/help`

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Dashboard shows 0 projects after a run | `SEARCH_PROVIDER=demo` (default) — configure a real provider |
| Runs complete but Telegram gets nothing | `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` unset, or all leads were HOLD/REJECTED (check `/api/logs`) |
| `/status` etc. don't reply | Webhook not set, or app isn't reachable over HTTPS — outbound alerts still work regardless |
| LLM output not parsing | Check `/api/logs` for `research`/`hunter` errors; some local models need a stronger JSON-mode model |
| Scheduler didn't fire | Confirm the process has been running continuously — `systemctl status vasu-ai-hunter` |

All errors are recorded in the `audit_logs` table and visible at
`GET /api/logs` — nothing fails silently.

---

## Extending

- **New search provider**: subclass `SearchProvider` in `search_provider.py`,
  register it in `_PROVIDERS`.
- **New LLM provider**: subclass `LLMProvider` in `llm_provider.py`.
- **Adjust scoring weights**: edit `FACTORS`/logic in `scoring.py` — every
  factor's points/reason are stored per-project for auditability.
- **Change the rotation**: edit `ROTATION` in `orchestrator.py` and
  `RUN_HOURS` in `.env`.
