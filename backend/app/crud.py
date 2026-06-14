from sqlalchemy.orm import Session
from . import models, schemas
import datetime
import json


# ── Goals ─────────────────────────────────────────────────────────────────────

def create_goal(db: Session, goal: schemas.GoalCreate) -> models.Goal:
    db_goal = models.Goal(goal=goal.goal)
    db.add(db_goal)
    db.commit()
    db.refresh(db_goal)
    return db_goal


def get_goals(db: Session, skip: int = 0, limit: int = 100) -> list[models.Goal]:
    return db.query(models.Goal).offset(skip).limit(limit).all()


def set_goal_week_start(db: Session, goal: models.Goal, week_start: datetime.date) -> models.Goal:
    goal.week_start = week_start
    db.commit()
    db.refresh(goal)
    return goal


# ── Tasks ─────────────────────────────────────────────────────────────────────

def create_task(db: Session, task: schemas.TaskCreate) -> models.Task:
    db_task = models.Task(
        title=task.title,
        category=task.category,
        duration=task.duration,
        scheduled_time=task.scheduled_time,
        scheduled_date=task.scheduled_date,
        goal_id=task.goal_id,
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task


def get_tasks(db: Session, skip: int = 0, limit: int = 100) -> list[models.Task]:
    return db.query(models.Task).offset(skip).limit(limit).all()


def get_tasks_by_goal(db: Session, goal_id: int) -> list[models.Task]:
    return db.query(models.Task).filter(models.Task.goal_id == goal_id).order_by(models.Task.id).all()


def get_all_tasks(db: Session) -> list[models.Task]:
    """All tasks across all goals — used for user-wide behavioral analysis."""
    return db.query(models.Task).all()


def update_task_status(
    db: Session, task_id: int, status: str, reason: str | None = None
) -> models.Task | None:
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        return None
    task.status = status
    if status == "done":
        task.completed_at = datetime.datetime.utcnow()
        task.skip_reason = None
    elif status == "skipped":
        task.skip_reason = reason
        task.completed_at = None
    else:
        task.completed_at = None
        task.skip_reason = None
    db.commit()
    db.refresh(task)
    return task


# ── Insights ──────────────────────────────────────────────────────────────────

def save_insight(
    db: Session,
    mood: str,
    completion_rate: float,
    stats: dict,
    insight_result: dict | None,
) -> models.Insight:
    record = models.Insight(
        mood=mood,
        completion_rate=completion_rate,
        stats_json=json.dumps(stats),
        insights_json=json.dumps(insight_result) if insight_result else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_latest_insight(db: Session) -> models.Insight | None:
    return db.query(models.Insight).order_by(models.Insight.id.desc()).first()


# ── User profile (persistent agent memory) ────────────────────────────────────

def upsert_user_profile(db: Session, memory: dict) -> models.UserProfile:
    profile = db.query(models.UserProfile).filter(models.UserProfile.id == 1).first()
    if not profile:
        profile = models.UserProfile(id=1)
        db.add(profile)
    profile.best_time_slot     = memory.get("best_time_slot")
    profile.worst_time_slot    = memory.get("worst_time_slot")
    profile.top_excuse         = memory.get("top_excuse")
    profile.strongest_category = memory.get("strongest_category")
    profile.weakest_category   = memory.get("weakest_category")
    profile.memory_json        = json.dumps(memory)
    profile.last_updated       = datetime.datetime.utcnow()
    db.commit()
    db.refresh(profile)
    return profile


def get_user_profile(db: Session) -> models.UserProfile | None:
    return db.query(models.UserProfile).filter(models.UserProfile.id == 1).first()
