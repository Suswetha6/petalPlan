# Architecture — PetalPlan

## Overview

PetalPlan is a single-user adaptive planning application. A React SPA sends goals and tracks task completion against a FastAPI backend. The backend calls the Anthropic Claude API to generate plans and behavioral insights, persisting everything in SQLite. There is no authentication layer — the system is designed for personal, local use.

```
Browser (React + Vite)
        │
        │ HTTP / JSON  (Vite proxy in dev, direct in prod)
        ▼
FastAPI  (Python 3.11)
  ├── CRUD layer  (SQLAlchemy ORM)  ──▶  SQLite  (petalplan.db)
  ├── Agent layer (agent.py)        ──▶  Anthropic Claude API
  └── Insights layer (insights.py)  ──▶  Anthropic Claude API
```

---

## Component Breakdown

### Frontend (`frontend/`)

| File | Responsibility |
|------|---------------|
| `App.jsx` | Single-file app: all views (Home, Plan, Insights), all state |
| `App.css` | Scoped styles; parchment design system with CSS variables |
| `vite.config.js` | Dev proxy routing `/goals`, `/tasks`, `/insights` → `localhost:8000` |

The frontend is a deliberately flat SPA with no router. View transitions are controlled by a `view` state variable (`'plan'` | `'insights'`). This is intentional : a router would be justified once the app acquires auth and per-user pages.

### Backend (`backend/app/`)

| Module | Responsibility |
|--------|---------------|
| `main.py` | FastAPI route handlers, startup migration, date helpers |
| `models.py` | SQLAlchemy ORM models (4 tables) |
| `schemas.py` | Pydantic V2 request/response models — the API contract |
| `crud.py` | All DB reads and writes; no business logic |
| `agent.py` | Claude API calls for plan generation (base + adaptive) |
| `insights.py` | Layer A: pure-Python stats; Layer B: Claude insights call |
| `database.py` | Engine creation, session factory, `get_session` dependency |

---

## Request Flows

### Plan Generation

```
POST /goals/{id}/generate-plan  { week_start?: date }
  1. Validate goal exists in DB
  2. agent.generate_plan(goal_text)
       → Claude API (claude-opus-4-8, adaptive thinking, json_schema output)
       ← { tasks: [...], summary: "..." }
  3. Compute week_start (from body or today's Monday)
  4. Map each task's "Monday, 7 PM – 8 PM" → concrete calendar date
  5. Persist Goal.week_start + N Task rows
  6. Return GeneratedPlan
```

### Behavioral Insights

```
POST /insights/generate
  1. Load ALL tasks from DB (cross-goal)
  2. insights.compute_stats(tasks)          ← pure Python, no I/O
       → completion rates, mood, excuses, time-slot analysis
  3. If acted_count < 3 → save stats-only snapshot, return early
  4. insights.generate_insights(stats)
       → Claude API (claude-opus-4-8, adaptive thinking, json_schema output)
       ← { pattern_summary, strengths, weak_spots, suggestions,
            reschedule_hints, memory_summary }
  5. crud.upsert_user_profile(memory_summary)   ← single-row upsert
  6. crud.save_insight(...)                     ← append-only snapshot
  7. Return InsightResponse
```

### Adaptive Plan Generation

```
POST /goals/{id}/generate-adaptive-plan  { week_start?: date }
  1. Validate goal exists
  2. Load UserProfile.memory_json → fails 400 if no prior insights
  3. Load latest Insight.insights_json → extract reschedule_hints
  4. agent.generate_adaptive_plan(goal, memory, hints)
       → Claude API with behavioral memory injected into system prompt
  5. Same persistence path as regular plan generation
```

---

## AI Design Decisions

### Adaptive Thinking (`thinking: { type: "adaptive" }`)

Both `agent.py` and `insights.py` use adaptive thinking. This lets Claude allocate reasoning tokens proportionally to task complexity — a simple goal like "30-min morning run" uses fewer thinking tokens than "system design of a distributed database." Adaptive mode is preferred over a fixed `budget_tokens` because plan complexity is highly variable.

### Structured Output via JSON Schema

All Claude calls use `output_config: { format: { type: "json_schema", schema: ... } }`. This guarantees the response can be safely `json.loads()`-ed into a typed Pydantic model. It eliminates the need for regex-based extraction, retry loops, or defensive parsing, and makes the AI output as reliable as a typed function return.

### Two-Layer Insights Architecture

`compute_stats()` is pure Python with no I/O — it runs in microseconds and is fully covered by unit tests (34 tests). Claude only receives the already-computed aggregate numbers. This means:
- Claude never sees raw task titles (reduces prompt injection surface)
- Claude's behavioral claims are bounded by real numbers it received, not invented
- The stats layer is independently testable without API keys or mocking

### User-Centric Memory (not Goal-Centric)

`UserProfile` is a single row with id=1. Insights are computed across **all goals**, not per-goal. This is intentional: behavioral patterns (e.g. "always skips tasks after 9 PM") are properties of the person, not of a specific goal. The adaptive scheduler reads this cross-goal memory when generating the next plan.

---

## Scaling Decisions

### SQLite → PostgreSQL

The database URL comes from an environment variable:

```python
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./petalplan.db")
```

The `check_same_thread: False` option is applied only when using SQLite:

```python
connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
```

Swapping to PostgreSQL requires one line: set `DATABASE_URL=postgresql://...`. No ORM changes needed — SQLAlchemy abstracts the dialect. The `_migrate()` raw-DDL function (`ALTER TABLE ... ADD COLUMN`) uses portable SQL that works on both engines.

**When to migrate:** At the point of adding authentication and multi-user support. PostgreSQL is also required if deploying to a managed platform (Railway, Supabase) where file-based SQLite is impractical.

### Synchronous Claude Calls

`generate_plan` and `generate_insights` block the FastAPI request thread for 20–40 seconds. FastAPI's default `uvicorn` worker handles this as a blocking call — it does not parallelize well across concurrent users.

**Current behaviour:** Acceptable for single-user personal use. The Vite dev proxy and production static serving pattern both assume a single concurrent user.

**At scale:** Move Claude calls to a task queue (Celery + Redis, or FastAPI BackgroundTasks for light load). Return a `job_id` immediately, poll or use WebSockets for progress. The React loading state already expects a long wait; wiring it to a poll endpoint requires minimal UI change.

### In-Memory Stats Computation

`compute_stats()` loads all tasks into Python memory with `crud.get_all_tasks()`. For one user with ~1,000 tasks this is fast (< 1 ms). It becomes a concern at ~100k rows.

**At scale:** Push aggregations to SQL (`GROUP BY category`, `COUNT(*) FILTER (WHERE status = 'done')`). The two-layer separation (`compute_stats` vs `generate_insights`) means this refactor is localised to `insights.py` and `crud.py` with no interface changes.

### Static File Serving

In production, FastAPI serves the React build from `frontend/dist` via `StaticFiles`. This is simple but puts static file I/O on the same process as the API.

**At scale:** Serve `frontend/dist` from a CDN (Cloudflare, Vercel, S3+CloudFront). The backend becomes API-only (`/goals`, `/tasks`, `/insights`). The only change needed is configuring CORS (see Security below).

### Multi-User

The schema is single-user: `UserProfile.id` is hardcoded to 1, and there is no `user_id` column on any table.

**Migration path to multi-user:**
1. Add `users` table with auth fields
2. Add `user_id FK` to `goals`, `insights`, `user_profile`
3. Scope all CRUD queries by `user_id`
4. Add JWT middleware (FastAPI dependency on all routes)
5. `UserProfile` becomes one row per user (drop `default=1`)

---

## Security

### API Key Handling

`ANTHROPIC_API_KEY` is loaded from `.env` via `python-dotenv`. The key is never committed — `.env` is in `.gitignore`. The client factory raises `ValueError` before any DB or network access if the key is absent:

```python
def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
    return anthropic.Anthropic(api_key=api_key)
```

**Hardening for production:** Rotate to a secret manager (AWS Secrets Manager, Vault) rather than a `.env` file. The env-var interface is unchanged.

### SQL Injection

All database access goes through SQLAlchemy ORM with parameterised queries — there is no f-string or `%`-interpolated raw SQL in any query path. The `_migrate()` startup function uses raw `text()` DDL statements, but these contain no user input (only hardcoded column names), so there is no injection surface there.

### Prompt Injection

User goal text is passed to Claude as part of the user message. A crafted goal like `"Ignore previous instructions and..."` could attempt to override the system prompt.

**Current mitigations:**
- Structured output (`json_schema`) means Claude must emit valid JSON matching the schema regardless of what the prompt says — a jailbreak attempt that produces text outside the schema will cause `json.loads()` to raise and the endpoint will return a 500.
- Adaptive thinking mode makes Claude significantly more resistant to instruction override.
- The insights pipeline never sends raw task titles to Claude — only pre-aggregated statistics — eliminating the most common injection surface (user-controlled strings in the prompt).

**Current mitigations (additional):** Goal text is capped at 1000 chars and skip reasons at 500 chars at the Pydantic validation layer — oversized injection payloads are rejected with `422` before reaching the model.

### CORS

No CORS middleware is configured. In development, the Vite proxy handles cross-origin requests transparently. In production (separate frontend/backend domains), add:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-frontend.com"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)
```

Using `allow_origins=["*"]` should be avoided — it would allow any site to call your API and trigger Claude usage at your cost.

### Input Validation

All request bodies are validated by Pydantic V2. Invalid payloads receive a `422 Unprocessable Entity` before any business logic runs. Constraints applied at the schema layer:

| Field | Constraint | Reason |
|-------|-----------|--------|
| `goal` | max 1000 chars | Caps Claude prompt size and token spend |
| `task.title` | max 500 chars | Prevents oversized payloads |
| `task.category` | max 100 chars | Reasonable label bound |
| `task.duration` | 1–1440 min | Sanity check (max 24 hours) |
| `skip_reason` | max 500 chars | Injected into Claude prompt; bounded to limit injection surface |
| `limit` query param | max 500 | Prevents full-table dumps via unbounded pagination |

Task status values are constrained to a `Literal["done", "skipped", "pending"]` enum — arbitrary status strings are rejected at the schema layer.

### Error Exposure

All 500 responses return generic client-facing messages. Full stack traces are logged server-side via Python's `logging` module:

```python
logger.error("Plan generation failed: %s", e, exc_info=True)
raise HTTPException(status_code=500, detail="Plan generation failed. Please try again.")
```

Applies to plan generation, adaptive plan generation, and insight generation endpoints.

### Rate Limiting

There is no rate limiting on Claude-backed endpoints. A single user can trigger unlimited plan generations, each consuming ~$0.05–0.20 of API credits.

**For production:** Add rate limiting middleware (e.g. `slowapi`) on `POST /goals/{id}/generate-plan`, `POST /goals/{id}/generate-adaptive-plan`, and `POST /insights/generate`. A budget of 10 Claude calls per hour per user is a reasonable starting point.

### Transport Security

The dev server runs plain HTTP. Production deployments must terminate TLS at the reverse proxy or platform layer (Nginx, Caddy, Render, Railway all handle this automatically). FastAPI itself does not need changes.

---

## Deployment

### Development

```
backend:   uvicorn app.main:app --reload   (port 8000)
frontend:  vite dev                        (port 5173, proxies /goals, /tasks, /insights → 8000)
```

### Production (Single Container)

FastAPI serves the built React app from `frontend/dist`:

```
docker-compose up
  → nginx or uvicorn on port 80/443
  → /assets/*    served as static files from frontend/dist/assets
  → /            serves frontend/dist/index.html
  → /goals, /tasks, /insights  handled by FastAPI routes
```

### Production (Split Deployment)

```
Frontend:  Vercel / Netlify / S3+CloudFront  (static)
Backend:   Render / Railway / Fly.io         (uvicorn, with CORS configured)
Database:  Supabase / Neon / RDS             (PostgreSQL, DATABASE_URL env var)
```
