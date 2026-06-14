from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Literal, Dict
import datetime


# ── Task ──────────────────────────────────────────────────────────────────────

class TaskBase(BaseModel):
    title: str
    category: Optional[str] = None
    duration: Optional[int] = None
    scheduled_time: Optional[str] = None
    scheduled_date: Optional[datetime.date] = None


class TaskCreate(TaskBase):
    title: str = Field(min_length=1, max_length=500)
    category: Optional[str] = Field(default=None, max_length=100)
    duration: Optional[int] = Field(default=None, ge=1, le=1440)
    scheduled_time: Optional[str] = Field(default=None, max_length=200)
    goal_id: Optional[int] = None


class Task(TaskBase):
    id: int
    goal_id: Optional[int]
    status: str = "pending"
    completed_at: Optional[datetime.datetime] = None
    skip_reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TaskStatusUpdate(BaseModel):
    status: Literal["done", "skipped", "pending"]
    reason: Optional[str] = Field(default=None, max_length=500)


# ── Goal ──────────────────────────────────────────────────────────────────────

class GoalBase(BaseModel):
    goal: str


class GoalCreate(GoalBase):
    goal: str = Field(min_length=1, max_length=1000)


class Goal(GoalBase):
    id: int
    created_at: datetime.datetime
    week_start: Optional[datetime.date] = None

    model_config = ConfigDict(from_attributes=True)


class GeneratedPlan(BaseModel):
    goal_id: int
    summary: str
    tasks: List[Task]


class GeneratePlanRequest(BaseModel):
    week_start: Optional[datetime.date] = None


# ── Behavioral Insights ───────────────────────────────────────────────────────

class ExcuseEntry(BaseModel):
    reason: str
    count: int


class BehavioralStats(BaseModel):
    total_tasks: int
    done: int
    skipped: int
    pending: int
    completion_rate: float
    mood: Literal["THRIVING", "STABLE", "CONCERNED", "CHAOS", "INTERVENTION"]
    consecutive_misses: int
    completion_by_category: Dict[str, float]
    completion_by_day: Dict[str, float]
    completion_by_time_slot: Dict[str, float]
    strongest_category: Optional[str]
    weakest_category: Optional[str]
    best_time_slot: Optional[str]
    worst_time_slot: Optional[str]
    top_excuses: List[ExcuseEntry]


class MemorySummary(BaseModel):
    best_time_slot: Optional[str]
    worst_time_slot: Optional[str]
    top_excuse: Optional[str]
    strongest_category: Optional[str]
    weakest_category: Optional[str]


class InsightResult(BaseModel):
    pattern_summary: str
    strengths: List[str]
    weak_spots: List[str]
    suggestions: List[str]
    reschedule_hints: List[str]
    memory_summary: MemorySummary


class InsightResponse(BaseModel):
    mood: str
    stats: BehavioralStats
    insights: Optional[InsightResult] = None
    message: Optional[str] = None


# ── User memory (agent contract) ──────────────────────────────────────────────

class UserMemory(BaseModel):
    best_time_slot: Optional[str]
    worst_time_slot: Optional[str]
    top_excuse: Optional[str]
    strongest_category: Optional[str]
    weakest_category: Optional[str]
    last_updated: Optional[datetime.datetime]

    model_config = ConfigDict(from_attributes=True)
