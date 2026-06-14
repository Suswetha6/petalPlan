from dotenv import load_dotenv
load_dotenv()  # must run before any module reads DATABASE_URL or ANTHROPIC_API_KEY

from fastapi import FastAPI, HTTPException, Depends, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
from app import models, schemas, crud, agent, insights
from app.database import engine, get_session
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text
import datetime
import json
import logging
import os

logger = logging.getLogger(__name__)


# ── DB bootstrap ──────────────────────────────────────────────────────────────

models.Base.metadata.create_all(bind=engine)


def _migrate():
    """Add columns introduced after initial schema, for existing databases."""
    inspector = inspect(engine)

    task_cols = {col["name"] for col in inspector.get_columns("tasks")}
    goal_cols = {col["name"] for col in inspector.get_columns("goals")}

    with engine.connect() as conn:
        # tasks — tracking columns
        if "status" not in task_cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN status VARCHAR DEFAULT 'pending'"))
        if "completed_at" not in task_cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN completed_at DATETIME"))
        if "skip_reason" not in task_cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN skip_reason VARCHAR"))
        # tasks — date column
        if "scheduled_date" not in task_cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN scheduled_date DATE"))
        # goals — week_start
        if "week_start" not in goal_cols:
            conn.execute(text("ALTER TABLE goals ADD COLUMN week_start DATE"))
        conn.commit()


_migrate()

# ── Date helpers ──────────────────────────────────────────────────────────────

_DAY_OFFSETS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _week_start_for(dt: datetime.date | None = None) -> datetime.date:
    """Return the Monday of the week containing dt (defaults to today)."""
    dt = dt or datetime.date.today()
    return dt - datetime.timedelta(days=dt.weekday())


def _scheduled_date(week_start: datetime.date, scheduled_time: str) -> datetime.date | None:
    """'Monday, 7 PM - 8 PM' + week_start → concrete calendar date."""
    day_name = scheduled_time.split(",")[0].strip().lower()
    offset = _DAY_OFFSETS.get(day_name)
    return week_start + datetime.timedelta(days=offset) if offset is not None else None


def _save_plan_tasks(db: Session, goal_id: int, tasks: list[dict], week_start: datetime.date):
    """Create Task rows, attach dates, return ORM objects."""
    created = []
    for t in tasks:
        created.append(crud.create_task(
            db,
            schemas.TaskCreate(
                title=t["title"],
                category=t["category"],
                duration=t["duration"],
                scheduled_time=t["scheduled_time"],
                scheduled_date=_scheduled_date(week_start, t["scheduled_time"]),
                goal_id=goal_id,
            ),
        ))
    return created


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="PetalPlan API")

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)

FRONTEND_DIST = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
)
if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    def root_index():
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


# ── Goals ─────────────────────────────────────────────────────────────────────

@app.post("/goals/", response_model=schemas.Goal)
def create_goal(goal: schemas.GoalCreate, db: Session = Depends(get_session)):
    return crud.create_goal(db, goal)


@app.get("/goals/", response_model=list[schemas.Goal])
def read_goals(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_session),
):
    return crud.get_goals(db, skip=skip, limit=limit)


# ── Tasks ─────────────────────────────────────────────────────────────────────

@app.post("/tasks/", response_model=schemas.Task)
def create_task(task: schemas.TaskCreate, db: Session = Depends(get_session)):
    return crud.create_task(db, task)


@app.get("/tasks/", response_model=list[schemas.Task])
def read_tasks(
    goal_id: Optional[int] = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_session),
):
    if goal_id is not None:
        return crud.get_tasks_by_goal(db, goal_id)
    return crud.get_tasks(db, skip=skip, limit=limit)


@app.patch("/tasks/{task_id}/status", response_model=schemas.Task)
def update_task_status(
    task_id: int, update: schemas.TaskStatusUpdate, db: Session = Depends(get_session)
):
    task = crud.update_task_status(db, task_id, update.status, update.reason)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ── Plan generation ───────────────────────────────────────────────────────────

@app.post("/goals/{goal_id}/generate-plan", response_model=schemas.GeneratedPlan)
def generate_plan(
    goal_id: int,
    body: Optional[schemas.GeneratePlanRequest] = Body(default=None),
    db: Session = Depends(get_session),
):
    goal = db.query(models.Goal).filter(models.Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    try:
        plan = agent.generate_plan(goal.goal)
    except ValueError as e:
        logger.error("Plan generation config error: %s", e)
        raise HTTPException(status_code=500, detail="Plan generation failed: server configuration error.")
    except Exception as e:
        logger.error("Plan generation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Plan generation failed. Please try again.")

    week_start = _week_start_for(body.week_start if body else None)
    crud.set_goal_week_start(db, goal, week_start)
    tasks = _save_plan_tasks(db, goal_id, plan["tasks"], week_start)

    return schemas.GeneratedPlan(goal_id=goal_id, summary=plan["summary"], tasks=tasks)


@app.post("/goals/{goal_id}/generate-adaptive-plan", response_model=schemas.GeneratedPlan)
def generate_adaptive_plan(
    goal_id: int,
    body: Optional[schemas.GeneratePlanRequest] = Body(default=None),
    db: Session = Depends(get_session),
):
    """
    Generates a plan using UserProfile memory + latest reschedule_hints.
    Requires at least one prior call to POST /insights/generate.
    """
    goal = db.query(models.Goal).filter(models.Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    profile = crud.get_user_profile(db)
    if not profile or not profile.memory_json:
        raise HTTPException(
            status_code=400,
            detail="No behavioral memory found. Run POST /insights/generate first.",
        )

    memory = json.loads(profile.memory_json)

    # Pull reschedule_hints from latest insight that has Claude output
    reschedule_hints: list[str] = []
    latest = crud.get_latest_insight(db)
    if latest and latest.insights_json:
        reschedule_hints = json.loads(latest.insights_json).get("reschedule_hints", [])

    try:
        plan = agent.generate_adaptive_plan(goal.goal, memory, reschedule_hints)
    except ValueError as e:
        logger.error("Adaptive plan config error: %s", e)
        raise HTTPException(status_code=500, detail="Adaptive plan generation failed: server configuration error.")
    except Exception as e:
        logger.error("Adaptive plan generation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Adaptive plan generation failed. Please try again.")

    week_start = _week_start_for(body.week_start if body else None)
    crud.set_goal_week_start(db, goal, week_start)
    tasks = _save_plan_tasks(db, goal_id, plan["tasks"], week_start)

    return schemas.GeneratedPlan(goal_id=goal_id, summary=plan["summary"], tasks=tasks)


# ── Behavioral Insights ───────────────────────────────────────────────────────

@app.post("/insights/generate", response_model=schemas.InsightResponse)
def generate_insights_endpoint(db: Session = Depends(get_session)):
    all_tasks = crud.get_all_tasks(db)
    stats = insights.compute_stats(all_tasks)

    acted_count = stats["done"] + stats["skipped"]
    if acted_count < 3:
        crud.save_insight(db, stats["mood"], stats["completion_rate"], stats, None)
        return schemas.InsightResponse(
            mood=stats["mood"],
            stats=schemas.BehavioralStats(**stats),
            message=f"Only {acted_count} acted task(s) — need at least 3 for AI insights. Stats saved.",
        )

    try:
        insight_result = insights.generate_insights(stats)
    except ValueError as e:
        logger.error("Insight generation config error: %s", e)
        raise HTTPException(status_code=500, detail="Insight generation failed: server configuration error.")
    except Exception as e:
        logger.error("Insight generation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Insight generation failed. Please try again.")

    crud.upsert_user_profile(db, insight_result["memory_summary"])
    crud.save_insight(db, stats["mood"], stats["completion_rate"], stats, insight_result)

    return schemas.InsightResponse(
        mood=stats["mood"],
        stats=schemas.BehavioralStats(**stats),
        insights=schemas.InsightResult(**insight_result),
    )


@app.get("/insights/latest", response_model=schemas.InsightResponse)
def get_latest_insight(db: Session = Depends(get_session)):
    record = crud.get_latest_insight(db)
    if not record:
        raise HTTPException(status_code=404, detail="No insights generated yet")
    stats = schemas.BehavioralStats(**json.loads(record.stats_json))
    insight_result = (
        schemas.InsightResult(**json.loads(record.insights_json))
        if record.insights_json else None
    )
    return schemas.InsightResponse(mood=record.mood, stats=stats, insights=insight_result)


@app.get("/insights/memory", response_model=schemas.UserMemory)
def get_user_memory(db: Session = Depends(get_session)):
    """Agent memory contract — consumed by the Adaptive Scheduling Agent."""
    profile = crud.get_user_profile(db)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail="No memory stored yet. Run POST /insights/generate first.",
        )
    return profile
