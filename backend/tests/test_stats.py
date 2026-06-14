"""
Unit tests for insights.compute_stats — pure Python, no DB, no Claude.
Uses SimpleNamespace to mimic SQLAlchemy Task objects.
"""

import pytest
from types import SimpleNamespace
from app.insights import compute_stats, _parse_hour, _to_bucket


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_task(
    task_id: int = 1,
    status: str = "pending",
    category: str = "DSA",
    scheduled_time: str = "Monday, 7 PM - 8 PM",
    skip_reason: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=task_id,
        status=status,
        category=category,
        scheduled_time=scheduled_time,
        skip_reason=skip_reason,
    )


def tasks(*specs) -> list:
    """Shorthand: tasks(('done','DSA'), ('skipped','Fitness','Too tired'))"""
    result = []
    for i, spec in enumerate(specs, start=1):
        status = spec[0]
        category = spec[1] if len(spec) > 1 else "DSA"
        reason = spec[2] if len(spec) > 2 else None
        sched = spec[3] if len(spec) > 3 else "Monday, 7 PM - 8 PM"
        result.append(make_task(i, status, category, sched, reason))
    return result


# ── Completion rate ───────────────────────────────────────────────────────────

def test_completion_rate_all_done():
    t = tasks(("done",), ("done",), ("done",))
    s = compute_stats(t)
    assert s["completion_rate"] == 1.0
    assert s["done"] == 3
    assert s["skipped"] == 0


def test_completion_rate_all_skipped():
    t = tasks(("skipped",), ("skipped",))
    s = compute_stats(t)
    assert s["completion_rate"] == 0.0


def test_completion_rate_mixed():
    # 3 done, 2 skipped → 3/5 = 0.6
    t = tasks(("done",), ("done",), ("done",), ("skipped",), ("skipped",))
    s = compute_stats(t)
    assert s["completion_rate"] == pytest.approx(0.6, abs=0.001)


def test_pending_excluded_from_rate():
    # pending tasks must not affect the rate
    t = tasks(("done",), ("pending",), ("pending",), ("pending",))
    s = compute_stats(t)
    assert s["completion_rate"] == 1.0
    assert s["pending"] == 3


def test_no_acted_tasks():
    t = tasks(("pending",), ("pending",))
    s = compute_stats(t)
    assert s["completion_rate"] == 0.0
    assert s["done"] == 0
    assert s["skipped"] == 0


# ── Mood mapping ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("done,skipped,expected_mood", [
    (9, 1,  "THRIVING"),    # 90%
    (7, 3,  "STABLE"),      # 70%
    (5, 5,  "CONCERNED"),   # 50%
    (3, 7,  "CHAOS"),       # 30%
    (1, 9,  "INTERVENTION"),# 10%
])
def test_mood_from_rate(done, skipped, expected_mood):
    # Skipped tasks get lower IDs (older), done tasks get higher IDs (recent).
    # This keeps consecutive_misses = 0 so we're testing rate→mood in isolation.
    t = (
        [make_task(i, "skipped") for i in range(1, skipped + 1)] +
        [make_task(i + skipped, "done") for i in range(1, done + 1)]
    )
    s = compute_stats(t)
    assert s["mood"] == expected_mood


def test_mood_intervention_overrides_rate_via_streak():
    # 60% rate would normally be STABLE, but 5 consecutive misses → INTERVENTION
    base = [make_task(i, "done") for i in range(1, 7)]   # 6 done (old)
    streak = [make_task(i + 6, "skipped") for i in range(1, 6)]  # 5 skipped (recent, higher id)
    s = compute_stats(base + streak)
    assert s["mood"] == "INTERVENTION"
    assert s["consecutive_misses"] == 5


def test_mood_four_consecutive_misses_not_intervention():
    # 4 consecutive misses — does NOT trigger INTERVENTION on its own
    base = [make_task(i, "done") for i in range(1, 9)]     # 8 done
    streak = [make_task(i + 8, "skipped") for i in range(1, 5)]  # 4 skipped
    s = compute_stats(base + streak)
    assert s["consecutive_misses"] == 4
    assert s["mood"] != "INTERVENTION"


# ── Consecutive misses ────────────────────────────────────────────────────────

def test_consecutive_misses_counted_from_most_recent():
    # ids determine "recent" — higher id = more recent
    t = [
        make_task(1, "done"),
        make_task(2, "done"),
        make_task(3, "skipped"),
        make_task(4, "skipped"),
        make_task(5, "skipped"),
    ]
    s = compute_stats(t)
    assert s["consecutive_misses"] == 3


def test_consecutive_misses_broken_by_done():
    t = [
        make_task(1, "skipped"),
        make_task(2, "skipped"),
        make_task(3, "done"),    # breaks the streak
        make_task(4, "skipped"),
    ]
    s = compute_stats(t)
    assert s["consecutive_misses"] == 1  # only task 4 is the tail streak


def test_consecutive_misses_zero_when_last_is_done():
    t = [make_task(1, "skipped"), make_task(2, "done")]
    s = compute_stats(t)
    assert s["consecutive_misses"] == 0


# ── Top excuses ───────────────────────────────────────────────────────────────

def test_top_excuses_sorted_by_count():
    t = tasks(
        ("skipped", "DSA", "Too tired"),
        ("skipped", "DSA", "Too tired"),
        ("skipped", "DSA", "Too tired"),
        ("skipped", "DSA", "Had class"),
        ("skipped", "DSA", "Had class"),
        ("skipped", "DSA", "Forgot"),
    )
    s = compute_stats(t)
    excuses = s["top_excuses"]
    assert excuses[0]["reason"] == "Too tired"
    assert excuses[0]["count"] == 3
    assert excuses[1]["reason"] == "Had class"
    assert excuses[1]["count"] == 2


def test_top_excuses_empty_when_no_reasons():
    t = tasks(("skipped", "DSA", None), ("skipped", "DSA", None))
    s = compute_stats(t)
    assert s["top_excuses"] == []


def test_top_excuses_excludes_done_tasks():
    t = tasks(("done", "DSA", "This reason should not appear"))
    s = compute_stats(t)
    assert s["top_excuses"] == []


# ── Completion by category ────────────────────────────────────────────────────

def test_completion_by_category():
    t = [
        make_task(1, "done",    "DSA"),
        make_task(2, "done",    "DSA"),
        make_task(3, "skipped", "DSA"),
        make_task(4, "done",    "Fitness"),
        make_task(5, "skipped", "Fitness"),
        make_task(6, "skipped", "Fitness"),
    ]
    s = compute_stats(t)
    assert s["completion_by_category"]["DSA"]     == pytest.approx(2/3, abs=0.01)
    assert s["completion_by_category"]["Fitness"] == pytest.approx(1/3, abs=0.01)


def test_strongest_weakest_category():
    t = [
        make_task(1, "done",    "DSA"),
        make_task(2, "done",    "DSA"),
        make_task(3, "skipped", "Fitness"),
        make_task(4, "skipped", "Fitness"),
    ]
    s = compute_stats(t)
    assert s["strongest_category"] == "DSA"
    assert s["weakest_category"]   == "Fitness"


def test_pending_tasks_excluded_from_category_rate():
    t = [
        make_task(1, "done",    "DSA"),
        make_task(2, "pending", "DSA"),  # must not affect rate
        make_task(3, "pending", "DSA"),
    ]
    s = compute_stats(t)
    assert s["completion_by_category"]["DSA"] == 1.0


# ── Completion by day ─────────────────────────────────────────────────────────

def test_completion_by_day():
    t = [
        make_task(1, "done",    "DSA", "Monday, 7 PM - 8 PM"),
        make_task(2, "skipped", "DSA", "Monday, 9 PM - 10 PM"),
        make_task(3, "done",    "DSA", "Tuesday, 7 PM - 8 PM"),
    ]
    s = compute_stats(t)
    assert s["completion_by_day"]["Monday"]  == pytest.approx(0.5, abs=0.01)
    assert s["completion_by_day"]["Tuesday"] == 1.0


# ── Time slot helpers ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("scheduled_time,expected_hour", [
    ("Monday, 7 PM - 8 PM",   19),
    ("Tuesday, 9 AM - 10 AM",  9),
    ("Wednesday, 12 PM - 1 PM", 12),
    ("Friday, 12 AM - 1 AM",   0),
    ("Saturday, 11:30 PM - 12 AM", 23),
])
def test_parse_hour(scheduled_time, expected_hour):
    assert _parse_hour(scheduled_time) == expected_hour


@pytest.mark.parametrize("hour,expected_bucket", [
    (6,  "5AM-8AM"),
    (9,  "8AM-11AM"),
    (13, "11AM-2PM"),
    (15, "2PM-5PM"),
    (19, "5PM-8PM"),
    (21, "8PM-11PM"),
    (23, "11PM-2AM"),
])
def test_time_bucket(hour, expected_bucket):
    assert _to_bucket(hour) == expected_bucket


def test_completion_by_time_slot():
    t = [
        make_task(1, "done",    "DSA", "Monday, 7 PM - 8 PM"),   # 5PM-8PM
        make_task(2, "done",    "DSA", "Tuesday, 7 PM - 8 PM"),  # 5PM-8PM
        make_task(3, "skipped", "DSA", "Monday, 10 PM - 11 PM"), # 8PM-11PM
    ]
    s = compute_stats(t)
    assert s["completion_by_time_slot"]["5PM-8PM"]  == 1.0
    assert s["completion_by_time_slot"]["8PM-11PM"] == 0.0
    assert s["best_time_slot"]  == "5PM-8PM"
    assert s["worst_time_slot"] == "8PM-11PM"


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_task_list():
    s = compute_stats([])
    assert s["total_tasks"] == 0
    assert s["completion_rate"] == 0.0
    assert s["consecutive_misses"] == 0
    assert s["top_excuses"] == []
    assert s["strongest_category"] is None
    assert s["weakest_category"] is None
