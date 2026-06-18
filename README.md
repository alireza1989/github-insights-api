# GitHub Insights API

A FastAPI service that ingests GitHub collaboration data, computes reviewer-load and cycle-time metrics, and generates LLM-powered narrative insights with structured, evidence-grounded output.

## Features

- **GitHub ingestion** — pulls PRs, reviews, and commits via GraphQL (paginated, idempotent, re-runnable)
- **Reviewer-load metric** — Gini coefficient, top-N concentration, per-reviewer breakdown
- **Cycle-time metric** — p50/p90 time-to-first-review, time-to-approval, time-to-merge
- **LLM insights** — Claude-powered narrative with evidence chain, computed confidence score, grounding validation, and retry on hallucination
- **Web UI** — single-page dashboard at `/` with charts and insight display
- **OpenAPI docs** — interactive API explorer at `/docs`

## Quickstart

### Option A — Docker Compose (recommended)

```bash
cp .env.example .env
# edit .env and add GITHUB_TOKEN and ANTHROPIC_API_KEY

docker compose up --build
```

The API is available at `http://localhost:8000`.

### Option B — Local with uv

```bash
# requires Python 3.12+ and uv (https://docs.astral.sh/uv)
cp .env.example .env
# edit .env

uv sync
uv run uvicorn app.main:app --reload
```

### Web UI (easiest)

Open `http://localhost:8000`, paste any public GitHub URL (e.g. `https://github.com/pallets/flask`),
pick a date range, and click **Analyze**. The dashboard syncs data, computes metrics, and generates
an AI insight automatically.

### API / curl

The `repo` parameter accepts a full GitHub URL **or** `owner/name` format interchangeably.

```bash
# 1. Sync a repository (fetches PRs, reviews, commits)
curl -X POST http://localhost:8000/sync \
  -H 'Content-Type: application/json' \
  -d '{"repo":"https://github.com/pallets/flask","since":"2024-01-01","until":"2024-06-30"}'

# 2. Reviewer-load metrics
curl 'http://localhost:8000/metrics/review-load?repo=https://github.com/pallets/flask&from=2024-01-01&to=2024-06-30'

# 3. Cycle-time metrics
curl 'http://localhost:8000/metrics/cycle-time?repo=pallets/flask&from=2024-01-01&to=2024-06-30'

# 4. LLM-powered insight
curl 'http://localhost:8000/insights?repo=pallets/flask&from=2024-01-01&to=2024-06-30'
```

Open `http://localhost:8000/docs` for the interactive OpenAPI explorer.

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_TOKEN` | ✅ | — | GitHub PAT with `public_repo` scope |
| `ANTHROPIC_API_KEY` | ✅ | — | Anthropic API key |
| `LLM_MODEL` | | `claude-sonnet-4-6` | Claude model ID |
| `LLM_MAX_TOKENS` | | `8000` | Max output tokens per insight call |
| `LLM_THINKING_BUDGET` | | `4000` | Extended thinking budget tokens |
| `LLM_ENABLE_THINKING` | | `true` | Enable extended thinking |
| `DATABASE_URL` | | `sqlite+aiosqlite:///./insights.db` | Async SQLite URL |
| `RATE_LIMIT_PER_MINUTE` | | `10` | Rate limit on `/insights` per IP |
| `LOG_LEVEL` | | `INFO` | Log level |
| `LOG_JSON` | | `false` | Emit JSON logs (set `true` in production) |

The GitHub PAT only needs **`public_repo` (read-only)** scope. It is never logged.

## API reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Web UI dashboard |
| `GET` | `/health` | Health check |
| `POST` | `/sync` | Ingest a repository for a date range |
| `GET` | `/metrics/review-load` | Reviewer-load distribution + Gini |
| `GET` | `/metrics/cycle-time` | PR cycle-time p50/p90 |
| `GET` | `/insights` | LLM narrative insight |
| `GET` | `/docs` | Interactive OpenAPI docs |

Full parameter docs at `/docs`.

## CLI

```bash
# Sync without starting the server
uv run python -m app.cli sync --repo pallets/flask --since 2024-01-01 --until 2024-06-30
```

## Running tests

```bash
uv run pytest
```

## Running evals

Evals exercise the real LLM against hand-crafted metric fixtures. They require `ANTHROPIC_API_KEY`.

```bash
uv run python -m evals.run
# or via pytest:
uv run pytest evals/
```

## Architecture

```
GitHub API
    │
    ▼
app/ingest/        ← fetch → normalize → upsert (idempotent)
    │
    ▼
SQLite (SQLModel)  ← pull_request, review, commit, sync_run, insight_cache
    │
    ├──▶ app/metrics/    ← pure functions over DB rows (review_load, cycle_time)
    │         │
    │         ▼
    └──▶ app/insights/   ← confidence scoring → LLM call → grounding validation
              │
              ▼
         REST API (FastAPI) + Web UI
```

**Key design decisions:**

- **Structured LLM output via tool use** — the insight schema is registered as a Claude tool and `tool_choice` is forced, so output is always valid JSON matching the Pydantic model. No markdown-fence stripping, no JSON-repair.
- **Computed confidence, not LLM-generated** — a deterministic formula (sample size, effect size, window length) produces the confidence score. The LLM uses it to calibrate language but cannot override it.
- **Grounding validation** — after every LLM call, numeric tokens in the narrative are cross-checked against the metrics payload. If grounding fails, the call is retried once with the failure surfaced in the prompt.
- **Extended thinking + prompt caching** — extended thinking is enabled for analytical depth; the system prompt is prompt-cached to reduce cost on repeated calls.
- **Idempotent ingest** — composite unique constraints + `ON CONFLICT DO UPDATE` make re-running `/sync` for the same window safe.
- **Insights cached 24 h** — responses are keyed by `(repo, from, to, metric, model, prompt_version)` in SQLite.
- **SQLite over Postgres** — zero-ops, ships in Docker, sufficient for this scale. Alembic + Postgres would be the next step.

## Note on AI assistance

This project was built with the assistance of Claude AI (via Claude Code). All security-sensitive code (auth handling, input validation, logging redaction, grounding logic) was reviewed and hardened by hand.
