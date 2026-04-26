"""
Validate graph structure, content assets, measurement fields, and event logs.

Default mode reports missing course content as warnings so a fresh template can
still be inspected. Use --strict to fail on those content gaps.
"""

import json
import sys
from pathlib import Path
from typing import Any, Optional, Union

try:
    import click
    from rich.console import Console
    from rich.table import Table
    from rich import box
except ImportError:
    print("Please install dependencies: pip install click rich")
    sys.exit(1)

console = Console()

SCRIPTS_DIR = Path(__file__).parent.parent
ROOT_DIR = SCRIPTS_DIR.parent
DATA_DIR = SCRIPTS_DIR / "data"
CONTENT_DIR = SCRIPTS_DIR / "content"
QUESTION_BANK_DIR = CONTENT_DIR / "question_banks"
RUBRIC_DIR = CONTENT_DIR / "rubrics"
SCHEMA_DIR = CONTENT_DIR / "schema"
ERROR_TYPES_FILE = CONTENT_DIR / "misconceptions" / "error_types.json"
EVENT_DIR = DATA_DIR / "events"
SKILL_GRAPH_FILE = DATA_DIR / "skill_graph.json"

STATUSES = {
    "locked",
    "unlocked",
    "concept_done",
    "demo_done",
    "learning",
    "mastered",
    "review_due",
    "long_term",
    "needs_validation",
}
EDGE_TYPES = {
    "prerequisite",
    "encompasses",
    "component_of",
    "confusable_with",
    "remediates",
    "transfers_to",
    "source_anchor",
    "assessed_by",
    "variant_of",
}
QUESTION_REQUIRED = {
    "id",
    "coverage",
    "question_type",
    "recommended_format",
    "prompt",
    "source_sections",
    "expected_points",
    "stage_fit",
    "difficulty",
    "rubric_id",
}
RUBRIC_REQUIRED = {
    "id",
    "question_type",
    "recommended_format",
    "must_hit",
    "common_failures",
    "partial_credit_rules",
    "error_type_mapping",
}
COVERAGES = {"core", "misconception", "boundary", "transfer", "bridge"}
STAGE_FITS = {"demo_worked", "demo_faded", "demo_independent", "practice", "review"}


Finding = dict[str, str]


def rel(path: Union[Path, str]) -> str:
    path = Path(path)
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def add(findings: list[Finding], severity: str, code: str, path: Union[Path, str], message: str) -> None:
    findings.append({"severity": severity, "code": code, "path": rel(path), "message": message})


def load_json(path: Path, findings: list[Finding]) -> Optional[Any]:
    if not path.exists():
        add(findings, "error", "missing_file", path, "Required JSON file is missing.")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        add(findings, "error", "invalid_json", path, str(exc))
        return None


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def gap_severity(strict: bool) -> str:
    return "error" if strict else "warning"


def load_error_types(findings: list[Finding]) -> set[str]:
    if not ERROR_TYPES_FILE.exists():
        add(findings, "warning", "missing_error_type_registry", ERROR_TYPES_FILE, "Rubric error types cannot be checked.")
        return set()
    payload = load_json(ERROR_TYPES_FILE, findings)
    if not isinstance(payload, dict):
        return set()
    items = payload.get("error_types", [])
    if isinstance(items, dict):
        return {str(key) for key in items}
    ids = set()
    for item in as_list(items):
        if isinstance(item, dict) and item.get("id"):
            ids.add(str(item["id"]))
        elif isinstance(item, str):
            ids.add(item)
    return ids


def validate_graph(strict: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    graph = load_json(SKILL_GRAPH_FILE, findings)
    if not isinstance(graph, dict):
        return findings
    skills = graph.get("skills")
    if not isinstance(skills, dict) or not skills:
        add(findings, "error", "graph.skills_invalid", SKILL_GRAPH_FILE, "skills must be a non-empty object.")
        return findings

    for skill_id, skill in skills.items():
        path = f"{rel(SKILL_GRAPH_FILE)}#{skill_id}"
        if not isinstance(skill, dict):
            add(findings, "error", "skill.invalid", path, "Skill must be an object.")
            continue
        if not skill.get("name"):
            add(findings, "error", "skill.missing_name", path, "Skill is missing name.")
        if skill.get("status") not in STATUSES:
            add(findings, "error", "skill.invalid_status", path, f"Invalid status: {skill.get('status')!r}.")
        score = skill.get("mastery_score")
        if score is not None and (not is_number(score) or not 0 <= float(score) <= 1):
            add(findings, "error", "skill.invalid_mastery_score", path, "mastery_score must be in [0, 1].")
        prereqs = skill.get("prerequisites", [])
        if not isinstance(prereqs, list):
            add(findings, "error", "skill.invalid_prerequisites", path, "prerequisites must be a list.")
            prereqs = []
        for prereq_id in prereqs:
            if prereq_id == skill_id:
                add(findings, "error", "skill.self_prerequisite", path, "Skill cannot depend on itself.")
            if prereq_id not in skills:
                add(findings, "error", "skill.missing_prerequisite", path, f"Unknown prerequisite: {prereq_id}.")
        source = skill.get("source", {})
        if not isinstance(source, dict) or not any(source.get(key) for key in ("section", "anchor", "anchors")):
            add(findings, "warning", "skill.coarse_source_anchor", path, "No section or anchor reference found.")

    validate_cycles(skills, findings)
    validate_edges(graph, skills, findings)
    return findings


def validate_cycles(skills: dict[str, dict], findings: list[Finding]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(skill_id: str, stack: list[str]) -> None:
        if skill_id in visiting:
            start = stack.index(skill_id) if skill_id in stack else 0
            add(findings, "error", "graph.prerequisite_cycle", SKILL_GRAPH_FILE, " -> ".join(stack[start:] + [skill_id]))
            return
        if skill_id in visited:
            return
        visiting.add(skill_id)
        for prereq_id in as_list(skills.get(skill_id, {}).get("prerequisites")):
            if prereq_id in skills:
                visit(prereq_id, stack + [skill_id])
        visiting.remove(skill_id)
        visited.add(skill_id)

    for skill_id in skills:
        visit(skill_id, [])


def validate_edges(graph: dict[str, Any], skills: dict[str, dict], findings: list[Finding]) -> None:
    edges = graph.get("edges", [])
    if not edges:
        return
    if not isinstance(edges, list):
        add(findings, "error", "graph.edges_invalid", SKILL_GRAPH_FILE, "edges must be a list.")
        return
    for idx, edge in enumerate(edges):
        path = f"{rel(SKILL_GRAPH_FILE)}#edges[{idx}]"
        if not isinstance(edge, dict):
            add(findings, "error", "edge.invalid", path, "Edge must be an object.")
            continue
        if edge.get("type") not in EDGE_TYPES:
            add(findings, "error", "edge.invalid_type", path, f"Invalid edge type: {edge.get('type')!r}.")
        for field in ("from", "to"):
            node = edge.get(field)
            if node not in skills and not str(node).startswith("ERR-"):
                add(findings, "error", f"edge.missing_{field}", path, f"Unknown node: {node!r}.")
        if edge.get("weight") is not None and (not is_number(edge["weight"]) or float(edge["weight"]) < 0):
            add(findings, "error", "edge.invalid_weight", path, "weight must be non-negative.")


def validate_content(strict: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    graph = load_json(SKILL_GRAPH_FILE, findings)
    if not isinstance(graph, dict) or not isinstance(graph.get("skills"), dict):
        return findings
    if not (SCHEMA_DIR / "question_bank.schema.json").exists():
        add(findings, "warning", "schema.missing_question_bank_schema", SCHEMA_DIR, "Question bank schema is missing.")
    if not (SCHEMA_DIR / "rubric.schema.json").exists():
        add(findings, "warning", "schema.missing_rubric_schema", SCHEMA_DIR, "Rubric schema is missing.")

    error_types = load_error_types(findings)
    skills = graph["skills"]
    for skill_id, skill in skills.items():
        rubric_path = RUBRIC_DIR / f"{skill_id}.json"
        rubrics = validate_rubrics(skill_id, rubric_path, error_types, findings, strict)
        bank_path = QUESTION_BANK_DIR / f"{skill_id}.json"
        validate_question_bank(skill_id, skill, skills, bank_path, rubrics, findings, strict)
    return findings


def validate_rubrics(
    skill_id: str,
    path: Path,
    error_types: set[str],
    findings: list[Finding],
    strict: bool,
) -> dict[str, dict]:
    if not path.exists():
        add(findings, gap_severity(strict), "content.missing_rubric", path, f"No rubric file for {skill_id}.")
        return {}
    payload = load_json(path, findings)
    if not isinstance(payload, dict):
        return {}
    if payload.get("skill_id") != skill_id:
        add(findings, "error", "rubric.skill_id_mismatch", path, "skill_id does not match filename.")
    rubrics: dict[str, dict] = {}
    for idx, rubric in enumerate(as_list(payload.get("rubrics"))):
        rpath = f"{rel(path)}#rubrics[{idx}]"
        if not isinstance(rubric, dict):
            add(findings, "error", "rubric.invalid", rpath, "Rubric must be an object.")
            continue
        missing = sorted(RUBRIC_REQUIRED - set(rubric))
        if missing:
            add(findings, "error", "rubric.missing_fields", rpath, ", ".join(missing))
        rubric_id = rubric.get("id")
        if rubric_id in rubrics:
            add(findings, "error", "rubric.duplicate_id", rpath, f"Duplicate rubric id: {rubric_id}.")
        if rubric_id:
            rubrics[str(rubric_id)] = rubric
        for failure in as_list(rubric.get("common_failures")):
            if isinstance(failure, dict) and error_types and failure.get("error_type") not in error_types:
                add(findings, "error", "rubric.unknown_error_type", rpath, f"Unknown error_type: {failure.get('error_type')}.")
        mapping = rubric.get("error_type_mapping", {})
        if isinstance(mapping, dict) and error_types:
            for signal, error_type in mapping.items():
                if error_type not in error_types:
                    add(findings, "error", "rubric.unknown_mapped_error_type", rpath, f"{signal!r} -> {error_type!r}.")
    return rubrics


def validate_question_bank(
    skill_id: str,
    skill: dict,
    skills: dict[str, dict],
    path: Path,
    rubrics: dict[str, dict],
    findings: list[Finding],
    strict: bool,
) -> None:
    if not path.exists():
        add(findings, gap_severity(strict), "content.missing_question_bank", path, f"No question bank file for {skill_id}.")
        return
    payload = load_json(path, findings)
    if not isinstance(payload, dict):
        return
    if payload.get("skill_id") != skill_id:
        add(findings, "error", "question_bank.skill_id_mismatch", path, "skill_id does not match filename.")
    entries = as_list(payload.get("entries"))
    if not entries:
        add(findings, "error", "question_bank.entries_invalid", path, "entries must be a non-empty list.")
        return

    seen_ids: set[str] = set()
    coverages: set[str] = set()
    stages: set[str] = set()
    for idx, entry in enumerate(entries):
        qpath = f"{rel(path)}#entries[{idx}]"
        if not isinstance(entry, dict):
            add(findings, "error", "question.invalid", qpath, "Question entry must be an object.")
            continue
        missing = sorted(QUESTION_REQUIRED - set(entry))
        if missing:
            add(findings, "error", "question.missing_fields", qpath, ", ".join(missing))
        if entry.get("id") in seen_ids:
            add(findings, "error", "question.duplicate_id", qpath, f"Duplicate id: {entry.get('id')}.")
        if entry.get("id"):
            seen_ids.add(str(entry["id"]))
        coverage = entry.get("coverage")
        if coverage in COVERAGES:
            coverages.add(coverage)
        elif coverage is not None:
            add(findings, "error", "question.invalid_coverage", qpath, f"Invalid coverage: {coverage}.")
        for stage in as_list(entry.get("stage_fit")):
            if stage in STAGE_FITS:
                stages.add(stage)
            else:
                add(findings, "error", "question.invalid_stage_fit", qpath, f"Invalid stage_fit: {stage}.")
        if entry.get("rubric_id") and rubrics and entry["rubric_id"] not in rubrics:
            add(findings, "error", "question.missing_rubric_ref", qpath, f"Unknown rubric_id: {entry['rubric_id']}.")
        for related in as_list(entry.get("related_skills")):
            if related not in skills:
                add(findings, "error", "question.unknown_related_skill", qpath, f"Unknown related skill: {related}.")
        validate_measurement_fields(entry, skills, findings, qpath)

    missing_coverages = sorted({"core", "misconception", "boundary", "transfer"} - coverages)
    if missing_coverages:
        add(findings, gap_severity(strict), "content.missing_coverage", path, ", ".join(missing_coverages))
    missing_stages = sorted({"demo_worked", "demo_faded", "demo_independent"} - stages)
    if missing_stages:
        add(findings, gap_severity(strict), "content.missing_demo_stage", path, ", ".join(missing_stages))
    if skill.get("prerequisites") and "bridge" not in coverages:
        add(findings, gap_severity(strict), "content.missing_bridge", path, "Skill has prerequisites but no bridge item.")


def validate_measurement_fields(entry: dict[str, Any], skills: dict[str, dict], findings: list[Finding], path: str) -> None:
    vector = entry.get("skill_vector")
    if vector is not None:
        if not isinstance(vector, dict) or not vector:
            add(findings, "error", "question.invalid_skill_vector", path, "skill_vector must be a non-empty object.")
        else:
            total = 0.0
            for sid, weight in vector.items():
                if sid not in skills:
                    add(findings, "error", "question.skill_vector_unknown_skill", path, f"Unknown skill: {sid}.")
                if not is_number(weight) or not 0 <= float(weight) <= 1:
                    add(findings, "error", "question.skill_vector_invalid_weight", path, "Weights must be in [0, 1].")
                else:
                    total += float(weight)
            if total > 1.25:
                add(findings, "warning", "question.skill_vector_high_sum", path, f"Weights sum to {total:.2f}.")
    for field, minimum, maximum in (
        ("difficulty_param", 0.0, 1.0),
        ("discrimination", 0.0, 2.0),
        ("expected_time_sec", 1.0, None),
    ):
        value = entry.get(field)
        if value is None:
            continue
        if not is_number(value) or float(value) < minimum or (maximum is not None and float(value) > maximum):
            add(findings, "error", f"question.invalid_{field}", path, f"{field} is out of range.")
    hints = entry.get("allowed_hints")
    if hints is not None and (not isinstance(hints, int) or isinstance(hints, bool) or hints < 0):
        add(findings, "error", "question.invalid_allowed_hints", path, "allowed_hints must be a non-negative integer.")
    for field in ("misconception_targets", "target_edges"):
        if field in entry and not all(isinstance(item, str) and item for item in as_list(entry[field])):
            add(findings, "error", f"question.invalid_{field}", path, f"{field} must be a list of strings.")


def validate_events() -> list[Finding]:
    findings: list[Finding] = []
    if not EVENT_DIR.exists():
        return findings
    for path in sorted(EVENT_DIR.glob("*.jsonl")):
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                item_path = f"{rel(path)}:{line_no}"
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    add(findings, "error", "event.invalid_json", item_path, str(exc))
                    continue
                for field in ("event_id", "timestamp", "event_type"):
                    if not event.get(field):
                        add(findings, "error", "event.missing_field", item_path, f"Missing {field}.")
                if event.get("event_type") == "answer_submitted":
                    for field in ("skill_id", "question_id", "result"):
                        if not event.get(field):
                            add(findings, "error", "event.answer_missing_field", item_path, f"Missing {field}.")
    return findings


def validate_all(strict: bool = False) -> list[Finding]:
    return validate_graph(strict) + validate_content(strict) + validate_events()


def render(findings: list[Finding]) -> None:
    if not findings:
        console.print("[green]Validation passed with no findings[/green]")
        return
    errors = [item for item in findings if item["severity"] == "error"]
    warnings = [item for item in findings if item["severity"] == "warning"]
    console.print(f"[bold]Validation findings:[/bold] {len(errors)} errors, {len(warnings)} warnings")
    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("severity")
    table.add_column("code")
    table.add_column("path")
    table.add_column("message")
    for item in findings:
        style = "red" if item["severity"] == "error" else "yellow"
        table.add_row(f"[{style}]{item['severity']}[/{style}]", item["code"], item["path"], item["message"])
    console.print(table)


def finish(findings: list[Finding]) -> None:
    render(findings)
    if any(item["severity"] == "error" for item in findings):
        sys.exit(1)


@click.group()
def cli():
    """Validate graph, content assets, and event logs."""


@cli.command("all")
@click.option("--strict", is_flag=True, help="Treat content readiness gaps as errors.")
def all_cmd(strict: bool):
    finish(validate_all(strict))


@cli.command("graph")
def graph_cmd():
    finish(validate_graph())


@cli.command("content")
@click.option("--strict", is_flag=True, help="Treat missing content coverage as errors.")
def content_cmd(strict: bool):
    finish(validate_content(strict))


@cli.command("events")
def events_cmd():
    finish(validate_events())


if __name__ == "__main__":
    cli()
