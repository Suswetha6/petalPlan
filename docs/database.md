# Database — PetalPlan

## Engine

SQLite by default. Configured via the `DATABASE_URL` environment variable:

```
DATABASE_URL=sqlite:///./petalplan.db          # default (local file)
DATABASE_URL=postgresql://user:pass@host/db    # production swap
```

The ORM (SQLAlchemy 2.x) abstracts the dialect. The only SQLite-specific code is `connect_args={"check_same_thread": False}`, which is applied conditionally and not needed for PostgreSQL.

---

## Schema

Four tables. The relationships are:

```
goals ──< tasks          (one goal → many tasks, FK nullable)
user_profile             (singleton, id = 1)
insights                 (append-only snapshots, no FK)
```

---

### `goals`

Stores the user's stated goal and the week it was planned for.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | INTEGER PK | No | Auto-increment |
| `goal` | VARCHAR | No | Free-text goal description. Indexed. |
| `created_at` | DATETIME | No | UTC timestamp, set on insert |
| `week_start` | DATE | Yes | Monday of the planned week. Set after plan generation. `NULL` if plan has never been generated. |

**Index:** `goal` column (for text-based lookups; not currently used for search but present for future filtering).

**Design note:** `week_start` is a computed field — set by the server to the Monday of whatever week the user selects. It is not the date the goal was created. A goal can be re-planned for a different week (adaptive plan); in that case `week_start` is overwritten with the new week's Monday.

---

### `tasks`

One row per task inside a generated plan.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | INTEGER PK | No | Auto-increment. Used to determine "recency" in consecutive-miss calculation (higher id = more recent). |
| `title` | VARCHAR | No | Human-readable task name. Indexed. |
| `category` | VARCHAR | Yes | e.g. `DSA`, `Fitness`, `System Design`. Set by Claude. |
| `duration` | INTEGER | Yes | Duration in minutes. |
| `scheduled_time` | VARCHAR | Yes | Human-readable time string: `"Monday, 7 PM - 8 PM"`. Stored as-is from Claude output. |
| `scheduled_date` | DATE | Yes | Computed concrete date: `week_start + day_offset`. `NULL` if day name is unrecognised. |
| `goal_id` | INTEGER FK | Yes | References `goals.id`. `NULL` for tasks created without a goal. |
| `status` | VARCHAR | No | `pending` \| `done` \| `skipped`. Default: `pending`. |
| `completed_at` | DATETIME | Yes | Set when `status = done`, cleared on undo. |
| `skip_reason` | VARCHAR | Yes | Free-text reason entered by the user when marking missed. Cleared on undo. |

**Why `scheduled_time` is a string, not a `TIME` column**

Claude generates time slots as human-readable strings (`"Monday, 7 PM - 8 PM"`). These serve two purposes: display in the week grid (split on `,`) and time-bucket analysis (regex-parsed to an hour). Storing them as-is avoids a lossy round-trip through `datetime.time`, and preserves the day-name component used for day-column assignment. The concrete date lives in `scheduled_date`.

**Why `goal_id` is nullable**

The API allows creating ad-hoc tasks without a goal (`POST /tasks/`). Plan generation always sets `goal_id`.

**Consecutive-miss ordering**

The behavioral insight engine determines "most recent" tasks by sorting on `id DESC`. This is an intentional design: task IDs are assigned sequentially during plan generation, so higher IDs are later in the batch. This is reliable within a single plan; across multiple regenerations, the ordering correctly reflects generation sequence.

---

### `user_profile`

Single-row table. Always `id = 1`. Upserted (not inserted) on every successful insights generation.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | INTEGER PK | No | Always 1 |
| `best_time_slot` | VARCHAR | Yes | e.g. `5PM-8PM` |
| `worst_time_slot` | VARCHAR | Yes | e.g. `8PM-11PM` |
| `top_excuse` | VARCHAR | Yes | Most frequent skip reason |
| `strongest_category` | VARCHAR | Yes | Category with highest completion rate |
| `weakest_category` | VARCHAR | Yes | Category with lowest completion rate |
| `memory_json` | VARCHAR | Yes | JSON-serialised dict of all the above fields. Consumed by the adaptive scheduling agent in a single read. |
| `last_updated` | DATETIME | Yes | UTC timestamp of the last upsert |

**Design note — why a JSON column alongside structured columns**

`memory_json` is a denormalised copy of the five scalar fields stored as a JSON string. The adaptive plan endpoint reads `memory_json` directly and passes it to Claude as a dict, avoiding an ORM-to-dict conversion step. The structured columns (`best_time_slot`, etc.) exist for the `GET /insights/memory` response which returns them as typed fields. Both stay in sync because both are written in the same `upsert_user_profile()` call.

**Design note — singleton row**

The current design is explicitly single-user. Multi-user would change this table to one row per user with a `user_id` primary key replacing the hardcoded `id = 1`. No other code change is needed outside `crud.upsert_user_profile` and `crud.get_user_profile`.

---

### `insights`

Append-only snapshot table. Never updated after insert.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | INTEGER PK | No | Auto-increment |
| `created_at` | DATETIME | No | UTC timestamp of snapshot |
| `mood` | VARCHAR | No | `THRIVING` \| `STABLE` \| `CONCERNED` \| `CHAOS` \| `INTERVENTION` |
| `completion_rate` | FLOAT | No | `done / (done + skipped)`, range `[0.0, 1.0]` |
| `stats_json` | VARCHAR | No | Full `BehavioralStats` dict as JSON |
| `insights_json` | VARCHAR | Yes | Full `InsightResult` dict as JSON. `NULL` when acted task count < 3 (stats-only snapshot). |

**Design note — why append-only**

Insights are expensive to generate (Claude API call) and represent a point-in-time snapshot of the user's behavioral state. Overwriting them would lose the historical record. The `GET /insights/latest` endpoint reads `ORDER BY id DESC LIMIT 1` to return the most recent. Future work could expose an insights history view to let users see their behavioral trend over time.

**Design note — JSON blobs**

`stats_json` and `insights_json` store the full structured output as JSON strings rather than normalising into separate columns. The data is always read and written as a unit, never queried by individual field. JSON columns avoid 5+ extra tables with no query benefit.

---

## Migration Strategy

There is no Alembic or migration framework. Instead, `_migrate()` in `main.py` runs at every startup and applies missing columns idempotently:

```python
def _migrate():
    inspector = inspect(engine)
    task_cols = {col["name"] for col in inspector.get_columns("tasks")}

    with engine.connect() as conn:
        if "status" not in task_cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN status VARCHAR DEFAULT 'pending'"))
        ...
        conn.commit()
```

**Why this pattern instead of Alembic**

For a single-developer, single-database project this is simpler than managing migration files. The idempotency check (`if "status" not in task_cols`) makes it safe to run on every startup. `SQLAlchemy.metadata.create_all()` handles new tables; `_migrate()` handles new columns on existing tables.

**Limitation:** `ALTER TABLE ... ADD COLUMN` cannot change column types or drop columns. If a destructive schema change is ever needed, a proper migration script or Alembic would be required. The current schema has been stable since v1.

**Columns added by migration (not in the original schema):**

| Table | Column | Reason |
|-------|--------|--------|
| `tasks` | `status` | Added when task-tracking feature was built |
| `tasks` | `completed_at` | Added with status tracking |
| `tasks` | `skip_reason` | Added with missed-task reason feature |
| `tasks` | `scheduled_date` | Added for concrete calendar date computation |
| `goals` | `week_start` | Added for week-picker and date-anchored plans |

---

## Indexing

Current indexes (set via `index=True` in SQLAlchemy column definitions):

| Table | Column | Type |
|-------|--------|------|
| `goals` | `id` | PK |
| `goals` | `goal` | B-tree |
| `tasks` | `id` | PK |
| `tasks` | `title` | B-tree |
| `insights` | `id` | PK |
| `user_profile` | `id` | PK |

No index on `tasks.goal_id` — the `GET /tasks/?goal_id=N` query does a full scan. For personal use (hundreds of tasks) this is fast. Add an index at scale:

```sql
CREATE INDEX idx_tasks_goal_id ON tasks(goal_id);
```

No index on `tasks.status` — the insights computation loads all tasks then filters in Python. At scale, push this to SQL with a partial index:

```sql
CREATE INDEX idx_tasks_status ON tasks(status) WHERE status != 'pending';
```

---

## Mood Classification

Computed in `insights.compute_stats()`, not stored on tasks — only on `Insight` snapshots.

| Mood | Rate threshold | Consecutive misses |
|------|---------------|-------------------|
| `THRIVING` | ≥ 80% | — |
| `STABLE` | 60–79% | — |
| `CONCERNED` | 40–59% | — |
| `CHAOS` | 20–39% | — |
| `INTERVENTION` | < 20% **or** | ≥ 5 (streak overrides rate) |

The consecutive-miss streak check fires before the rate threshold. Five consecutive skips means `INTERVENTION` even at a 60% overall rate.

---

## Data Lifecycle

```
User enters goal
  → goals row created (week_start = NULL)

User generates plan
  → goals.week_start set
  → N tasks rows created (status = 'pending')

User marks task done/missed
  → tasks.status updated
  → tasks.completed_at / tasks.skip_reason set

User requests insights
  → insights row appended (stats_json always, insights_json if acted ≥ 3)
  → user_profile row upserted (id = 1)

User requests adaptive plan
  → reads user_profile.memory_json + latest insights.insights_json
  → N new tasks rows created under same goal_id
  → goals.week_start overwritten with new week
```

Old task rows from previous plan generations are not deleted — they accumulate and feed future behavioral analysis. This is intentional: the more history, the richer the insights.
