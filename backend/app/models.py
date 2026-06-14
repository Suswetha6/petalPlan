from sqlalchemy import Column, Integer, String, DateTime, Date, Float, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base
import datetime


class Goal(Base):
    __tablename__ = "goals"
    id = Column(Integer, primary_key=True, index=True)
    goal = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    week_start = Column(Date, nullable=True)   # Monday of the week this plan covers
    tasks = relationship("Task", back_populates="goal")


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    category = Column(String, nullable=True)
    duration = Column(Integer, nullable=True)
    scheduled_time = Column(String, nullable=True)   # "Monday, 7 PM - 8 PM"
    scheduled_date = Column(Date, nullable=True)     # computed from week_start + day offset
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=True)
    goal = relationship("Goal", back_populates="tasks")
    # tracking fields
    status = Column(String, default="pending")       # pending | done | skipped
    completed_at = Column(DateTime, nullable=True)
    skip_reason = Column(String, nullable=True)


class UserProfile(Base):
    """Single-row user memory — upserted on every insights generation."""
    __tablename__ = "user_profile"
    id = Column(Integer, primary_key=True, default=1)
    best_time_slot = Column(String, nullable=True)
    worst_time_slot = Column(String, nullable=True)
    top_excuse = Column(String, nullable=True)
    strongest_category = Column(String, nullable=True)
    weakest_category = Column(String, nullable=True)
    memory_json = Column(String, nullable=True)
    last_updated = Column(DateTime, nullable=True)


class Insight(Base):
    """Append-only snapshot produced each time insights are generated."""
    __tablename__ = "insights"
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    mood = Column(String)
    completion_rate = Column(Float)
    stats_json = Column(String)
    insights_json = Column(String, nullable=True)
