# PetalPlan

An AI-native adaptive planner built for the **CCCL × Nova Buildathon — June 14, 2026**.

PetalPlan generates weekly task plans from a goal, tracks what you complete or skip, and learns from your behavior to schedule smarter next time.

---

## How it works

1. **Enter a goal** — "Get a SWE job in 3 months"
2. **Get a weekly plan** — Claude generates 14–21 tasks across the week with concrete time slots
3. **Track tasks** — mark done or missed; leave a reason when you skip
4. **Generate insights** — behavioral stats + Claude analysis of your patterns (best time slots, excuse wall, mood score)
5. **Adaptive plan** — next week's plan is scheduled around what actually works for you

---

## Stack

| Layer | Tech |
|-------|------|
| Frontend | React 19 + Vite, plain CSS |
| Backend | FastAPI, Python 3.11, SQLAlchemy ORM |
| Database | Supabase (PostgreSQL) |
| AI | Claude `claude-opus-4-8`, adaptive thinking, JSON schema output |

---

## Local setup

**Prerequisites:** Python 3.11+, Node 18+

```bash
# 1. Clone
git clone <repo-url> && cd PetalPlan

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Create .env
echo "ANTHROPIC_API_KEY=your_key_here" > .env
# Optional — defaults to SQLite if omitted:
echo "DATABASE_URL=postgresql://..." >> .env

uvicorn app.main:app --host 0.0.0.0 --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

App runs at `http://localhost:5173`.

---

## Docs

- [`docs/architecture.md`](docs/architecture.md) — system design, scaling decisions, security
- [`docs/database.md`](docs/database.md) — schema, migration strategy, design rationale
- [`docs/api.md`](docs/api.md) — all endpoints with request/response schemas and curl examples
