# VASU AI Project Hunter — GitHub Actions Setup

## What was fixed / added in this version

The original app was built as an always-on FastAPI server (`app/main.py`) with
an internal scheduler (`app/scheduler.py`, APScheduler). That model needs a
process kept alive 24/7 — GitHub Actions runners don't do that; they start,
run one job, and stop. That mismatch is why `python -m app.free_runner` (in
an earlier version of this repo) failed with `ModuleNotFoundError`.

This version adds a small script entrypoint, `app/run_once.py`, that:
1. Initializes the database
2. Runs exactly one hunt cycle for the current hour (or a given `--hour`)
3. Sends results to Telegram
4. Exits

GitHub Actions' own cron schedule (`.github/workflows/hourly-hunt.yml`)
decides *when* this runs — hourly, 9 AM to 6 PM IST. The old
`app/main.py` (dashboard) and `app/scheduler.py` are untouched and still work
if you ever want to run this as a persistent server elsewhere (Render,
Railway, a VPS, etc.) — GitHub Actions just doesn't use them.

Also added:
- **OpenRouter** as an LLM provider (`app/llm_provider.py`) — uses your
  `OPENROUTER_API_KEY` secret, OpenAI-compatible API.
- **DuckDuckGo search** (`app/search_provider.py`) — free, no API key needed,
  so real (non-demo) results reach Telegram without a paid search key.
- **Database persistence across runs** via `actions/cache`, so duplicate
  detection actually works run-to-run (otherwise every run would start with
  an empty database and could re-notify the same project).

## 1. Upload to GitHub — folder structure matters

Upload the **entire contents of this folder** (not just the `.py` files) so
that `app/` stays a subfolder, not flattened into the repo root:

```
your-repo/
├── .github/workflows/hourly-hunt.yml
├── app/
│   ├── __init__.py
│   ├── agents/
│   ├── run_once.py
│   ├── main.py
│   ├── config.py
│   ├── ...
├── tests/
├── requirements.txt
└── .env.example
```

If you drag-and-drop files into GitHub's web uploader one by one, it's easy
to lose the `app/` folder structure — use "Add folder" or a git push instead.

## 2. Add GitHub Secrets

Repo → Settings → Secrets and variables → Actions → **New repository secret**:

| Secret name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | from @BotFather |
| `TELEGRAM_CHAT_ID` | your chat id |
| `OPENROUTER_API_KEY` | from openrouter.ai |

Optional — Settings → Secrets and variables → Actions → **Variables** tab:

| Variable name | Value |
|---|---|
| `LLM_MODEL` | any OpenRouter model id, e.g. `meta-llama/llama-3.1-8b-instruct:free` (default already set if you skip this) |

## 3. Test it

Actions → **VASU AI Hourly Project Hunt** → **Run workflow** → hour = `9` → Run.

**What success looks like in the logs (step "Run hunt cycle"):**
```
Cycle complete: {'run_id': 1, 'candidates': N, 'duplicates': 0, 'rejected': X, 'verified': Y, 'high_priority': Z}
```
and you should get one or more Telegram messages (a run report, plus a
project card for each approved lead).

**If `candidates` is 0 every time:** DuckDuckGo may be rate-limiting the
runner's IP, or the free LLM model may be returning empty/unparseable JSON.
Switch `SEARCH_PROVIDER` to `tavily` (free tier, needs a key from tavily.com)
in the workflow env, and/or try a different `LLM_MODEL`, if this happens
often.

## 4. Known limitations (not bugs)

- GitHub's `schedule` cron can be delayed by several minutes during high
  platform load, or skipped if the repo has been inactive for 60+ days —
  this is a GitHub-wide limitation, not specific to this workflow.
- Free LLM models on OpenRouter vary in extraction quality. If leads look
  low-quality, try a different (still free) model via the `LLM_MODEL`
  variable.
- Free DuckDuckGo search can be blocked/rate-limited under heavy automated
  use. The system degrades gracefully (returns 0 candidates that run) rather
  than crashing — but if it happens often, switch to a paid-free-tier
  provider (Tavily/SerpApi/Brave) as noted above.
