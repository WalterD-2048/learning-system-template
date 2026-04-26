"""
Explainable task selection v1.

This module ranks next learning tasks from the typed graph and student model.
It is intentionally read-only and side-by-side with engine.session so the
current session planner can adopt it incrementally.
"""

import json
import sys
from datetime import date, datetime
from typing import Any, Optional

try:
    import click
    from rich.console import Console
    from rich.table import Table
    from rich import box
except ImportError:
    print("Please install dependencies: pip install click rich")
    sys.exit(1)

from engine.fire import calculate_fire_awards
from engine.graph import (
    confusable_ids,
    dependent_ids,
    edges_from,
    get_skills,
    load_graph,
    prerequisite_ids,
)
from engine.student_model import (
    clamp,
    derive_mastery_score,
    estimate_retrievability,
    get_skill_student_model,
)

console = Console()

TASK_REVIEW = "review"
TASK_LEARN = "learn"
TASK_PRACTICE = "practice"
TASK_VALIDATE = "validate"
TASK_REMEDIATE = "remediate"
TASK_FRONTIER_PROBE = "frontier_probe"
TASK_STRENGTHEN = "strengthen"

ACTIVE_STATUSES = {"unlocked", "concept_done", "demo_done", "learning"}
MASTERED_STATUSES = {"mastered", "review_due", "long_term"}

DEFAULT_WEIGHTS = {
    "expected_mastery_gain": 2.0,
    "forgetting_risk_reduction": 1.7,
    "implicit_fire_gain": 1.2,
    "frontier_value": 1.1,
    "diagnostic_information_gain": 1.2,
    "prerequisite_stabilization": 0.8,
    "remediation_value": 1.5,
    "interference_penalty": 1.0,
    "frustration_risk": 1.3,
    "redundancy_penalty": 0.7,
}

TASK_BASE_MINUTES = {
    TASK_REVIEW: 6.0,
    TASK_LEARN: 12.0,
    TASK_PRACTICE: 9.0,
    TASK_VALIDATE: 5.0,
    TASK_REMEDIATE: 10.0,
    TASK_FRONTIER_PROBE: 4.0,
    TASK_STRENGTHEN: 7.0,
}


def parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def skill_state(skill: dict[str, Any], at_time: Optional[str] = None) -> dict[str, Any]:
    model = get_skill_student_model(skill)
    timestamp = at_time or now_iso()
    model["retrievability"] = estimate_retrievability(model, timestamp)
    model["mastery_score"] = derive_mastery_score(model)
    return model


def readiness_from_model(model: dict[str, Any]) -> float:
    return clamp(
        0.55 * float(model.get("mastery_p", 0.0))
        + 0.35 * float(model.get("retrievability", 0.0))
        + 0.10 * float(model.get("automaticity", 0.0))
        - 0.15 * float(model.get("uncertainty", 0.0))
    )


def prerequisite_readiness(
    graph: dict[str, Any],
    skill_id: str,
    at_time: Optional[str] = None,
) -> dict[str, Any]:
    skills = get_skills(graph)
    prereqs = prerequisite_ids(graph, skill_id)
    if not prereqs:
        return {
            "average": 1.0,
            "weakest": 1.0,
            "missing": [],
            "items": [],
        }

    items = []
    missing = []
    for prereq_id in prereqs:
        prereq = skills.get(prereq_id)
        if not prereq:
            missing.append(prereq_id)
            continue
        model = skill_state(prereq, at_time)
        readiness = readiness_from_model(model)
        items.append({
            "skill_id": prereq_id,
            "readiness": round(readiness, 4),
            "mastery_p": round(float(model.get("mastery_p", 0.0)), 4),
            "retrievability": round(float(model.get("retrievability", 0.0)), 4),
            "uncertainty": round(float(model.get("uncertainty", 0.0)), 4),
        })

    if not items:
        return {
            "average": 0.0,
            "weakest": 0.0,
            "missing": missing,
            "items": [],
        }
    values = [item["readiness"] for item in items]
    return {
        "average": round(sum(values) / len(values), 4),
        "weakest": round(min(values), 4),
        "missing": missing,
        "items": items,
    }


def due_review_info(skill: dict[str, Any], today: Optional[date] = None) -> Optional[dict[str, Any]]:
    today = today or date.today()
    if skill.get("status") not in MASTERED_STATUSES:
        return None
    review = skill.get("review", {})
    next_due = parse_date(review.get("next_due"))
    if skill.get("status") == "review_due" and next_due is None:
        return {"days_overdue": 0, "next_due": None}
    if next_due is None or next_due > today:
        return None
    return {
        "days_overdue": max((today - next_due).days, 0),
        "next_due": next_due.isoformat(),
        "review_round": review.get("current_round", 0),
        "fire_credits": float(review.get("fire_credits", 0.0) or 0.0),
    }


def recent_error_pressure(skill: dict[str, Any]) -> float:
    model = get_skill_student_model(skill)
    pressure = sum(float(count) for count in model.get("error_counts", {}).values())
    history = skill.get("practice_history", [])
    if isinstance(history, list) and history:
        last = history[-1] if isinstance(history[-1], dict) else {}
        counts = last.get("error_counts", {})
        if isinstance(counts, dict):
            pressure += sum(float(count) for count in counts.values())
        else:
            pressure += len(last.get("errors", [])) if isinstance(last.get("errors"), list) else 0
    return pressure


def error_counts(skill: dict[str, Any]) -> dict[str, float]:
    counts: dict[str, float] = {}
    model = get_skill_student_model(skill)
    for key, value in model.get("error_counts", {}).items():
        counts[str(key)] = counts.get(str(key), 0.0) + float(value)
    history = skill.get("practice_history", [])
    if isinstance(history, list) and history:
        last = history[-1] if isinstance(history[-1], dict) else {}
        raw_counts = last.get("error_counts", {})
        if isinstance(raw_counts, dict):
            for key, value in raw_counts.items():
                counts[str(key)] = counts.get(str(key), 0.0) + float(value)
        for error in last.get("errors", []) if isinstance(last.get("errors"), list) else []:
            counts[str(error)] = counts.get(str(error), 0.0) + 1.0
    return counts


def remediation_pressure_by_target(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Aggregate error pressure through ERR-* -> skill remediates edges.
    """
    skills = get_skills(graph)
    pressure: dict[str, dict[str, Any]] = {}
    for source_skill_id, skill in skills.items():
        for error_type, count in error_counts(skill).items():
            err_node = f"ERR-{error_type}"
            for edge in edges_from(graph, err_node, include_legacy=False):
                if edge.get("type") != "remediates":
                    continue
                target = str(edge.get("to"))
                if target not in skills:
                    continue
                weight = float(edge.get("weight", 1.0) or 1.0)
                item = pressure.setdefault(
                    target,
                    {"pressure": 0.0, "sources": [], "error_types": set()},
                )
                item["pressure"] += float(count) * weight
                item["sources"].append(source_skill_id)
                item["error_types"].add(str(error_type))
    normalized: dict[str, dict[str, Any]] = {}
    for skill_id, item in pressure.items():
        normalized[skill_id] = {
            "pressure": round(float(item["pressure"]), 4),
            "sources": sorted(set(item["sources"])),
            "error_types": sorted(item["error_types"]),
        }
    return normalized


def candidate_task_types(
    graph: dict[str, Any],
    skill_id: str,
    target_skill_id: Optional[str] = None,
    today: Optional[date] = None,
    at_time: Optional[str] = None,
    remediation_pressure: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    skills = get_skills(graph)
    skill = skills[skill_id]
    status = skill.get("status")
    model = skill_state(skill, at_time)
    prereq = prerequisite_readiness(graph, skill_id, at_time)
    due = due_review_info(skill, today)
    errors = recent_error_pressure(skill)
    tasks: list[dict[str, Any]] = []

    if status == "needs_validation":
        tasks.append({"task_type": TASK_VALIDATE, "trigger": "needs_validation"})

    if due is not None:
        tasks.append({"task_type": TASK_REVIEW, "trigger": "review_due", "due": due})
    elif status in MASTERED_STATUSES and float(model.get("retrievability", 1.0)) < 0.62:
        tasks.append({"task_type": TASK_REVIEW, "trigger": "low_retrievability"})

    if status in {"unlocked", "concept_done"}:
        tasks.append({"task_type": TASK_LEARN, "trigger": status})
    elif status in {"demo_done", "learning"}:
        tasks.append({"task_type": TASK_PRACTICE, "trigger": status})

    if errors > 0 and status != "locked":
        tasks.append({"task_type": TASK_REMEDIATE, "trigger": "recent_errors", "error_pressure": errors})
    if remediation_pressure and status != "locked":
        tasks.append({
            "task_type": TASK_REMEDIATE,
            "trigger": "graph_remediation",
            "error_pressure": remediation_pressure.get("pressure", 0.0),
            "remediation_sources": remediation_pressure.get("sources", []),
            "remediation_error_types": remediation_pressure.get("error_types", []),
        })

    if status == "locked" and prereq["average"] >= 0.68 and prereq["weakest"] >= 0.55:
        tasks.append({"task_type": TASK_FRONTIER_PROBE, "trigger": "prerequisites_nearly_ready"})

    if (
        status in MASTERED_STATUSES
        and float(model.get("mastery_p", 0.0)) < 0.82
        and float(model.get("uncertainty", 0.0)) > 0.18
    ):
        tasks.append({"task_type": TASK_STRENGTHEN, "trigger": "weak_mastery_or_uncertainty"})

    if target_skill_id:
        prereqs = set(prerequisite_ids(graph, target_skill_id))
        dependents = set(dependent_ids(graph, skill_id))
        if skill_id == target_skill_id and status != "locked":
            tasks.append({"task_type": TASK_PRACTICE, "trigger": "target_skill"})
        elif skill_id in prereqs and status != "locked":
            tasks.append({"task_type": TASK_VALIDATE, "trigger": "target_prerequisite"})
        elif target_skill_id in dependents and status in MASTERED_STATUSES:
            tasks.append({"task_type": TASK_STRENGTHEN, "trigger": "supports_target"})

    return dedupe_tasks(tasks)


def dedupe_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_type: dict[str, dict[str, Any]] = {}
    for task in tasks:
        task_type = task["task_type"]
        if task_type not in by_type:
            by_type[task_type] = task
            continue
        existing = by_type[task_type]
        existing["trigger"] = ",".join(sorted(set(str(existing.get("trigger", "")).split(",") + [str(task.get("trigger", ""))])))
        for key, value in task.items():
            if key == "error_pressure":
                existing[key] = float(existing.get(key, 0.0) or 0.0) + float(value or 0.0)
                continue
            if key in {"remediation_sources", "remediation_error_types"}:
                existing[key] = sorted(set(existing.get(key, []) + list(value or [])))
                continue
            existing.setdefault(key, value)
    return list(by_type.values())


def estimated_minutes(task_type: str, skill: dict[str, Any], model: dict[str, Any], prereq: dict[str, Any]) -> float:
    minutes = TASK_BASE_MINUTES.get(task_type, 8.0)
    complexity = skill.get("complexity")
    if isinstance(complexity, (int, float)):
        minutes *= 0.85 + 0.55 * clamp(float(complexity))
    elif complexity == "low":
        minutes *= 0.85
    elif complexity == "high":
        minutes *= 1.25
    minutes *= 1.0 + 0.25 * float(model.get("uncertainty", 0.0))
    if task_type in {TASK_LEARN, TASK_PRACTICE, TASK_REMEDIATE}:
        minutes *= 1.0 + 0.35 * (1.0 - float(prereq["average"]))
    return round(max(minutes, 2.0), 2)


def implicit_fire_gain(graph: dict[str, Any], skill_id: str, at_time: Optional[str] = None) -> float:
    skills = get_skills(graph)
    awards = calculate_fire_awards(graph, skill_id, passed=True, quality=0.85)
    gain = 0.0
    for award in awards:
        component = skills.get(award["skill_id"])
        if not component:
            continue
        model = skill_state(component, at_time)
        need = 0.65 * (1.0 - float(model.get("retrievability", 0.0))) + 0.35 * float(model.get("uncertainty", 0.0))
        gain += float(award["credit"]) * clamp(need)
    return round(gain, 4)


def prerequisite_stabilization(graph: dict[str, Any], skill_id: str, at_time: Optional[str] = None) -> float:
    skills = get_skills(graph)
    value = 0.0
    for dependent_id in dependent_ids(graph, skill_id):
        dependent = skills.get(dependent_id)
        if not dependent:
            continue
        if dependent.get("status") == "locked":
            value += 0.35
        elif dependent.get("status") in ACTIVE_STATUSES:
            value += 0.2
    model = skill_state(skills[skill_id], at_time)
    value *= 0.5 + 0.5 * float(model.get("uncertainty", 0.0))
    return round(value, 4)


def interference_penalty(graph: dict[str, Any], skill_id: str, at_time: Optional[str] = None) -> float:
    skills = get_skills(graph)
    penalty = 0.0
    for related_id in confusable_ids(graph, skill_id):
        related = skills.get(related_id)
        if not related:
            continue
        model = skill_state(related, at_time)
        related_readiness = readiness_from_model(model)
        if related_readiness < 0.7:
            penalty += (0.7 - related_readiness) * 0.8
    return round(penalty, 4)


def score_task(
    graph: dict[str, Any],
    skill_id: str,
    task: dict[str, Any],
    target_skill_id: Optional[str] = None,
    at_time: Optional[str] = None,
    weights: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    skills = get_skills(graph)
    skill = skills[skill_id]
    model = skill_state(skill, at_time)
    prereq = prerequisite_readiness(graph, skill_id, at_time)
    task_type = task["task_type"]
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}

    mastery_p = float(model.get("mastery_p", 0.0))
    retrievability = float(model.get("retrievability", 0.0))
    uncertainty = float(model.get("uncertainty", 0.0))
    readiness = float(prereq["average"])
    weakest_prereq = float(prereq["weakest"])

    mastery_target = 0.9 if task_type in {TASK_LEARN, TASK_PRACTICE, TASK_REMEDIATE} else 0.78
    expected_mastery_gain = clamp(mastery_target - mastery_p) * (0.45 + 0.55 * readiness) * (0.75 + uncertainty)
    if task_type == TASK_REVIEW:
        expected_mastery_gain *= 0.45
    elif task_type == TASK_VALIDATE:
        expected_mastery_gain *= 0.55
    elif task_type == TASK_FRONTIER_PROBE:
        expected_mastery_gain *= 0.35

    due = task.get("due")
    due_pressure = 0.0
    if isinstance(due, dict):
        due_pressure = min(float(due.get("days_overdue", 0)) / 7.0, 1.0)
    forgetting_risk_reduction = clamp(1.0 - retrievability) * (1.0 + 0.5 * due_pressure)
    if task_type not in {TASK_REVIEW, TASK_STRENGTHEN}:
        forgetting_risk_reduction *= 0.35

    fire_gain = implicit_fire_gain(graph, skill_id, at_time)

    frontier_value = 0.0
    if task_type in {TASK_LEARN, TASK_PRACTICE, TASK_FRONTIER_PROBE}:
        frontier_value = 0.45 * readiness + 0.45 * weakest_prereq + 0.10 * uncertainty
    if target_skill_id and skill_id == target_skill_id:
        frontier_value += 0.35
    elif target_skill_id and skill_id in prerequisite_ids(graph, target_skill_id):
        frontier_value += 0.2
    frontier_value = clamp(frontier_value)

    diagnostic_information_gain = uncertainty
    if task_type not in {TASK_VALIDATE, TASK_REMEDIATE, TASK_FRONTIER_PROBE}:
        diagnostic_information_gain *= 0.45

    stabilization = prerequisite_stabilization(graph, skill_id, at_time)
    error_pressure = recent_error_pressure(skill) + float(task.get("error_pressure", 0.0) or 0.0)
    remediation_value = clamp(error_pressure / 3.0) if task_type == TASK_REMEDIATE else 0.0
    if task.get("remediation_sources"):
        remediation_value = clamp(remediation_value + 0.15)
    interference = interference_penalty(graph, skill_id, at_time)
    frustration = 0.0
    if task_type in {TASK_LEARN, TASK_PRACTICE, TASK_REMEDIATE, TASK_FRONTIER_PROBE}:
        frustration += clamp(0.72 - weakest_prereq)
    if skill.get("status") == "locked" and task_type != TASK_FRONTIER_PROBE:
        frustration += 0.4

    redundancy = 0.0
    if mastery_p > 0.88 and retrievability > 0.82 and uncertainty < 0.16:
        redundancy = (mastery_p + retrievability) / 2.0 - 0.75
    if task_type == TASK_REVIEW and due is not None:
        redundancy *= 0.4

    minutes = estimated_minutes(task_type, skill, model, prereq)
    components = {
        "expected_mastery_gain": round(expected_mastery_gain, 4),
        "forgetting_risk_reduction": round(forgetting_risk_reduction, 4),
        "implicit_fire_gain": round(fire_gain, 4),
        "frontier_value": round(frontier_value, 4),
        "diagnostic_information_gain": round(diagnostic_information_gain, 4),
        "prerequisite_stabilization": round(stabilization, 4),
        "remediation_value": round(remediation_value, 4),
        "interference_penalty": round(interference, 4),
        "frustration_risk": round(frustration, 4),
        "redundancy_penalty": round(redundancy, 4),
    }
    gross = sum(
        components[name] * weights[name]
        for name in (
            "expected_mastery_gain",
            "forgetting_risk_reduction",
            "implicit_fire_gain",
            "frontier_value",
            "diagnostic_information_gain",
            "prerequisite_stabilization",
            "remediation_value",
        )
    )
    risk = sum(
        components[name] * weights[name]
        for name in ("interference_penalty", "frustration_risk", "redundancy_penalty")
    )
    score = max((gross - risk) / minutes * 10.0, 0.0)
    return {
        "task_id": f"{task_type}:{skill_id}",
        "task_type": task_type,
        "skill_id": skill_id,
        "name": skill.get("name", skill_id),
        "status": skill.get("status"),
        "trigger": task.get("trigger"),
        "score": round(score, 4),
        "estimated_minutes": minutes,
        "components": components,
        "model": {
            "mastery_p": round(mastery_p, 4),
            "retrievability": round(retrievability, 4),
            "automaticity": round(float(model.get("automaticity", 0.0)), 4),
            "uncertainty": round(uncertainty, 4),
            "mastery_score": round(float(model.get("mastery_score", 0.0)), 4),
        },
        "prerequisite_readiness": prereq,
        "remediation": {
            "error_pressure": round(error_pressure, 4),
            "sources": task.get("remediation_sources", []),
            "error_types": task.get("remediation_error_types", []),
        },
        "reasons": task_reasons(task_type, components, prereq, task),
    }


def task_reasons(
    task_type: str,
    components: dict[str, float],
    prereq: dict[str, Any],
    task: dict[str, Any],
) -> list[str]:
    reasons = [f"trigger={task.get('trigger')}"]
    positive = [
        (key, value)
        for key, value in components.items()
        if value > 0 and not key.endswith("_penalty") and key not in {"frustration_risk"}
    ]
    positive.sort(key=lambda item: item[1], reverse=True)
    reasons.extend(f"{key}={value:.2f}" for key, value in positive[:3])
    risks = [
        (key, value)
        for key, value in components.items()
        if value > 0 and (key.endswith("_penalty") or key == "frustration_risk")
    ]
    risks.sort(key=lambda item: item[1], reverse=True)
    reasons.extend(f"risk:{key}={value:.2f}" for key, value in risks[:2])
    if task_type in {TASK_LEARN, TASK_PRACTICE, TASK_FRONTIER_PROBE}:
        reasons.append(f"prereq_avg={prereq['average']:.2f}, weakest={prereq['weakest']:.2f}")
    if task.get("remediation_error_types"):
        reasons.append("errors=" + ",".join(task["remediation_error_types"][:3]))
    return reasons


def rank_tasks(
    graph: dict[str, Any],
    limit: int = 8,
    target_skill_id: Optional[str] = None,
    at_time: Optional[str] = None,
) -> list[dict[str, Any]]:
    today = date.today()
    ranked: list[dict[str, Any]] = []
    remediation_pressure = remediation_pressure_by_target(graph)
    for skill_id in get_skills(graph):
        for task in candidate_task_types(
            graph,
            skill_id,
            target_skill_id,
            today,
            at_time,
            remediation_pressure.get(skill_id),
        ):
            ranked.append(score_task(graph, skill_id, task, target_skill_id, at_time))
    ranked.sort(key=lambda item: (-item["score"], item["estimated_minutes"], item["task_id"]))
    return ranked[:limit]


@click.group()
def cli():
    """Explainable task selection utilities."""


@cli.command("next")
@click.option("--limit", type=int, default=8)
@click.option("--target", "target_skill_id", default=None)
@click.option("--json-output", is_flag=True)
def next_cmd(limit: int, target_skill_id: Optional[str], json_output: bool):
    """Rank next candidate tasks."""
    graph = load_graph()
    tasks = rank_tasks(graph, limit=limit, target_skill_id=target_skill_id)
    if json_output:
        console.print(json.dumps(tasks, ensure_ascii=False, indent=2))
        return
    render_tasks(tasks)


@cli.command("explain")
@click.argument("skill_id")
@click.option("--target", "target_skill_id", default=None)
@click.option("--json-output", is_flag=True)
def explain_cmd(skill_id: str, target_skill_id: Optional[str], json_output: bool):
    """Explain all candidate tasks for one skill."""
    graph = load_graph()
    if skill_id not in get_skills(graph):
        console.print(f"[red]Unknown skill:[/red] {skill_id}")
        sys.exit(1)
    today = date.today()
    tasks = [
        score_task(graph, skill_id, task, target_skill_id)
        for task in candidate_task_types(graph, skill_id, target_skill_id, today)
    ]
    tasks.sort(key=lambda item: (-item["score"], item["task_type"]))
    if json_output:
        console.print(json.dumps(tasks, ensure_ascii=False, indent=2))
        return
    render_tasks(tasks)


def render_tasks(tasks: list[dict[str, Any]]) -> None:
    if not tasks:
        console.print("[dim]No candidate tasks found[/dim]")
        return
    table = Table(box=box.SIMPLE)
    table.add_column("#", justify="right")
    table.add_column("task")
    table.add_column("skill")
    table.add_column("score", justify="right")
    table.add_column("min", justify="right")
    table.add_column("top reasons")
    for idx, task in enumerate(tasks, start=1):
        table.add_row(
            str(idx),
            task["task_type"],
            task["skill_id"],
            f"{task['score']:.2f}",
            f"{task['estimated_minutes']:.1f}",
            "; ".join(task.get("reasons", [])[:3]),
        )
    console.print(table)


if __name__ == "__main__":
    cli()
