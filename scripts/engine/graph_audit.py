"""
Knowledge graph quality audit.

This is stricter than structural validation: it checks whether the graph is
useful for adaptive learning, not just whether JSON is well-formed.
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

from engine.graph import (
    ASSESSED_BY,
    COMPONENT_OF,
    EDGE_TYPES,
    ENCOMPASSES,
    GRAPH_EDGES_FILE,
    GRAPH_NODES_FILE,
    NODE_TYPES,
    PREREQUISITE,
    REMEDIATES,
    SOURCE_ANCHOR,
    get_nodes,
    get_skills,
    load_graph,
    node_exists,
    normalize_edges,
)

console = Console()

SCRIPTS_DIR = Path(__file__).parent.parent
ROOT_DIR = SCRIPTS_DIR.parent
CONTENT_DIR = SCRIPTS_DIR / "content"
QUESTION_BANK_DIR = CONTENT_DIR / "question_banks"
ERROR_TYPES_FILE = CONTENT_DIR / "misconceptions" / "error_types.json"

Finding = dict[str, str]


def rel(path: Union[Path, str]) -> str:
    path = Path(path)
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def add(findings: list[Finding], severity: str, code: str, path: Union[Path, str], message: str) -> None:
    findings.append({"severity": severity, "code": code, "path": rel(path), "message": message})


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def question_bank_entries() -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    if not QUESTION_BANK_DIR.exists():
        return entries
    for path in sorted(QUESTION_BANK_DIR.glob("*.json")):
        payload = load_json(path)
        if not isinstance(payload, dict):
            continue
        for entry in as_list(payload.get("entries")):
            if isinstance(entry, dict) and entry.get("id"):
                entries[str(entry["id"])] = entry
    return entries


def error_type_ids() -> set[str]:
    payload = load_json(ERROR_TYPES_FILE)
    if not isinstance(payload, dict):
        return set()
    items = payload.get("error_types", [])
    ids = set()
    for item in as_list(items):
        if isinstance(item, dict) and item.get("id"):
            ids.add(str(item["id"]))
        elif isinstance(item, str):
            ids.add(item)
    return ids


def audit_graph(strict: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    graph = load_graph()
    nodes = get_nodes(graph)
    skills = get_skills(graph)
    edges = normalize_edges(graph)
    questions = question_bank_entries()
    strict_gap = "error" if strict else "warning"

    if not GRAPH_NODES_FILE.exists():
        add(findings, "warning", "kg_v2.missing_nodes_file", GRAPH_NODES_FILE, "graph.nodes.json is missing.")
    if not GRAPH_EDGES_FILE.exists():
        add(findings, "warning", "kg_v2.missing_edges_file", GRAPH_EDGES_FILE, "graph.edges.json is missing.")

    audit_nodes(nodes, findings)
    audit_edges(graph, edges, findings)
    audit_prerequisite_cycles(edges, findings)
    audit_skill_grounding(skills, edges, findings, strict_gap)
    audit_assessment_coverage(skills, edges, questions, findings, strict_gap)
    audit_component_edges(skills, edges, findings)
    audit_remediation_edges(nodes, edges, findings)
    audit_question_nodes(edges, nodes, questions, findings)
    return findings


def audit_nodes(nodes: dict[str, dict[str, Any]], findings: list[Finding]) -> None:
    for node_id, node in nodes.items():
        path = f"{rel(GRAPH_NODES_FILE)}#{node_id}"
        node_type = node.get("type")
        if node_type not in NODE_TYPES:
            add(findings, "error", "kg.node.invalid_type", path, f"Invalid node type: {node_type!r}.")
        if not node.get("name"):
            add(findings, "warning", "kg.node.missing_name", path, "Node is missing a human-readable name.")
        if node_type == "skill" and node.get("granularity") == "large":
            add(findings, "warning", "kg.skill.too_large", path, "Large skill should be split into smaller skills.")
        for field in ("complexity", "importance"):
            value = node.get(field)
            if value is not None and (not is_number(value) or not 0 <= float(value) <= 1):
                add(findings, "error", f"kg.node.invalid_{field}", path, f"{field} must be in [0, 1].")


def audit_edges(graph: dict[str, Any], edges: list[dict[str, Any]], findings: list[Finding]) -> None:
    seen = set()
    for idx, edge in enumerate(edges):
        path = f"{rel(GRAPH_EDGES_FILE)}#edges[{idx}]"
        edge_type = edge.get("type")
        if edge_type not in EDGE_TYPES:
            add(findings, "error", "kg.edge.invalid_type", path, f"Invalid edge type: {edge_type!r}.")
        for field in ("from", "to"):
            if not node_exists(graph, edge.get(field)):
                add(findings, "error", f"kg.edge.unknown_{field}", path, f"Unknown node: {edge.get(field)!r}.")
        key = (edge.get("from"), edge.get("to"), edge_type)
        if key in seen:
            add(findings, "warning", "kg.edge.duplicate", path, f"Duplicate edge: {key}.")
        seen.add(key)
        for field in ("weight", "confidence", "min_mastery"):
            value = edge.get(field)
            if value is not None and (not is_number(value) or not 0 <= float(value) <= 1):
                add(findings, "error", f"kg.edge.invalid_{field}", path, f"{field} must be in [0, 1].")
        if edge_type in {ENCOMPASSES, COMPONENT_OF, ASSESSED_BY, REMEDIATES} and edge.get("weight") is None:
            add(findings, "warning", "kg.edge.missing_weight", path, f"{edge_type} edge should include weight.")
        if edge.get("used_by") is None:
            add(findings, "warning", "kg.edge.missing_used_by", path, "Edge should say which algorithms use it.")


def audit_prerequisite_cycles(edges: list[dict[str, Any]], findings: list[Finding]) -> None:
    prereqs: dict[str, list[str]] = {}
    for edge in edges:
        if edge.get("type") == PREREQUISITE:
            prereqs.setdefault(str(edge.get("to")), []).append(str(edge.get("from")))

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str, stack: list[str]) -> None:
        if node_id in visiting:
            start = stack.index(node_id) if node_id in stack else 0
            add(findings, "error", "kg.prerequisite_cycle", GRAPH_EDGES_FILE, " -> ".join(stack[start:] + [node_id]))
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        for prereq_id in prereqs.get(node_id, []):
            visit(prereq_id, stack + [node_id])
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in prereqs:
        visit(node_id, [])


def audit_skill_grounding(
    skills: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    findings: list[Finding],
    severity: str,
) -> None:
    anchored = {
        str(edge.get("from"))
        for edge in edges
        if edge.get("type") == SOURCE_ANCHOR
    }
    touched = set()
    for edge in edges:
        if edge.get("from") in skills:
            touched.add(str(edge.get("from")))
        if edge.get("to") in skills:
            touched.add(str(edge.get("to")))
    for skill_id, skill in skills.items():
        path = f"{rel(GRAPH_NODES_FILE)}#{skill_id}"
        source = skill.get("source", {})
        legacy_anchor = isinstance(source, dict) and any(source.get(key) for key in ("section", "anchor", "anchors"))
        if skill_id not in anchored and not legacy_anchor:
            add(findings, severity, "kg.skill.missing_source_anchor", path, "Skill has no source_anchor edge or legacy source anchor.")
        if skill_id not in touched:
            add(findings, "warning", "kg.skill.isolated", path, "Skill has no typed graph edges.")


def audit_assessment_coverage(
    skills: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    questions: dict[str, dict[str, Any]],
    findings: list[Finding],
    severity: str,
) -> None:
    assessed_by = {
        str(edge.get("from"))
        for edge in edges
        if edge.get("type") == ASSESSED_BY
    }
    vector_coverage = set()
    for entry in questions.values():
        vector = entry.get("skill_vector")
        if isinstance(vector, dict):
            vector_coverage.update(str(skill_id) for skill_id in vector)
    for skill_id in skills:
        if skill_id not in assessed_by and skill_id not in vector_coverage:
            add(findings, severity, "kg.skill.missing_assessment", f"{rel(GRAPH_NODES_FILE)}#{skill_id}", "Skill has no assessed_by edge or question skill_vector coverage.")


def audit_component_edges(skills: dict[str, dict[str, Any]], edges: list[dict[str, Any]], findings: list[Finding]) -> None:
    component_sources = {
        str(edge.get("from"))
        for edge in edges
        if edge.get("type") == ENCOMPASSES
    }
    component_targets = {
        str(edge.get("to"))
        for edge in edges
        if edge.get("type") == COMPONENT_OF
    }
    for skill_id, skill in skills.items():
        has_prereq = bool(skill.get("prerequisites")) or any(
            edge.get("type") == PREREQUISITE and edge.get("to") == skill_id
            for edge in edges
        )
        if has_prereq and skill_id not in component_sources and skill_id not in component_targets:
            add(
                findings,
                "warning",
                "kg.skill.missing_encompasses",
                f"{rel(GRAPH_EDGES_FILE)}#{skill_id}",
                "Skill has prerequisites but no encompasses/component_of edge for FIRe v2.",
            )


def audit_remediation_edges(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]], findings: list[Finding]) -> None:
    remediated = {
        str(edge.get("from"))
        for edge in edges
        if edge.get("type") == REMEDIATES
    }
    for node_id, node in nodes.items():
        if node.get("type") == "misconception" and node_id not in remediated:
            add(findings, "warning", "kg.misconception.missing_remediates", f"{rel(GRAPH_NODES_FILE)}#{node_id}", "Misconception node has no remediates edge.")


def audit_question_nodes(
    edges: list[dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    questions: dict[str, dict[str, Any]],
    findings: list[Finding],
) -> None:
    for edge in edges:
        if edge.get("type") != ASSESSED_BY:
            continue
        question_id = str(edge.get("to"))
        node = nodes.get(question_id)
        if node is None and question_id not in questions:
            add(findings, "warning", "kg.assessed_by.question_missing", GRAPH_EDGES_FILE, f"Question {question_id} is not in graph.nodes.json or question banks.")
        if node is not None and node.get("type") != "question":
            add(findings, "error", "kg.assessed_by.target_not_question", GRAPH_EDGES_FILE, f"{question_id} should be a question node.")


def render(findings: list[Finding]) -> None:
    if not findings:
        console.print("[green]Knowledge graph audit passed with no findings[/green]")
        return
    errors = [item for item in findings if item["severity"] == "error"]
    warnings = [item for item in findings if item["severity"] == "warning"]
    console.print(f"[bold]Knowledge graph audit:[/bold] {len(errors)} errors, {len(warnings)} warnings")
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
    """Audit knowledge graph quality for adaptive learning."""


@cli.command("run")
@click.option("--strict", is_flag=True, help="Treat missing source/assessment coverage as errors.")
def run_cmd(strict: bool):
    finish(audit_graph(strict))


@cli.command("json")
@click.option("--strict", is_flag=True)
def json_cmd(strict: bool):
    findings = audit_graph(strict)
    console.print(json.dumps(findings, ensure_ascii=False, indent=2))
    if any(item["severity"] == "error" for item in findings):
        sys.exit(1)


if __name__ == "__main__":
    cli()
