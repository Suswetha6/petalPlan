# API Reference — PetalPlan

**Base URL (dev):** `http://localhost:8000`  
**Content-Type:** `application/json` for all requests and responses  
**Authentication:** None (single-user design)  
**Interactive docs:** `http://localhost:8000/docs` (Swagger UI)

---

## Goals

### `POST /goals/`

Create a new goal.

**Request body**

```json
{ "goal": "Get a software engineering job in 3 months" }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `goal` | string | Yes | Free-text goal description |

**Response `200`**

```json
{
  "id": 9,
  "goal": "Get a software engineering job in 3 months",
  "created_at": "2026-06-14T10:30:00.000000",
  "week_start": null
}
```

`week_start` is `null` until a plan is generated for this goal.

---

### `GET /goals/`

List all goals, oldest first.

**Query parameters**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `skip` | int | 0 | Offset |
| `limit` | int | 100 | Max results |

**Response `200`** — array of Goal objects (same shape as `POST /goals/` response).

---

## Tasks

### `POST /tasks/`

Create a standalone task (not attached to a plan).

**Request body**

```json
{
  "title": "DSA Practice – Arrays",
  "category": "DSA",
  "duration": 60,
  "scheduled_time": "Monday, 7 PM - 8 PM",
  "scheduled_date": "2026-06-16",
  "goal_id": 9
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Task name |
| `category` | string | No | e.g. DSA, Fitness, Learning |
| `duration` | int | No | Minutes |
| `scheduled_time` | string | No | Human-readable: `"Monday, 7 PM - 8 PM"` |
| `scheduled_date` | date | No | ISO 8601: `"2026-06-16"` |
| `goal_id` | int | No | FK to `goals.id` |

**Response `200`** — Task object (see below).

---

### `GET /tasks/`

List tasks, optionally filtered by goal.

**Query parameters**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `goal_id` | int | — | Filter to tasks belonging to this goal |
| `skip` | int | 0 | Offset (ignored when `goal_id` is set) |
| `limit` | int | 100 | Max results (ignored when `goal_id` is set) |

**Response `200`** — array of Task objects.

**Task object**

```json
{
  "id": 42,
  "title": "DSA Practice – Arrays",
  "category": "DSA",
  "duration": 60,
  "scheduled_time": "Monday, 7 PM - 8 PM",
  "scheduled_date": "2026-06-16",
  "goal_id": 9,
  "status": "pending",
  "completed_at": null,
  "skip_reason": null
}
```

`status` is one of `pending` | `done` | `skipped`.

---

### `PATCH /tasks/{task_id}/status`

Update a task's completion status.

**Path parameter:** `task_id` (integer)

**Request body**

```json
{ "status": "skipped", "reason": "Too tired after work" }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | `"done"` \| `"skipped"` \| `"pending"` | Yes | New status. `pending` = undo. |
| `reason` | string | No | Skip reason. Stored only when `status = skipped`. |

**Side effects by status value**

| Status | `completed_at` | `skip_reason` |
|--------|---------------|---------------|
| `done` | set to UTC now | cleared |
| `skipped` | cleared | set to `reason` |
| `pending` | cleared | cleared |

**Response `200`** — updated Task object.

**Errors**

| Code | Condition |
|------|-----------|
| `404` | `task_id` not found |
| `422` | `status` value not in allowed set |

---

## Plan Generation

### `POST /goals/{goal_id}/generate-plan`

Generate a weekly plan for a goal using Claude. Creates Task rows in the database.

**Path parameter:** `goal_id` (integer)

**Request body** — optional

```json
{ "week_start": "2026-06-16" }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `week_start` | date | No | Any date in the target week. Server normalises to the Monday of that week. Defaults to today's Monday if omitted. |

Omit the body entirely or send `{}` to use the current week.

**What happens**

1. Claude (`claude-opus-4-8`, adaptive thinking) receives the goal text and returns 14–21 tasks as structured JSON.
2. The server computes `week_start` (Monday normalization) and derives a concrete `scheduled_date` for each task from its day name.
3. All tasks are persisted to the DB under this `goal_id`. Existing tasks for the goal are **not** deleted — they accumulate for behavioral analysis.
4. `goals.week_start` is set to the computed Monday.

**Response `200`**

```json
{
  "goal_id": 9,
  "summary": "This week focuses on core DSA patterns in the evening slots where your energy peaks...",
  "tasks": [
    {
      "id": 101,
      "title": "Arrays & Hashing Deep Dive",
      "category": "DSA",
      "duration": 90,
      "scheduled_time": "Monday, 7 PM - 9:30 PM",
      "scheduled_date": "2026-06-16",
      "goal_id": 9,
      "status": "pending",
      "completed_at": null,
      "skip_reason": null
    }
  ]
}
```

**Errors**

| Code | Condition |
|------|-----------|
| `404` | `goal_id` not found |
| `500` | Claude API error, key not set, or schema validation failure |

**Latency:** 20–40 seconds (Claude API call with adaptive thinking).

---

### `POST /goals/{goal_id}/generate-adaptive-plan`

Generate a plan informed by the user's behavioral memory. Requires at least one prior call to `POST /insights/generate`.

**Path parameter:** `goal_id` (integer)

**Request body** — optional, same as `generate-plan`

```json
{ "week_start": "2026-06-23" }
```

**What happens**

1. Loads `UserProfile.memory_json` — fails `400` if no behavioral memory exists.
2. Loads `reschedule_hints` from the most recent `Insight` row that has Claude output.
3. Calls Claude with behavioral memory and directives injected into the system prompt.
4. Same persistence path as regular plan generation.

**Behavioral memory injected into Claude**

```
BEHAVIORAL MEMORY — use this to optimise scheduling:
  Best work time slot  : 5PM-8PM
  Worst work time slot : 8PM-11PM
  Strongest category   : DSA
  Weakest category     : Fitness
  Top excuse for misses: dance practice

RESCHEDULING DIRECTIVES — must follow:
  - Move Fitness tasks to 8AM-11AM
  - Cap Tuesday to 2 tasks max
```

**Response `200`** — same shape as `generate-plan`, with an adaptive `summary` explaining what Claude changed.

**Errors**

| Code | Condition |
|------|-----------|
| `400` | No behavioral memory — run `POST /insights/generate` first |
| `404` | `goal_id` not found |
| `500` | Claude API error |

**Latency:** 20–40 seconds.

---

## Behavioral Insights

### `POST /insights/generate`

Compute behavioral stats across all tasks (all goals) and optionally generate Claude AI insights.

**Request body:** none

**What happens**

1. Loads all tasks from the DB (cross-goal).
2. Computes `BehavioralStats` in pure Python (completion rates, mood, excuse wall, time-slot analysis).
3. If fewer than 3 tasks have been acted on (`done` or `skipped`): saves a stats-only snapshot and returns without calling Claude.
4. Otherwise: calls Claude to generate `InsightResult` (patterns, strengths, suggestions, reschedule hints).
5. Upserts `UserProfile` with the `memory_summary` from Claude.
6. Appends an `Insight` snapshot to the DB.

**Response `200` — sufficient data (≥ 3 acted tasks)**

```json
{
  "mood": "CONCERNED",
  "stats": {
    "total_tasks": 45,
    "done": 12,
    "skipped": 8,
    "pending": 25,
    "completion_rate": 0.6,
    "mood": "CONCERNED",
    "consecutive_misses": 2,
    "completion_by_category": { "DSA": 0.75, "Fitness": 0.33 },
    "completion_by_day": { "Monday": 0.8, "Tuesday": 0.5 },
    "completion_by_time_slot": { "5PM-8PM": 0.9, "8PM-11PM": 0.2 },
    "strongest_category": "DSA",
    "weakest_category": "Fitness",
    "best_time_slot": "5PM-8PM",
    "worst_time_slot": "8PM-11PM",
    "top_excuses": [
      { "reason": "dance practice", "count": 3 },
      { "reason": "too tired", "count": 2 }
    ]
  },
  "insights": {
    "pattern_summary": "You complete DSA tasks at a 75% rate when scheduled in the 5PM-8PM window...",
    "strengths": ["Consistent DSA completion in evening slots", "Strong Monday performance"],
    "weak_spots": ["Fitness tasks fail 67% of the time", "8PM-11PM slot has 20% completion"],
    "suggestions": [
      "Move all Fitness tasks to 8AM-11AM",
      "Avoid scheduling Learning tasks after 8PM"
    ],
    "reschedule_hints": [
      "Move Fitness to 8AM-11AM",
      "Cap 8PM-11PM to one task per day"
    ],
    "memory_summary": {
      "best_time_slot": "5PM-8PM",
      "worst_time_slot": "8PM-11PM",
      "top_excuse": "dance practice",
      "strongest_category": "DSA",
      "weakest_category": "Fitness"
    }
  },
  "message": null
}
```

**Response `200` — insufficient data (< 3 acted tasks)**

```json
{
  "mood": "STABLE",
  "stats": { ... },
  "insights": null,
  "message": "Only 2 acted task(s) — need at least 3 for AI insights. Stats saved."
}
```

**Mood values and thresholds**

| Mood | Condition |
|------|-----------|
| `THRIVING` | completion rate ≥ 80% |
| `STABLE` | 60–79% |
| `CONCERNED` | 40–59% |
| `CHAOS` | 20–39% |
| `INTERVENTION` | < 20% **or** ≥ 5 consecutive recent misses |

**Time slot buckets**

| Bucket | Hours |
|--------|-------|
| `5AM-8AM` | 05:00–07:59 |
| `8AM-11AM` | 08:00–10:59 |
| `11AM-2PM` | 11:00–13:59 |
| `2PM-5PM` | 14:00–16:59 |
| `5PM-8PM` | 17:00–19:59 |
| `8PM-11PM` | 20:00–22:59 |
| `11PM-2AM` | 23:00–25:59 |

**Latency:** < 100 ms (stats only) or 10–20 s (with Claude insights).

---

### `GET /insights/latest`

Return the most recently generated insight snapshot.

**Response `200`** — same shape as `POST /insights/generate`.

**Errors**

| Code | Condition |
|------|-----------|
| `404` | No insights have been generated yet |

---

### `GET /insights/memory`

Return the persistent user behavioral memory. This is the contract endpoint consumed by the Adaptive Scheduling Agent.

**Response `200`**

```json
{
  "best_time_slot": "5PM-8PM",
  "worst_time_slot": "8PM-11PM",
  "top_excuse": "dance practice",
  "strongest_category": "DSA",
  "weakest_category": "Fitness",
  "last_updated": "2026-06-14T10:45:00.000000"
}
```

All fields are `null` until `POST /insights/generate` has been called at least once with sufficient data.

**Errors**

| Code | Condition |
|------|-----------|
| `404` | No memory stored yet |

---

## Error Format

All errors follow FastAPI's default format:

```json
{ "detail": "Human-readable error message" }
```

Common status codes:

| Code | Meaning |
|------|---------|
| `200` | Success |
| `400` | Bad request (e.g. adaptive plan without prior insights) |
| `404` | Resource not found |
| `422` | Request body validation failed (Pydantic) |
| `500` | Server error (Claude API failure, key missing, etc.) |

---

## Curl Examples

**Create a goal**

```bash
curl -s -X POST http://localhost:8000/goals/ \
  -H "Content-Type: application/json" \
  -d '{"goal": "Prepare for system design interviews in 6 weeks"}'
```

**Generate a plan for week of Jun 23**

```bash
curl -s -X POST http://localhost:8000/goals/9/generate-plan \
  -H "Content-Type: application/json" \
  -d '{"week_start": "2026-06-23"}'
```

**Mark task 42 as skipped with reason**

```bash
curl -s -X PATCH http://localhost:8000/tasks/42/status \
  -H "Content-Type: application/json" \
  -d '{"status": "skipped", "reason": "Had an unexpected meeting"}'
```

**Get tasks for goal 9**

```bash
curl -s "http://localhost:8000/tasks/?goal_id=9"
```

**Generate insights**

```bash
curl -s -X POST http://localhost:8000/insights/generate
```

**Generate adaptive plan using behavioral memory**

```bash
curl -s -X POST http://localhost:8000/goals/9/generate-adaptive-plan \
  -H "Content-Type: application/json" \
  -d '{"week_start": "2026-06-30"}'
```

**Read current user memory**

```bash
curl -s http://localhost:8000/insights/memory
```

---

## Typical Integration Flow

```
1. POST /goals/                                  → get goal_id
2. POST /goals/{goal_id}/generate-plan           → week grid with tasks
3. PATCH /tasks/{id}/status  (×N, over the week) → track completion
4. POST /insights/generate                        → mood + behavioral analysis
5. POST /goals/{goal_id}/generate-adaptive-plan  → optimised next week
6. Repeat from step 3
```
