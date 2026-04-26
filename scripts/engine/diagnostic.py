"""
Adaptive diagnostic entry points.

The diagnostic module estimates a knowledge frontier from the typed graph and
student model, then applies compact diagnostic results back into the same event
and model pipeline used by practice sessions.
"""

import json
import sys
from datetime import date, timedelta
from typing import Any, Optional

try:
    import click
    from rich.console import Console
    from rich.table import Table
    from rich import box
except ImportError:
    print("Please install dependencies: pip install click rich")
    sys.exit(1)

from engine.event_log import ANSWER_EVENT_TYPE, append_event, parse_answer_result
from engine.graph import merge_graph_v2_assets, prerequisite_ids
from engine.state import check_unlockable, load_config, load_graph, save_graph
from engine.student_model import (
    derive_mastery_score,
    get_skill_student_model,
    model_from_mastery_score,
    update_models_from_event,
)
from engine.task_selection import rank_tasks, readiness_from_model, skill_state

console = Console()

ACTIVE_TASKS = {"learn", "practice", "frontier_probe", "validate", "remediate"}
MASTERED_STATUSES = {"mastered", "review_due", "long_term"}


def _store_model(skill: dict[str, Any], model: dict[str, Any]) -> None:
    if "mastery_score" not in model:
        model["mastery_score"] = derive_mastery_score(model)
    skill["student_model"] = model
    skill["mastery_score"] = model["mastery_score"]


def _unique_skill_items(tasks: list[dict[str, Any]], task_types: set[str], limit: int = 8) -> list[dict[str, Any]]:
    seen = set()
    items = []
    for task in tasks:
        if task.get("task_type") not in task_types:
            continue
        skill_id = task.get("skill_id")
        if not skill_id or skill_id in seen:
            continue
        seen.add(skill_id)
        items.append({
            "skill_id": skill_id,
            "task_type": task.get("task_type"),
            "score": task.get("score"),
            "status": task.get("status"),
            "estimated_minutes": task.get("estimated_minutes"),
            "reasons": task.get("reasons", []),
        })
        if len(items) >= limit:
            break
    return items


def diagnostic_summary(graph: dict[str, Any], limit: int = 8) -> dict[str, Any]:
    adaptive_graph = merge_graph_v2_assets(graph)
    tasks = rank_tasks(adaptive_graph, limit=max(limit * 3, 12))
    skills = adaptive_graph.get("skills", {})

    foundation_gaps = []
    mastered_skip_candidates = []
    for skill_id, skill in skills.items():
        model = skill_state(skill)
        readiness = readiness_from_model(model)
        if skill.get("status") not in MASTERED_STATUSES and readiness < 0.55:
            dependents = [
                sid for sid, candidate in skills.items()
                if skill_id in prerequisite_ids(adaptive_graph, sid)
                and candidate.get("status") != "locked"
            ]
            if dependents or skill.get("status") in {"learning", "needs_validation"}:
                foundation_gaps.append({
                    "skill_id": skill_id,
                    "status": skill.get("status"),
                    "readiness": round(readiness, 4),
                    "dependents": dependents,
                })
        if skill.get("status") not in MASTERED_STATUSES and readiness >= 0.82:
            mastered_skip_candidates.append({
                "skill_id": skill_id,
                "status": skill.get("status"),
                "readiness": round(readiness, 4),
                "mastery_score": model.get("mastery_score"),
            })

    return {
        "knowledge_frontier": _unique_skill_items(tasks, ACTIVE_TASKS, limit),
        "review_pressure": _unique_skill_items(tasks, {"review", "strengthen"}, limit),
        "foundation_gaps": foundation_gaps[:limit],
        "mastered_skip_candidates": mastered_skip_candidates[:limit],
        "recommended_next_tasks": tasks[:limit],
    }


def _normalize_diagnostic_results(raw: dict[str, Any]) -> dict[str, str]:
    if "answers" in raw and isinstance(raw["answers"], dict):
        raw = raw["answers"]
    results = {}
    for skill_id, value in raw.items():
        if value is None:
            continue
        results[str(skill_id)] = str(value)
    return results


def _diagnostic_event(skill_id: str, raw_result: str, session_id: Optional[str]) -> dict[str, Any]:
    normalized_result, error_type = parse_answer_result(raw_result)
    if raw_result in {"mastered", "known", "skip"}:
        normalized_result = "correct"
        error_type = None
    return append_event(
        ANSWER_EVENT_TYPE,
        {
            "session_id": session_id,
            "session_skill_id": "diagnostic",
            "skill_id": skill_id,
            "question_id": f"diagnostic:{skill_id}",
            "question_index": skill_id,
            "result": normalized_result,
            "raw_result": raw_result,
            "error_type": error_type,
            "question_type": "diagnostic",
            "answer_format": "diagnostic_probe",
            "difficulty_param": 0.65,
            "discrimination": 1.35,
            "skill_vector": {skill_id: 1.0},
        },
    )


def apply_diagnostic_results(
    graph: dict[str, Any],
    config: dict[str, Any],
    results: dict[str, str],
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    states = {
        sid: get_skill_student_model(skill)
        for sid, skill in graph.get("skills", {}).items()
        if isinstance(skill, dict)
    }
    events = []
    updates = []
    for skill_id, raw_result in results.items():
        skill = graph.get("skills", {}).get(skill_id)
        if not skill:
            updates.append({"skill_id": skill_id, "error": "unknown_skill"})
            continue
        event = _diagnostic_event(skill_id, raw_result, session_id)
        events.append(event)
        states = update_models_from_event(states, event)
        model = states[skill_id]

        if raw_result in {"mastered", "known", "skip"}:
            baseline = model_from_mastery_score(0.92)
            baseline["evidence_count"] = max(
                int(model.get("evidence_count", 0) or 0),
                int(baseline.get("evidence_count", 0) or 0),
            )
            baseline["last_evidence_at"] = event.get("timestamp")
            baseline["last_success_at"] = event.get("timestamp")
            model = baseline
            _store_model(skill, model)
            skill["status"] = "mastered"
            skill.setdefault("dates", {})["first_mastered"] = date.today().isoformat()
            skill.setdefault("dates", {})["last_practiced"] = date.today().isoformat()
            review = skill.setdefault("review", {})
            review["current_round"] = 0
            review["next_due"] = (date.today() + timedelta(days=1)).isoformat()
            review.setdefault("fire_credits", 0.0)
        elif event["result"] == "correct" and skill.get("status") in {"locked", "unlocked"}:
            _store_model(skill, model)
            skill["status"] = "demo_done"
            skill.setdefault("dates", {})["demo_completed"] = date.today().isoformat()
        elif event["result"] != "correct":
            _store_model(skill, model)
            if skill.get("status") in MASTERED_STATUSES:
                skill["status"] = "needs_validation"
            elif skill.get("status") == "locked":
                skill["status"] = "unlocked"
            else:
                skill["status"] = "learning"
        else:
            _store_model(skill, model)

        updates.append({
            "skill_id": skill_id,
            "result": event["result"],
            "status": skill.get("status"),
            "mastery_score": model.get("mastery_score"),
            "mastery_p": model.get("mastery_p"),
            "retrievability": model.get("retrievability"),
            "uncertainty": model.get("uncertainty"),
        })

    newly_unlocked = check_unlockable(graph)
    for unlocked_id in newly_unlocked:
        skill = graph["skills"][unlocked_id]
        skill.setdefault("student_model", get_skill_student_model(skill))

    return {
        "events_recorded": len(events),
        "updates": updates,
        "newly_unlocked": newly_unlocked,
        "next_summary": diagnostic_summary(graph),
    }


def render_summary(summary: dict[str, Any]) -> None:
    table = Table(box=box.SIMPLE, title="Knowledge frontier")
    table.add_column("skill")
    table.add_column("task")
    table.add_column("score", justify="right")
    table.add_column("status")
    table.add_column("reason")
    for item in summary.get("knowledge_frontier", []):
        table.add_row(
            str(item.get("skill_id", "")),
            str(item.get("task_type", "")),
            f"{float(item.get('score', 0.0) or 0.0):.2f}",
            str(item.get("status", "")),
            "; ".join(item.get("reasons", [])[:2]),
        )
    console.print(table)

    if summary.get("foundation_gaps"):
        gap_table = Table(box=box.SIMPLE, title="Foundation gaps")
        gap_table.add_column("skill")
        gap_table.add_column("readiness", justify="right")
        gap_table.add_column("status")
        gap_table.add_column("dependents")
        for item in summary["foundation_gaps"]:
            gap_table.add_row(
                item["skill_id"],
                f"{item['readiness']:.2f}",
                item["status"],
                ", ".join(item.get("dependents", [])) or "-",
            )
        console.print(gap_table)


@click.group()
def cli():
    """Adaptive diagnostic utilities."""


@cli.command("status")
@click.option("--limit", type=int, default=8)
@click.option("--json-output", is_flag=True)
def status_cmd(limit: int, json_output: bool):
    """Show diagnostic summary and recommended frontier tasks."""
    graph = load_graph()
    summary = diagnostic_summary(graph, limit=limit)
    if json_output:
        console.print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    render_summary(summary)


@cli.command("frontier")
@click.option("--limit", type=int, default=8)
@click.option("--json-output", is_flag=True)
def frontier_cmd(limit: int, json_output: bool):
    """Show only the current knowledge frontier."""
    graph = load_graph()
    frontier = diagnostic_summary(graph, limit=limit)["knowledge_frontier"]
    if json_output:
        console.print(json.dumps(frontier, ensure_ascii=False, indent=2))
        return
    render_summary({"knowledge_frontier": frontier})


@cli.command("apply")
@click.argument("results_json")
@click.option("--session-id", default=None)
@click.option("--json-output", is_flag=True)
def apply_cmd(results_json: str, session_id: Optional[str], json_output: bool):
    """Apply diagnostic results, for example '{"SK-001":"mastered","SK-002":"wrong:prerequisite"}'."""
    try:
        raw = json.loads(results_json)
        if not isinstance(raw, dict):
            raise ValueError("results must be a JSON object")
        results = _normalize_diagnostic_results(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        console.print(f"[red]Invalid diagnostic results:[/red] {exc}")
        sys.exit(1)

    graph = load_graph()
    config = load_config()
    output = apply_diagnostic_results(graph, config, results, session_id=session_id)
    save_graph(graph)
    if json_output:
        console.print(json.dumps(output, ensure_ascii=False, indent=2))
        return
    console.print(f"[green]Recorded {output['events_recorded']} diagnostic events[/green]")
    for item in output["updates"]:
        if item.get("error"):
            console.print(f"  {item['skill_id']}: {item['error']}")
        else:
            console.print(
                f"  {item['skill_id']}: {item['result']} -> {item['status']} "
                f"({float(item.get('mastery_score', 0.0) or 0.0):.0%})"
            )
    if output.get("newly_unlocked"):
        console.print(f"  newly unlocked: {', '.join(output['newly_unlocked'])}")


if __name__ == "__main__":
    cli()
