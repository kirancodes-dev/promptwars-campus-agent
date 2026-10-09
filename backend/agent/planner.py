"""
Planner entry point: goal -> validated AgentPlan. Never executes tools.

The work is split into cohesive modules under agent/planning/:
  intent.py           which kind of request this is
  extraction.py       facts stated in the goal (subjects, durations, dates, exams, priorities, meeting)
  scheduling.py       free-slot search and study-block allocation
  study.py            study-planning workflows (single day, multi-day before exams, remember-then-plan)
  builders.py         single-action plans (tasks, notes, listings, preferences)
  preferences_text.py preferences stated in a sentence
  gemini_plan.py      validating Gemini's structured output
"""

from agent.planning.builders import (
    build_explain_assumptions_plan,
    build_general_plan,
    build_listing_plan,
    build_note_creation_plan,
    build_preference_listing_plan,
    build_preference_reset_plan,
    build_preference_update_plan,
    build_schedule_creation_plan,
    build_search_plan,
    build_task_and_schedule_plan,
    build_task_creation_plan,
)
from agent.planning.common import PlannerError, clarification_plan
from agent.planning.extraction import parse_study_requirements
from agent.planning.gemini_plan import plan_goal_with_gemini
from agent.planning.intent import VAGUE_GOALS, detect_intent
from agent.planning.study import build_chained_preference_and_study_plan, build_study_plan
from models.agent import AgentPlan, UserGoal

# Backwards-compatible names used by existing tests and callers.
_detect_intent = detect_intent
_parse_study_requirements = parse_study_requirements

__all__ = [
    "PlannerError",
    "VAGUE_GOALS",
    "detect_intent",
    "plan_goal",
    "plan_goal_smart",
    "plan_goal_with_gemini",
]

_BUILDERS = {
    "smart study planning": build_study_plan,
    "review and plan revision": build_study_plan,
    "study schedule planning": build_study_plan,
    "chained preference and study plan": build_chained_preference_and_study_plan,
    "task and schedule creation": build_task_and_schedule_plan,
    "explain assumptions": build_explain_assumptions_plan,
    "preference update": build_preference_update_plan,
    "preference listing": build_preference_listing_plan,
    "preference reset": build_preference_reset_plan,
    "task creation": build_task_creation_plan,
    "schedule creation": build_schedule_creation_plan,
    "note creation": build_note_creation_plan,
    "task listing": lambda goal: build_listing_plan(goal, "task listing"),
    "schedule listing": lambda goal: build_listing_plan(goal, "schedule listing"),
    "note search": build_search_plan,
}


def plan_goal(goal: UserGoal) -> AgentPlan:
    """Produce a validated AgentPlan from a UserGoal using the deterministic planner."""
    if not goal.goal or not goal.goal.strip():
        raise ValueError("Goal must contain meaningful text.")
    intent = detect_intent(goal.goal)
    if intent == "vague":
        return clarification_plan(
            goal,
            "Clarify request",
            "Clarification required before specific actions can be planned. "
            "Clarify study goal, subjects, duration and preferred time.",
        ).model_copy(update={"summary": "Clarification required before specific actions can be planned."})
    return _BUILDERS.get(intent, build_general_plan)(goal)


def plan_goal_smart(goal: UserGoal, gemini_service=None) -> AgentPlan:
    """Use Gemini when a service is provided; fall back to the deterministic planner on any planner error."""
    if gemini_service is not None:
        try:
            return plan_goal_with_gemini(goal, gemini_service)
        except PlannerError:
            return plan_goal(goal)
    return plan_goal(goal)
