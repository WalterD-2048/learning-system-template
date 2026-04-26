"""
Lightweight student model primitives.

This is an intentionally small v1.5 model: it keeps the existing public
mastery_score compatible while adding internal fields that can later support
adaptive diagnostics and expected-gain task selection.
"""

import json
import math
import sys
from copy import deepcopy
from datetime import datetime
from typing import Any, Optional, Union

try:
    import click
    from rich.console import Console
except ImportError:
    print("Please install dependencies: pip install click rich")
    sys.exit(1)

console = Console()

DEFAULT_MODEL = {
    "mastery_p": 0.05,
    "retrievability": 0.05,
    "stability_days": 1.0,
    "automaticity": 0.0,
    "uncertainty": 0.45,
    "evidence_count": 0,
    "success_streak": 0,
    "lapse_count": 0,
    "implicit_review_count": 0,
    "last_evidence_at": None,
    "last_success_at": None,
    "last_implicit_review_at": None,
    "error_counts": {},
}


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(maximum, max(minimum, float(value)))


def logistic(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def logit(probability: float) -> float:
    probability = clamp(probability, 0.001, 0.999)
    return math.log(probability / (1.0 - probability))


def parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def derive_mastery_score(model: dict[str, Any]) -> float:
    """
    Derive the old single score from the richer internal model.
    """
    score = (
        0.45 * float(model.get("mastery_p", 0.0))
        + 0.25 * float(model.get("retrievability", 0.0))
        + 0.20 * float(model.get("automaticity", 0.0))
        - 0.10 * float(model.get("uncertainty", 0.0))
    )
    return round(clamp(score), 4)


def estimate_retrievability(model: dict[str, Any], at_time: Optional[str] = None) -> float:
    timestamp = parse_time(at_time) or datetime.now().astimezone()
    last_success = parse_time(model.get("last_success_at")) or parse_time(model.get("last_evidence_at"))
    if last_success is None:
        return clamp(model.get("retrievability", model.get("mastery_p", 0.0)))
    elapsed_days = max((timestamp - last_success).total_seconds() / 86400.0, 0.0)
    stability_days = max(float(model.get("stability_days", 1.0)), 0.25)
    mastery_p = clamp(float(model.get("mastery_p", 0.0)))
    immediate_retrievability = 0.35 + 0.65 * mastery_p
    return round(clamp(immediate_retrievability * math.exp(-elapsed_days / stability_days)), 4)


def model_from_mastery_score(mastery_score: float) -> dict[str, Any]:
    mastery_score = clamp(mastery_score)
    model = deepcopy(DEFAULT_MODEL)
    model["mastery_p"] = round(clamp(mastery_score), 4)
    model["retrievability"] = round(clamp(mastery_score), 4)
    model["stability_days"] = round(max(1.0, 1.0 + 8.0 * mastery_score), 4)
    model["automaticity"] = round(clamp(max(0.0, mastery_score - 0.25)), 4)
    model["uncertainty"] = round(clamp(0.5 - 0.3 * mastery_score), 4)
    return model


def get_skill_student_model(skill: dict[str, Any]) -> dict[str, Any]:
    existing = skill.get("student_model")
    if isinstance(existing, dict):
        model = deepcopy(DEFAULT_MODEL)
        model.update(existing)
        return model
    return model_from_mastery_score(float(skill.get("mastery_score", 0.0) or 0.0))


def speed_bonus(response_time_sec: Optional[float], expected_time_sec: Optional[float]) -> float:
    if response_time_sec is None or expected_time_sec is None:
        return 0.0
    if expected_time_sec <= 0 or response_time_sec <= 0:
        return 0.0
    ratio = expected_time_sec / response_time_sec
    return clamp((ratio - 0.8) * 0.12, -0.04, 0.08)


def spacing_factor(model: dict[str, Any], at_time: Optional[str] = None) -> float:
    timestamp = parse_time(at_time) or datetime.now().astimezone()
    last_success = parse_time(model.get("last_success_at"))
    if last_success is None:
        return 0.2
    elapsed_days = max((timestamp - last_success).total_seconds() / 86400.0, 0.0)
    stability = max(float(model.get("stability_days", 1.0)), 0.25)
    return clamp(elapsed_days / stability, 0.0, 2.0)


def normalize_answer_result(result: Union[str, dict[str, Any]]) -> tuple[float, Optional[str], Optional[float], Optional[bool]]:
    if isinstance(result, dict):
        raw = str(result.get("result", ""))
        error_type = result.get("error_type")
        response_time_sec = result.get("response_time_sec")
        hint_used = result.get("hint_used")
    else:
        raw = str(result)
        error_type = None
        response_time_sec = None
        hint_used = None

    if raw == "correct":
        correctness = 1.0
    elif raw == "partial":
        correctness = 0.5
    elif raw.startswith("partial:"):
        correctness = 0.5
    else:
        correctness = 0.0
    if raw.startswith("wrong:") and error_type is None:
        error_type = raw.split(":", 1)[1] or "unspecified"
    elif raw == "wrong" and error_type is None:
        error_type = "unspecified"
    elif raw.startswith("partial:") and error_type is None:
        error_type = raw.split(":", 1)[1] or "partial"
    elif raw == "partial" and error_type is None:
        error_type = "partial"

    if response_time_sec is not None:
        response_time_sec = float(response_time_sec)
    return correctness, error_type, response_time_sec, hint_used


def item_evidence_weight(item: dict[str, Any]) -> float:
    discrimination = float(item.get("discrimination", 1.0) or 1.0)
    skill_weight = float(item.get("skill_weight", 1.0) or 1.0)
    return clamp(discrimination / 2.0, 0.05, 1.0) * clamp(skill_weight, 0.0, 1.0)


def answer_quality(
    correctness: float,
    response_time_sec: Optional[float],
    expected_time_sec: Optional[float],
    hint_used: Optional[bool],
) -> float:
    quality = clamp(correctness)
    if hint_used:
        quality *= 0.72
    if response_time_sec is not None and expected_time_sec is not None and expected_time_sec > 0:
        ratio = response_time_sec / expected_time_sec
        if ratio > 1.6:
            quality *= 0.85
        elif ratio < 0.75:
            quality = clamp(quality + 0.05)
    return round(clamp(quality), 4)


def update_after_answer(
    state: dict[str, Any],
    item: dict[str, Any],
    result: Union[str, dict[str, Any]],
    event_time: Optional[str] = None,
) -> dict[str, Any]:
    """
    Update one skill state from one item-level answer.

    item may include difficulty_param, discrimination, expected_time_sec, and
    skill_weight. result may be "correct", "wrong:boundary", or an event dict.
    """
    updated = deepcopy(DEFAULT_MODEL)
    updated.update(deepcopy(state))

    timestamp = event_time or now_iso()
    correctness, error_type, response_time_sec, hint_used = normalize_answer_result(result)
    difficulty = float(item.get("difficulty_param", 0.5) or 0.5)
    expected_time_sec = item.get("expected_time_sec")
    if expected_time_sec is not None:
        expected_time_sec = float(expected_time_sec)

    evidence = item_evidence_weight(item)
    quality = answer_quality(correctness, response_time_sec, expected_time_sec, hint_used)
    mastery_logit = logit(float(updated.get("mastery_p", 0.05)))

    if correctness >= 0.999:
        mastery_logit += 0.35 * evidence * (0.75 + difficulty) * max(quality, 0.5)
        updated["stability_days"] = round(
            max(0.5, float(updated.get("stability_days", 1.0)))
            * (1.0 + 0.25 * spacing_factor(updated, timestamp) + 0.15 * difficulty),
            4,
        )
        automaticity_delta = 0.03 + speed_bonus(response_time_sec, expected_time_sec)
        if hint_used:
            automaticity_delta *= 0.5
        updated["automaticity"] = round(clamp(float(updated.get("automaticity", 0.0)) + automaticity_delta), 4)
        updated["uncertainty"] = round(clamp(float(updated.get("uncertainty", 0.45)) - 0.04 * evidence), 4)
        updated["last_success_at"] = timestamp
        updated["success_streak"] = int(updated.get("success_streak", 0) or 0) + 1
    elif correctness > 0:
        mastery_logit += 0.12 * evidence * (0.75 + difficulty) * quality
        updated["stability_days"] = round(max(0.5, float(updated.get("stability_days", 1.0))) * 0.95, 4)
        updated["automaticity"] = round(clamp(float(updated.get("automaticity", 0.0)) - 0.01), 4)
        updated["uncertainty"] = round(clamp(float(updated.get("uncertainty", 0.45)) + 0.04 * evidence), 4)
        updated["success_streak"] = 0
        if error_type:
            error_counts = dict(updated.get("error_counts", {}))
            error_counts[str(error_type)] = error_counts.get(str(error_type), 0) + 1
            updated["error_counts"] = error_counts
    else:
        difficulty_penalty = 1.15 - 0.50 * clamp(difficulty)
        mastery_logit -= 0.45 * evidence * difficulty_penalty
        updated["stability_days"] = round(max(0.5, float(updated.get("stability_days", 1.0)) * 0.82), 4)
        updated["automaticity"] = round(clamp(float(updated.get("automaticity", 0.0)) - 0.03), 4)
        updated["uncertainty"] = round(clamp(float(updated.get("uncertainty", 0.45)) + 0.08 * evidence), 4)
        updated["success_streak"] = 0
        updated["lapse_count"] = int(updated.get("lapse_count", 0) or 0) + 1
        if error_type:
            error_counts = dict(updated.get("error_counts", {}))
            error_counts[str(error_type)] = error_counts.get(str(error_type), 0) + 1
            updated["error_counts"] = error_counts

    updated["mastery_p"] = round(clamp(logistic(mastery_logit)), 4)
    updated["last_evidence_at"] = timestamp
    updated["retrievability"] = estimate_retrievability(updated, timestamp)
    updated["evidence_count"] = int(updated.get("evidence_count", 0) or 0) + 1
    updated["mastery_score"] = derive_mastery_score(updated)
    return updated


def apply_fractional_review(
    state: dict[str, Any],
    credit: float,
    event_time: Optional[str] = None,
    implicit: bool = True,
) -> dict[str, Any]:
    """
    Apply FIRe or other implicit review credit without treating it as a full item.
    """
    updated = deepcopy(DEFAULT_MODEL)
    updated.update(deepcopy(state))
    timestamp = event_time or now_iso()
    credit = clamp(credit)
    if credit <= 0:
        return updated

    mastery_logit = logit(float(updated.get("mastery_p", 0.05)))
    mastery_logit += 0.12 * credit
    updated["mastery_p"] = round(clamp(logistic(mastery_logit)), 4)
    updated["retrievability"] = round(
        clamp(max(float(updated.get("retrievability", 0.0)), 0.35 + 0.45 * credit)),
        4,
    )
    updated["stability_days"] = round(
        max(0.5, float(updated.get("stability_days", 1.0))) * (1.0 + 0.10 * credit),
        4,
    )
    updated["uncertainty"] = round(clamp(float(updated.get("uncertainty", 0.45)) - 0.025 * credit), 4)
    updated["last_evidence_at"] = timestamp
    updated["last_implicit_review_at"] = timestamp if implicit else updated.get("last_implicit_review_at")
    updated["implicit_review_count"] = int(updated.get("implicit_review_count", 0) or 0) + 1
    updated["mastery_score"] = derive_mastery_score(updated)
    return updated


def update_models_from_event(
    states: dict[str, dict[str, Any]],
    event: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """
    Update every skill in an answer event's skill_vector.
    """
    skill_vector = event.get("skill_vector")
    if not isinstance(skill_vector, dict) or not skill_vector:
        skill_vector = {str(event.get("skill_id")): 1.0}

    updated = deepcopy(states)
    for skill_id, weight in skill_vector.items():
        if not skill_id or skill_id == "None":
            continue
        item = {
            "skill_weight": weight,
            "difficulty_param": event.get("difficulty_param", 0.5),
            "discrimination": event.get("discrimination", 1.0),
            "expected_time_sec": event.get("expected_time_sec"),
        }
        result = {
            "result": event.get("result", "wrong"),
            "error_type": event.get("error_type"),
            "response_time_sec": event.get("response_time_sec"),
            "hint_used": event.get("hint_used"),
        }
        updated[str(skill_id)] = update_after_answer(
            updated.get(str(skill_id), DEFAULT_MODEL),
            item,
            result,
            event.get("timestamp"),
        )
    return updated


@click.group()
def cli():
    """Student model utilities."""


@cli.command("init")
@click.option("--mastery-score", type=float, default=0.0)
def init_cmd(mastery_score: float):
    """Create a student model from a legacy mastery_score."""
    console.print(json.dumps(model_from_mastery_score(mastery_score), ensure_ascii=False, indent=2))


@cli.command("update")
@click.argument("state_json")
@click.argument("item_json")
@click.argument("result_json")
def update_cmd(state_json: str, item_json: str, result_json: str):
    """Update a model from JSON state, JSON item, and JSON/string result."""
    try:
        state = json.loads(state_json)
        item = json.loads(item_json)
        try:
            result: Union[str, dict[str, Any]] = json.loads(result_json)
        except json.JSONDecodeError:
            result = result_json
    except json.JSONDecodeError as exc:
        console.print(f"[red]Invalid JSON:[/red] {exc}")
        sys.exit(1)
    console.print(json.dumps(update_after_answer(state, item, result), ensure_ascii=False, indent=2))


@cli.command("update-event")
@click.argument("states_json")
@click.argument("event_json")
def update_event_cmd(states_json: str, event_json: str):
    """Update a skill->model mapping from one answer event JSON."""
    try:
        states = json.loads(states_json)
        event = json.loads(event_json)
    except json.JSONDecodeError as exc:
        console.print(f"[red]Invalid JSON:[/red] {exc}")
        sys.exit(1)
    console.print(json.dumps(update_models_from_event(states, event), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
