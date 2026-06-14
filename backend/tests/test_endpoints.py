"""
Integration tests for all API endpoints.
Claude API calls are mocked — no real API key required.
"""

import json
import datetime
import pytest
from unittest.mock import patch

from app import models, crud, schemas
from app.database import get_session


# ── Fixtures / helpers ────────────────────────────────────────────────────────

MOCK_PLAN = {
    "summary": "Focus on core algorithms and system design fundamentals.",
    "tasks": [
        {"title": "DSA Practice - Arrays",  "category": "DSA",    "duration": 60,  "scheduled_time": "Monday, 7 PM - 8 PM"},
        {"title": "System Design Reading",  "category": "System Design", "duration": 45, "scheduled_time": "Tuesday, 7 PM - 7:45 PM"},
        {"title": "LeetCode Easy Set",      "category": "Practice","duration": 30,  "scheduled_time": "Wednesday, 8 PM - 8:30 PM"},
    ],
}

MOCK_INSIGHTS = {
    "pattern_summary": "User performs best in evening slots.",
    "strengths": ["Consistent evening sessions"],
    "weak_spots": ["Morning tasks frequently skipped"],
    "suggestions": ["Move all technical tasks to 7PM-9PM"],
    "reschedule_hints": ["Move Fitness to 8AM-11AM"],
    "memory_summary": {
        "best_time_slot": "5PM-8PM",
        "worst_time_slot": "8AM-11AM",
        "top_excuse": "Too tired",
        "strongest_category": "DSA",
        "weakest_category": "Fitness",
    },
}


def _seed_goal(db, goal_text="Learn DSA in 1 month") -> models.Goal:
    return crud.create_goal(db, schemas.GoalCreate(goal=goal_text))


def _seed_task(db, goal_id: int, status: str = "pending", skip_reason: str | None = None) -> models.Task:
    task = crud.create_task(db, schemas.TaskCreate(
        title="DSA Practice",
        category="DSA",
        duration=60,
        scheduled_time="Monday, 7 PM - 8 PM",
        goal_id=goal_id,
    ))
    if status != "pending":
        crud.update_task_status(db, task.id, status, skip_reason)
        db.refresh(task)
    return task


# ── Goals ─────────────────────────────────────────────────────────────────────

class TestGoals:
    def test_create_goal(self, client):
        resp = client.post("/goals/", json={"goal": "Learn DSA"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["goal"] == "Learn DSA"
        assert "id" in data
        assert "created_at" in data
        assert data["week_start"] is None

    def test_get_goals_empty(self, client):
        assert client.get("/goals/").json() == []

    def test_get_goals_returns_all(self, client):
        client.post("/goals/", json={"goal": "Goal A"})
        client.post("/goals/", json={"goal": "Goal B"})
        resp = client.get("/goals/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ── Tasks ─────────────────────────────────────────────────────────────────────

class TestTasks:
    def test_create_task(self, client, db):
        goal = _seed_goal(db)
        resp = client.post("/tasks/", json={
            "title": "DSA Practice",
            "category": "DSA",
            "duration": 60,
            "scheduled_time": "Monday, 7 PM - 8 PM",
            "goal_id": goal.id,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "DSA Practice"
        assert data["status"] == "pending"
        assert data["scheduled_date"] is None

    def test_get_tasks_empty(self, client):
        assert client.get("/tasks/").json() == []

    def test_update_task_status_done(self, client, db):
        goal = _seed_goal(db)
        task = _seed_task(db, goal.id)

        resp = client.patch(f"/tasks/{task.id}/status", json={"status": "done"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "done"
        assert data["completed_at"] is not None
        assert data["skip_reason"] is None

    def test_update_task_status_skipped_with_reason(self, client, db):
        goal = _seed_goal(db)
        task = _seed_task(db, goal.id)

        resp = client.patch(f"/tasks/{task.id}/status", json={
            "status": "skipped",
            "reason": "Too tired",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "skipped"
        assert data["skip_reason"] == "Too tired"
        assert data["completed_at"] is None

    def test_update_task_status_undo_to_pending(self, client, db):
        goal = _seed_goal(db)
        task = _seed_task(db, goal.id, status="done")

        resp = client.patch(f"/tasks/{task.id}/status", json={"status": "pending"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["completed_at"] is None
        assert data["skip_reason"] is None

    def test_update_task_status_not_found(self, client):
        resp = client.patch("/tasks/9999/status", json={"status": "done"})
        assert resp.status_code == 404

    def test_invalid_status_value_rejected(self, client, db):
        goal = _seed_goal(db)
        task = _seed_task(db, goal.id)
        resp = client.patch(f"/tasks/{task.id}/status", json={"status": "invalid"})
        assert resp.status_code == 422


# ── Plan generation ───────────────────────────────────────────────────────────

class TestPlanGeneration:
    def test_generate_plan_goal_not_found(self, client):
        resp = client.post("/goals/9999/generate-plan")
        assert resp.status_code == 404

    def test_generate_plan_sets_week_start_and_scheduled_date(self, client, db):
        goal = _seed_goal(db)
        with patch("app.agent.generate_plan", return_value=MOCK_PLAN):
            resp = client.post(f"/goals/{goal.id}/generate-plan")

        assert resp.status_code == 200
        data = resp.json()
        assert data["goal_id"] == goal.id
        assert len(data["tasks"]) == 3

        # Every task must have a scheduled_date
        for task in data["tasks"]:
            assert task["scheduled_date"] is not None

        # Goal must have week_start set
        db.refresh(goal)
        assert goal.week_start is not None

    def test_generate_plan_correct_scheduled_dates(self, client, db):
        goal = _seed_goal(db)
        with patch("app.agent.generate_plan", return_value=MOCK_PLAN):
            resp = client.post(f"/goals/{goal.id}/generate-plan")

        tasks = resp.json()["tasks"]
        # MOCK_PLAN has Monday, Tuesday, Wednesday tasks
        dates = {t["scheduled_time"].split(",")[0]: t["scheduled_date"] for t in tasks}

        monday_date  = datetime.date.fromisoformat(dates["Monday"])
        tuesday_date = datetime.date.fromisoformat(dates["Tuesday"])
        wednesday_date = datetime.date.fromisoformat(dates["Wednesday"])

        assert tuesday_date - monday_date == datetime.timedelta(days=1)
        assert wednesday_date - monday_date == datetime.timedelta(days=2)
        assert monday_date.weekday() == 0   # 0 = Monday

    def test_generate_plan_saves_tasks_to_db(self, client, db):
        goal = _seed_goal(db)
        with patch("app.agent.generate_plan", return_value=MOCK_PLAN):
            client.post(f"/goals/{goal.id}/generate-plan")

        db_tasks = db.query(models.Task).filter(models.Task.goal_id == goal.id).all()
        assert len(db_tasks) == 3


# ── Adaptive plan generation ──────────────────────────────────────────────────

class TestAdaptivePlan:
    def test_adaptive_plan_goal_not_found(self, client):
        resp = client.post("/goals/9999/generate-adaptive-plan")
        assert resp.status_code == 404

    def test_adaptive_plan_requires_memory(self, client, db):
        goal = _seed_goal(db)
        resp = client.post(f"/goals/{goal.id}/generate-adaptive-plan")
        assert resp.status_code == 400
        assert "insights" in resp.json()["detail"].lower()

    def test_adaptive_plan_uses_memory_and_hints(self, client, db):
        goal = _seed_goal(db)

        # Seed UserProfile memory directly
        crud.upsert_user_profile(db, {
            "best_time_slot": "5PM-8PM",
            "worst_time_slot": "8PM-11PM",
            "top_excuse": "Too tired",
            "strongest_category": "DSA",
            "weakest_category": "Fitness",
        })

        # Seed an Insight with reschedule_hints
        crud.save_insight(db, "STABLE", 0.7, {
            "total_tasks": 10, "done": 7, "skipped": 3, "pending": 0,
            "completion_rate": 0.7, "mood": "STABLE", "consecutive_misses": 0,
            "completion_by_category": {}, "completion_by_day": {},
            "completion_by_time_slot": {}, "strongest_category": "DSA",
            "weakest_category": "Fitness", "best_time_slot": "5PM-8PM",
            "worst_time_slot": "8PM-11PM", "top_excuses": [],
        }, MOCK_INSIGHTS)

        captured_args = {}

        def mock_adaptive(goal_text, memory, hints):
            captured_args["goal"]   = goal_text
            captured_args["memory"] = memory
            captured_args["hints"]  = hints
            return MOCK_PLAN

        with patch("app.agent.generate_adaptive_plan", side_effect=mock_adaptive):
            resp = client.post(f"/goals/{goal.id}/generate-adaptive-plan")

        assert resp.status_code == 200
        assert captured_args["memory"]["best_time_slot"] == "5PM-8PM"
        assert captured_args["memory"]["top_excuse"] == "Too tired"
        assert "Move Fitness to 8AM-11AM" in captured_args["hints"]

    def test_adaptive_plan_works_without_prior_insight(self, client, db):
        """No Insight row — should still work (empty hints list)."""
        goal = _seed_goal(db)
        crud.upsert_user_profile(db, {
            "best_time_slot": "5PM-8PM",
            "worst_time_slot": "8PM-11PM",
            "top_excuse": "Too tired",
            "strongest_category": "DSA",
            "weakest_category": "Fitness",
        })

        captured_hints = {}

        def mock_adaptive(goal_text, memory, hints):
            captured_hints["hints"] = hints
            return MOCK_PLAN

        with patch("app.agent.generate_adaptive_plan", side_effect=mock_adaptive):
            resp = client.post(f"/goals/{goal.id}/generate-adaptive-plan")

        assert resp.status_code == 200
        assert captured_hints["hints"] == []


# ── Insights ──────────────────────────────────────────────────────────────────

class TestInsights:
    def test_insights_not_enough_data_returns_stats(self, client, db):
        # Only 2 acted tasks — below threshold of 3
        goal = _seed_goal(db)
        _seed_task(db, goal.id, status="done")
        _seed_task(db, goal.id, status="skipped", skip_reason="Too tired")

        resp = client.post("/insights/generate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["insights"] is None
        assert "message" in data
        assert data["stats"]["done"] == 1
        assert data["stats"]["skipped"] == 1

    def test_insights_saves_snapshot_when_insufficient(self, client, db):
        goal = _seed_goal(db)
        _seed_task(db, goal.id, status="done")
        client.post("/insights/generate")

        record = crud.get_latest_insight(db)
        assert record is not None
        assert record.insights_json is None

    def test_insights_calls_claude_when_enough_data(self, client, db):
        goal = _seed_goal(db)
        for status in ("done", "done", "skipped"):
            _seed_task(db, goal.id, status=status, skip_reason="Too tired" if status == "skipped" else None)

        with patch("app.insights.generate_insights", return_value=MOCK_INSIGHTS):
            resp = client.post("/insights/generate")

        assert resp.status_code == 200
        data = resp.json()
        assert data["insights"] is not None
        assert data["insights"]["pattern_summary"] == MOCK_INSIGHTS["pattern_summary"]

    def test_insights_updates_user_profile(self, client, db):
        goal = _seed_goal(db)
        for status in ("done", "done", "skipped"):
            _seed_task(db, goal.id, status=status)

        with patch("app.insights.generate_insights", return_value=MOCK_INSIGHTS):
            client.post("/insights/generate")

        profile = crud.get_user_profile(db)
        assert profile is not None
        assert profile.best_time_slot    == "5PM-8PM"
        assert profile.strongest_category == "DSA"
        assert profile.top_excuse        == "Too tired"

    def test_latest_insight_not_found(self, client):
        resp = client.get("/insights/latest")
        assert resp.status_code == 404

    def test_latest_insight_returns_most_recent(self, client, db):
        goal = _seed_goal(db)
        for status in ("done", "done", "skipped"):
            _seed_task(db, goal.id, status=status)

        with patch("app.insights.generate_insights", return_value=MOCK_INSIGHTS):
            client.post("/insights/generate")
            client.post("/insights/generate")   # second call

        resp = client.get("/insights/latest")
        assert resp.status_code == 200
        # Should return one result (the latest snapshot)
        assert resp.json()["insights"]["pattern_summary"] == MOCK_INSIGHTS["pattern_summary"]

    def test_memory_not_found(self, client):
        resp = client.get("/insights/memory")
        assert resp.status_code == 404

    def test_memory_returns_profile(self, client, db):
        crud.upsert_user_profile(db, {
            "best_time_slot": "5PM-8PM",
            "worst_time_slot": "8PM-11PM",
            "top_excuse": "Too tired",
            "strongest_category": "DSA",
            "weakest_category": "Fitness",
        })
        resp = client.get("/insights/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["best_time_slot"]     == "5PM-8PM"
        assert data["strongest_category"] == "DSA"
        assert data["last_updated"] is not None
