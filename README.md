# GitHub Insights API

> **Development note:** This project was developed using [Claude Code](https://claude.ai/code) under human supervision and planning. All architectural decisions, feature scope, and code reviews were directed by the author; Claude Code was used as the implementation assistant throughout.

A FastAPI service that ingests GitHub collaboration data, computes reviewer-load and cycle-time metrics, and generates LLM-powered narrative insights with structured, evidence-grounded output.

## Features

- **GitHub ingestion** — pulls PRs, reviews, and commits via GraphQL (paginated, idempotent, re-runnable)
- **Historical data caching** — synced date ranges are stored per repo; re-running or extending a window only fetches the missing gap from GitHub
- **Reviewer-load metric** — Gini coefficient, top-N concentration, per-reviewer breakdown with relative load
- **Cycle-time metric** — p50/p90 time-to-first-review, time-to-approval, time-to-merge
- **LLM insights** — Claude-powered narrative with evidence chain, computed confidence score, grounding validation, and automatic retry on hallucination
- **GitHub rate-limit aware** — proactively throttles when the hourly quota runs low; retries on 429/403 and transient 5xx/connection drops
- **Web UI** — single-page dashboard at `/` with charts and insight panel
- **OpenAPI docs** — interactive API explorer at `/docs`

---

## Quickstart

### Prerequisites

| Credential | Where to get it | Scopes needed |
|---|---|---|
| **GitHub PAT** | [github.com/settings/tokens](https://github.com/settings/tokens) → *Generate new token (classic)* | **None** — a token with no scopes is sufficient for public repos |
| **Anthropic API key** | [console.anthropic.com](https://console.anthropic.com) | — |

### Option A — Docker Compose (recommended)

```bash
git clone https://github.com/alireza1989/github-insights-api.git
cd github-insights-api

cp .env.example .env
# Open .env and fill in GITHUB_TOKEN and ANTHROPIC_API_KEY

docker compose up --build
```

The service is available at `http://localhost:8000`. The first build takes ~60 s; subsequent starts are instant.

### Option B — Local with uv

```bash
# requires Python 3.12+ and uv (https://docs.astral.sh/uv)
cp .env.example .env   # then edit

uv sync
uv run uvicorn app.main:app --reload
```

---

## Testing the service

### 1 — Web UI (recommended for a first look)

1. Open `http://localhost:8000`
2. Paste any public GitHub URL, e.g. `https://github.com/tiangolo/fastapi`
3. Set a date range — start with **3 months** to keep the sync fast
4. Click **Analyze**

The pipeline runs three steps automatically: *Sync → Compute metrics → Generate insight*. The first sync for a repo takes a few seconds (or longer for very large repos like kubernetes/kubernetes). Re-running the same range is instant — only new date gaps hit GitHub.

> **Suggested repos for testing** (small to medium, active review culture):
> - `tiangolo/fastapi` — fast sync, rich review data
> - `pallets/flask` — classic project, clean history
> - `psf/requests` — small and well-reviewed

### 2 — API / curl

The `repo` parameter accepts a full GitHub URL **or** `owner/name` interchangeably.

```bash
# Step 1 — Sync (returns 202 immediately; poll step 2 for status)
curl -s -X POST http://localhost:8000/sync \
  -H 'Content-Type: application/json' \
  -d '{"repo":"tiangolo/fastapi","since":"2025-01-01","until":"2025-03-31"}' | jq

# Step 2 — Poll sync status (replace 1 with the id returned above)
curl -s http://localhost:8000/sync/1 | jq

# Step 3 — Reviewer-load metrics
curl -s 'http://localhost:8000/metrics/review-load?repo=tiangolo/fastapi&from=2025-01-01&to=2025-03-31' | jq

# Step 4 — Cycle-time metrics
curl -s 'http://localhost:8000/metrics/cycle-time?repo=tiangolo/fastapi&from=2025-01-01&to=2025-03-31' | jq

# Step 5 — LLM narrative insight (may take ~20 s on first call; cached for 24 h after)
curl -s 'http://localhost:8000/insights?repo=tiangolo/fastapi&from=2025-01-01&to=2025-03-31' | jq
```

### 3 — Interactive API explorer

Open `http://localhost:8000/docs` — every endpoint is documented with live try-it-out.

### Running tests

```bash
uv run pytest          # 50 unit + integration tests, no API keys needed
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_TOKEN` | ✅ | — | GitHub PAT — no extra scopes needed for public repos |
| `ANTHROPIC_API_KEY` | ✅ | — | Anthropic API key |
| `LLM_MODEL` | | `claude-sonnet-4-6` | Claude model ID |
| `LLM_MAX_TOKENS` | | `8000` | Max output tokens per insight call |
| `LLM_ENABLE_THINKING` | | `true` | Enable adaptive extended thinking |
| `DATABASE_URL` | | `sqlite+aiosqlite:///./insights.db` | Async SQLite URL |
| `RATE_LIMIT_PER_MINUTE` | | `10` | Per-IP rate limit on `/insights` |
| `LOG_LEVEL` | | `INFO` | Log level |
| `LOG_JSON` | | `false` | Emit JSON logs (`true` in production / Docker) |

GitHub's GraphQL API requires authentication even for public repositories. A token with **no scopes** is sufficient — it is never logged.

---

## API reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Web UI dashboard |
| `GET` | `/health` | Health check |
| `POST` | `/sync` | Ingest a repository for a date range (async, returns 202) |
| `GET` | `/sync/{id}` | Poll ingest job status |
| `GET` | `/metrics/review-load` | Reviewer-load distribution + Gini coefficient |
| `GET` | `/metrics/cycle-time` | PR cycle-time p50/p90 |
| `GET` | `/insights` | LLM narrative insight |
| `GET` | `/docs` | Interactive OpenAPI explorer |

Full parameter docs at `/docs`.

---

## Architecture

```
GitHub GraphQL API
        │
        ▼
app/ingest/          ← fetch gaps only (SyncedRange coverage table)
        │              paginated, idempotent ON CONFLICT DO UPDATE
        ▼
SQLite (SQLModel)    ← pull_request, review, commit, sync_run,
        │              synced_range, insight_cache
        ├──▶ app/metrics/    ← pure functions: review_load, cycle_time
        │         │            pre-computes avg_reviews, relative_load
        │         ▼
        └──▶ app/insights/   ← confidence scoring (deterministic)
                  │              → LLM call (Claude, adaptive thinking)
                  │              → grounding validation + retry
                  ▼
         REST API (FastAPI) + Web UI (Tailwind + Chart.js)
```

**Key design decisions:**

- **Historical data caching** — a `synced_range` table records every successfully fetched `(repo, from_date, to_date)` window. On subsequent syncs only the uncovered gaps are fetched from GitHub, making re-runs and range extensions cheap.
- **Structured LLM output via tool use** — the insight schema is registered as a Claude tool; when thinking is disabled `tool_choice` is `"any"` (guaranteed call), when thinking is enabled it switches to `"auto"` (required by the API — forced tool use and thinking are mutually exclusive).
- **Adaptive extended thinking** — uses `{"type": "adaptive"}` (Claude 4.x format) for analytical depth; the legacy `{"type": "enabled", "budget_tokens": N}` format only works on Claude 3.7 Sonnet.
- **Computed confidence, not LLM-generated** — a deterministic formula (sample size 35 %, effect size 30 %, window length 20 %, data freshness 15 %) produces the confidence score. The LLM uses it to calibrate language but cannot override it.
- **Grounding validation** — after every LLM call, numeric tokens in the narrative are cross-checked against the full metrics payload (review-load + cycle-time). Numbers not found in the data trigger a retry with the failures surfaced in the prompt.
- **GitHub rate-limit respect** — proactively sleeps when `rateLimit.remaining < 500`; respects `Retry-After` on 429 (primary) and 403 (secondary) responses; retries up to 2× on connection drops and transient 5xx.
- **Prompt caching** — the static system prompt block carries `cache_control: ephemeral`; repeated calls for the same repo read from Anthropic's prompt cache, reducing cost significantly.
- **Insights cached 24 h** — responses are keyed by `(repo, from, to, metric, model, prompt_version)` in SQLite; bumping the prompt version auto-invalidates stale cached insights.
- **SQLite over Postgres** — zero-ops, ships in Docker, sufficient for this scale. Alembic + Postgres is the natural next step.

## Note on AI assistance

This project was built with the assistance of Claude AI (via Claude Code). All security-sensitive code (auth handling, input validation, logging redaction, grounding logic) was reviewed and hardened by hand.
