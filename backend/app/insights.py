"""
Behavioral Insights service — two clean layers:
  Layer A: compute_stats()      pure Python, no I/O, fast
  Layer B: generate_insights()  Claude API call, uses stats as context
"""

import os
import json
import re
from collections import Counter, defaultdict

import anthropic
from dotenv import load_dotenv

load_dotenv()

# ── Time-slot buckets ─────────────────────────────────────────────────────────

TIME_BUCKETS = [
    ("5AM-8AM",   5,  8),
    ("8AM-11AM",  8,  11),
    ("11AM-2PM",  11, 14),
    ("2PM-5PM",   14, 17),
    ("5PM-8PM",   17, 20),
    ("8PM-11PM",  20, 23),
    ("11PM-2AM",  23, 26),
]


def _parse_hour(scheduled_time: str) -> int | None:
    """'Monday, 7 PM - 8 PM'  →  19"""
    match = re.search(r'(\d{1,2})(?::\d{2})?\s*(AM|PM)', scheduled_time, re.IGNORECASE)
    if not match:
        return None
    hour, period = int(match.group(1)), match.group(2).upper()
    if period == "PM" and hour != 12:
        hour += 12
    elif period == "AM" and hour == 12:
        hour = 0
    return hour


def _to_bucket(hour: int) -> str:
    for label, start, end in TIME_BUCKETS:
        if start <= hour < end:
            return label
    return "Other"


# ── Mood mapping ──────────────────────────────────────────────────────────────

def _compute_mood(rate: float, consecutive_misses: int) -> str:
    if consecutive_misses >= 5:
        return "INTERVENTION"
    if rate < 0.20:
        return "INTERVENTION"
    if rate < 0.40:
        return "CHAOS"
    if rate < 0.60:
        return "CONCERNED"
    if rate < 0.80:
        return "STABLE"
    return "THRIVING"


# ── Layer A: pure stats ───────────────────────────────────────────────────────

def compute_stats(tasks: list) -> dict:
    """
    Accepts a list of SQLAlchemy Task objects (all tasks, all goals).
    Returns a plain dict matching the BehavioralStats schema.
    Pure Python — no I/O.
    """
    done_tasks    = [t for t in tasks if t.status == "done"]
    skipped_tasks = [t for t in tasks if t.status == "skipped"]
    pending_tasks = [t for t in tasks if t.status == "pending"]
    acted         = done_tasks + skipped_tasks

    done_count    = len(done_tasks)
    skipped_count = len(skipped_tasks)
    acted_count   = len(acted)

    completion_rate = done_count / acted_count if acted_count else 0.0

    # Consecutive misses — leading run of skips in most-recent-first order
    sorted_acted = sorted(acted, key=lambda t: t.id, reverse=True)
    consecutive_misses = 0
    for t in sorted_acted:
        if t.status == "skipped":
            consecutive_misses += 1
        else:
            break

    mood = _compute_mood(completion_rate, consecutive_misses)

    # By category
    cat_done  = defaultdict(int)
    cat_total = defaultdict(int)
    for t in acted:
        cat = t.category or "Uncategorized"
        cat_total[cat] += 1
        if t.status == "done":
            cat_done[cat] += 1
    completion_by_category = {
        cat: round(cat_done[cat] / cat_total[cat], 2)
        for cat in cat_total
    }

    # By day-of-week
    day_done  = defaultdict(int)
    day_total = defaultdict(int)
    for t in acted:
        if t.scheduled_time:
            day = t.scheduled_time.split(",")[0].strip()
            day_total[day] += 1
            if t.status == "done":
                day_done[day] += 1
    completion_by_day = {
        day: round(day_done[day] / day_total[day], 2)
        for day in day_total
    }

    # By time slot
    slot_done  = defaultdict(int)
    slot_total = defaultdict(int)
    for t in acted:
        if t.scheduled_time:
            hour = _parse_hour(t.scheduled_time)
            if hour is not None:
                slot = _to_bucket(hour)
                slot_total[slot] += 1
                if t.status == "done":
                    slot_done[slot] += 1
    completion_by_time_slot = {
        slot: round(slot_done[slot] / slot_total[slot], 2)
        for slot in slot_total
    }

    # Strongest / weakest
    strongest_category = (
        max(completion_by_category, key=completion_by_category.get)
        if completion_by_category else None
    )
    weakest_category = (
        min(completion_by_category, key=completion_by_category.get)
        if completion_by_category else None
    )
    best_time_slot = (
        max(completion_by_time_slot, key=completion_by_time_slot.get)
        if completion_by_time_slot else None
    )
    worst_time_slot = (
        min(completion_by_time_slot, key=completion_by_time_slot.get)
        if completion_by_time_slot else None
    )

    # Top excuses — exact match; Claude does fuzzy grouping in the prompt
    reasons = [t.skip_reason for t in skipped_tasks if t.skip_reason]
    top_excuses = [
        {"reason": r, "count": c}
        for r, c in Counter(reasons).most_common(10)
    ]

    return {
        "total_tasks":              len(tasks),
        "done":                     done_count,
        "skipped":                  skipped_count,
        "pending":                  len(pending_tasks),
        "completion_rate":          round(completion_rate, 3),
        "mood":                     mood,
        "consecutive_misses":       consecutive_misses,
        "completion_by_category":   completion_by_category,
        "completion_by_day":        completion_by_day,
        "completion_by_time_slot":  completion_by_time_slot,
        "strongest_category":       strongest_category,
        "weakest_category":         weakest_category,
        "best_time_slot":           best_time_slot,
        "worst_time_slot":          worst_time_slot,
        "top_excuses":              top_excuses,
    }


# ── Layer B: Claude insights ──────────────────────────────────────────────────

_INSIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern_summary":  {"type": "string"},
        "strengths":        {"type": "array", "items": {"type": "string"}},
        "weak_spots":       {"type": "array", "items": {"type": "string"}},
        "suggestions":      {"type": "array", "items": {"type": "string"}},
        "reschedule_hints": {"type": "array", "items": {"type": "string"}},
        "memory_summary": {
            "type": "object",
            "properties": {
                "best_time_slot":     {"type": "string"},
                "worst_time_slot":    {"type": "string"},
                "top_excuse":         {"type": "string"},
                "strongest_category": {"type": "string"},
                "weakest_category":   {"type": "string"},
            },
            "required": [
                "best_time_slot", "worst_time_slot", "top_excuse",
                "strongest_category", "weakest_category",
            ],
            "additionalProperties": False,
        },
    },
    "required": [
        "pattern_summary", "strengths", "weak_spots",
        "suggestions", "reschedule_hints", "memory_summary",
    ],
    "additionalProperties": False,
}


def generate_insights(stats: dict) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)

    excuse_lines = "\n".join(
        f'  - "{e["reason"]}": {e["count"]} time{"s" if e["count"] != 1 else ""}'
        for e in stats["top_excuses"]
    ) or "  (none recorded)"

    prompt = f"""Analyze this user's task completion data and generate behavioral insights.

OVERVIEW
  Completion rate : {stats['completion_rate'] * 100:.1f}%
  Mood level      : {stats['mood']}
  Done / Skipped  : {stats['done']} / {stats['skipped']}  (pending: {stats['pending']})
  Consecutive recent misses: {stats['consecutive_misses']}

BY CATEGORY
{json.dumps(stats['completion_by_category'], indent=2)}

BY DAY OF WEEK
{json.dumps(stats['completion_by_day'], indent=2)}

BY TIME SLOT
{json.dumps(stats['completion_by_time_slot'], indent=2)}

TOP SKIP REASONS (Excuse Wall)
{excuse_lines}

Output:
- pattern_summary: 2-3 sentence read on the user's current behavioral state
- strengths: what they consistently complete (be specific, use data)
- weak_spots: problem patterns (use data — days, slots, categories)
- suggestions: concrete actions to improve (3-5 items)
- reschedule_hints: specific scheduling changes for the adaptive agent
  e.g. "Move Fitness tasks to 8AM-11AM", "Cap Friday to 2 tasks max"
- memory_summary: distilled single values for each field — these are stored
  as persistent user memory consumed by future AI scheduling agents.
  If a field has no data, use "N/A".
"""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2048,
        thinking={"type": "adaptive"},
        system=(
            "You are a behavioral analyst for a productivity app. "
            "Be direct and specific. Base every claim on the numbers provided. "
            "Never invent patterns not supported by the data."
        ),
        output_config={
            "format": {
                "type": "json_schema",
                "schema": _INSIGHT_SCHEMA,
            }
        },
        messages=[{"role": "user", "content": prompt}],
    )

    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
