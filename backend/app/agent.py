import os
import json
import anthropic
from dotenv import load_dotenv

load_dotenv()

# ── Shared output schema ──────────────────────────────────────────────────────

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "category": {"type": "string"},
                    "duration": {"type": "integer"},
                    "scheduled_time": {"type": "string"},
                },
                "required": ["title", "category", "duration", "scheduled_time"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["tasks", "summary"],
    "additionalProperties": False,
}

# ── System prompts ────────────────────────────────────────────────────────────

_BASE_SYSTEM = """You are an expert productivity and learning planner. When given a user goal, generate a detailed 7-day weekly plan with specific, actionable tasks.

For each task provide:
- title: Clear, specific task name (e.g., "DSA Practice - Arrays & Strings", "30-min Morning Run")
- category: A concise label (e.g., DSA, System Design, Fitness, Learning, Project, Review, Practice)
- duration: Time in minutes as an integer (e.g., 60 for 1 hour)
- scheduled_time: Day and time slot as a string (e.g., "Monday, 7 PM - 8 PM", "Wednesday, 9 AM - 10 AM")

Create 14-21 tasks spread across the week. Follow these principles:
- Schedule cognitively demanding tasks in the morning or early evening when energy is higher
- Mix different categories across days to avoid monotony
- Reduce intensity on weekends — lighter review or rest tasks
- Build progressively: start moderate on Monday, peak mid-week, wind down Friday-Sunday

Return a 2-3 sentence summary explaining the overall strategy for this week's plan."""

_ADAPTIVE_SYSTEM = """You are an expert productivity planner with access to the user's behavioral history.

Generate a detailed 7-day weekly plan. For each task provide:
- title: Clear, specific task name
- category: DSA, System Design, Fitness, Learning, Project, Review, Practice, Research
- duration: Time in minutes as an integer
- scheduled_time: "DayName, H AM/PM - H AM/PM" (e.g. "Monday, 7 PM - 8 PM")

Create 14-21 tasks spread across the week.

CRITICAL — when behavioral memory is provided:
1. Move tasks that historically fail in the worst time slot into the best time slot
2. Reduce load on the weakest category during high-density days
3. Avoid scheduling patterns that triggered the top excuse
4. Follow any explicit rescheduling directives exactly as stated

Return a 2-3 sentence summary explaining your adaptive strategy and what you changed vs a generic plan."""


# ── Internal client factory ───────────────────────────────────────────────────

def _client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
    return anthropic.Anthropic(api_key=api_key)


def _call(client: anthropic.Anthropic, system: str, user_content: str) -> dict:
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=system,
        output_config={"format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
        messages=[{"role": "user", "content": user_content}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_plan(goal: str) -> dict:
    return _call(_client(), _BASE_SYSTEM, f"Goal: {goal}")


def generate_adaptive_plan(goal: str, memory: dict, reschedule_hints: list[str]) -> dict:
    """
    Like generate_plan but enriched with UserProfile memory and behavioral
    rescheduling directives from the latest Insight.
    """
    memory_block = ""
    has_memory = any(v for v in memory.values() if v and v not in ("N/A", "Unknown"))
    if has_memory:
        memory_block = (
            "\n\nBEHAVIORAL MEMORY — use this to optimise scheduling:\n"
            f"  Best work time slot  : {memory.get('best_time_slot', 'N/A')}\n"
            f"  Worst work time slot : {memory.get('worst_time_slot', 'N/A')}\n"
            f"  Strongest category   : {memory.get('strongest_category', 'N/A')}\n"
            f"  Weakest category     : {memory.get('weakest_category', 'N/A')}\n"
            f"  Top excuse for misses: {memory.get('top_excuse', 'N/A')}\n"
        )

    hints_block = ""
    if reschedule_hints:
        hints_block = "\nRESCHEDULING DIRECTIVES — must follow:\n" + "\n".join(
            f"  - {h}" for h in reschedule_hints
        )

    user_content = f"Goal: {goal}{memory_block}{hints_block}"
    return _call(_client(), _ADAPTIVE_SYSTEM, user_content)
