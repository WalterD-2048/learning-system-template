"""
FIRe v2 preview and application helpers.

This module uses typed knowledge graph edges. It is intentionally independent
from review.py for now, so existing review behavior remains unchanged until the
new flow is explicitly integrated.
"""

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

try:
    import click
    from rich.console import Console
    from rich.table import Table
    from rich import box
except ImportError:
    print("Please install dependencies: pip install click rich")
    sys.exit(1)

from engine.graph import (
    CONFUSABLE_WITH,
    PREREQUISITE,
    confusable_ids,
    dependent_ids,
    edges_to,
    encompassed_components,
    get_skills,
    load_graph,
    prerequisite_ids,
)

console = Console()

DATA_DIR = Path(__file__).parent.parent / "data"
SKILL_GRAPH_FILE = DATA_DIR / "skill_graph.json"


def save_graph(graph: dict[str, Any]) -> None:
    metadata = graph.setdefault("metadata", {})
    metadata["last_modified"] = date.today().isoformat()
    with open(SKILL_GRAPH_FILE, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)


def fire_v2_config(config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    config = config or {}
    fire = config.get("fire_v2", config.get("fire", {}))
    return {
        "enabled": fire.get("enabled", True),
        "default_weight": float(fire.get("default_weight", 1.0)),
        "depth_decay": float(fire.get("depth_decay", 0.65)),
        "max_depth": int(fire.get("max_depth", 3)),
        "min_credit": float(fire.get("min_credit", 0.05)),
        "too_early_discount": float(fire.get("too_early_discount", 0.5)),
    }


def calculate_fire_awards(
    graph: dict[str, Any],
    skill_id: str,
    passed: bool = True,
    quality: float = 1.0,
    config: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    cfg = fire_v2_config(config)
    if not passed or not cfg["enabled"]:
        return []
    quality = max(0.0, min(float(quality), 1.0))
    components = encompassed_components(
        graph,
        skill_id,
        max_depth=cfg["max_depth"],
        min_flow=cfg["min_credit"],
        default_weight=cfg["default_weight"],
        depth_decay=cfg["depth_decay"],
    )
    awards = []
    for component in components:
        credit = round(component["credit"] * quality, 4)
        if credit < cfg["min_credit"]:
            continue
        awards.append({**component, "credit": credit, "quality": quality})
    return awards


def apply_fire_awards(
    graph: dict[str, Any],
    awards: list[dict[str, Any]],
    implicit: bool = True,
) -> list[dict[str, Any]]:
    skills = get_skills(graph)
    applied = []
    for award in awards:
        skill_id = award["skill_id"]
        skill = skills.get(skill_id)
        if not skill:
            continue
        review = skill.setdefault("review", {})
        before = float(review.get("fire_credits", 0.0) or 0.0)
        after = round(before + float(award["credit"]), 4)
        review["fire_credits"] = after
        review["last_fire_source"] = award.get("path", [])[-1] if award.get("path") else None
        review["last_fire_implicit"] = implicit
        applied.append({
            "skill_id": skill_id,
            "name": skill.get("name", skill_id),
            "credit": award["credit"],
            "before": before,
            "after": after,
            "depth": award.get("depth"),
            "path": award.get("path", []),
        })
    return applied


def failure_suggestions(
    graph: dict[str, Any],
    skill_id: str,
    error_types: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Produce graph-aware suggestions after failure without mutating state.
    """
    error_types = error_types or []
    prereqs = prerequisite_ids(graph, skill_id)
    dependents = dependent_ids(graph, skill_id)
    confusables = confusable_ids(graph, skill_id)

    remediation_targets = []
    for error_type in error_types:
        err_node = f"ERR-{error_type}"
        for edge in edges_to(graph, err_node):
            if edge.get("type") == "remediates":
                remediation_targets.append(str(edge.get("from")))
    remediation_targets = sorted(set(target for target in remediation_targets if target))

    return {
        "skill_id": skill_id,
        "error_types": error_types,
        "prerequisites_to_validate": prereqs,
        "dependents_to_increase_uncertainty": dependents,
        "confusable_skills_to_contrast": confusables,
        "remediation_targets": remediation_targets,
    }


@click.group()
def cli():
    """FIRe v2 utilities."""


@cli.command("preview")
@click.argument("skill_id")
@click.option("--quality", type=float, default=1.0)
@click.option("--passed/--failed", default=True)
def preview_cmd(skill_id: str, quality: float, passed: bool):
    """Preview fractional FIRe awards from typed component edges."""
    graph = load_graph()
    awards = calculate_fire_awards(graph, skill_id, passed=passed, quality=quality)
    if not awards:
        console.print("[dim]No FIRe v2 awards[/dim]")
        return
    table = Table(box=box.SIMPLE)
    table.add_column("skill")
    table.add_column("credit", justify="right")
    table.add_column("depth", justify="right")
    table.add_column("path")
    for award in awards:
        table.add_row(
            award["skill_id"],
            f"{award['credit']:.4f}",
            str(award.get("depth", "")),
            " / ".join(award.get("path", [])),
        )
    console.print(table)


@cli.command("apply")
@click.argument("skill_id")
@click.option("--quality", type=float, default=1.0)
def apply_cmd(skill_id: str, quality: float):
    """Apply FIRe v2 awards to review.fire_credits."""
    graph = load_graph()
    awards = calculate_fire_awards(graph, skill_id, passed=True, quality=quality)
    applied = apply_fire_awards(graph, awards)
    save_graph(graph)
    console.print(json.dumps(applied, ensure_ascii=False, indent=2))


@cli.command("failure")
@click.argument("skill_id")
@click.option("--error", "errors", multiple=True)
def failure_cmd(skill_id: str, errors: tuple[str, ...]):
    """Preview graph-aware failure remediation suggestions."""
    graph = load_graph()
    suggestions = failure_suggestions(graph, skill_id, list(errors))
    console.print(json.dumps(suggestions, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
