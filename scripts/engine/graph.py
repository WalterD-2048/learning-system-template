"""
Typed knowledge graph helpers.

The template still supports legacy `skills[SK].prerequisites`; this module
normalizes those prerequisites together with the newer top-level `edges` list.
"""

import json
import sys
from collections import deque
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

console = Console()

DATA_DIR = Path(__file__).parent.parent / "data"
SKILL_GRAPH_FILE = DATA_DIR / "skill_graph.json"
GRAPH_NODES_FILE = DATA_DIR / "graph.nodes.json"
GRAPH_EDGES_FILE = DATA_DIR / "graph.edges.json"

PREREQUISITE = "prerequisite"
ENCOMPASSES = "encompasses"
COMPONENT_OF = "component_of"
CONFUSABLE_WITH = "confusable_with"
REMEDIATES = "remediates"
TRANSFERS_TO = "transfers_to"
SOURCE_ANCHOR = "source_anchor"
ASSESSED_BY = "assessed_by"
VARIANT_OF = "variant_of"

NODE_TYPES = {
    "skill",
    "concept",
    "misconception",
    "question",
    "source_anchor",
    "learning_objective",
}
EDGE_TYPES = {
    PREREQUISITE,
    ENCOMPASSES,
    COMPONENT_OF,
    CONFUSABLE_WITH,
    REMEDIATES,
    TRANSFERS_TO,
    SOURCE_ANCHOR,
    ASSESSED_BY,
    VARIANT_OF,
}


def load_optional_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_node_payload(payload: Any) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}
    nodes = payload.get("nodes", payload) if isinstance(payload, dict) else payload
    if isinstance(nodes, dict):
        return {
            str(node_id): {**node, "id": str(node_id)}
            for node_id, node in nodes.items()
            if isinstance(node, dict)
        }
    if isinstance(nodes, list):
        normalized = {}
        for node in nodes:
            if isinstance(node, dict) and node.get("id"):
                normalized[str(node["id"])] = node
        return normalized
    return {}


def normalize_edge_payload(payload: Any) -> list[dict[str, Any]]:
    if not payload:
        return []
    edges = payload.get("edges", payload) if isinstance(payload, dict) else payload
    return [edge for edge in edges if isinstance(edge, dict)] if isinstance(edges, list) else []


def merge_graph_v2_assets(graph: dict[str, Any]) -> dict[str, Any]:
    """
    Merge optional graph.nodes.json and graph.edges.json into the legacy graph.

    The legacy skill_graph.json remains the compatibility source for current
    engine flows. The v2 assets add typed nodes and richer edges for audit,
    FIRe, diagnostics, and task selection.
    """
    graph = dict(graph)
    node_payload = load_optional_json(GRAPH_NODES_FILE)
    edge_payload = load_optional_json(GRAPH_EDGES_FILE)
    nodes = normalize_node_payload(node_payload)
    if nodes:
        graph["nodes"] = {**normalize_node_payload(graph.get("nodes")), **nodes}
    v2_edges = normalize_edge_payload(edge_payload)
    if v2_edges:
        graph["edges"] = [*explicit_edges(graph), *v2_edges]
    return graph


def load_graph(path: Optional[Path] = None) -> dict[str, Any]:
    graph_path = path or SKILL_GRAPH_FILE
    with open(graph_path, "r", encoding="utf-8") as f:
        graph = json.load(f)
    return graph if path is not None else merge_graph_v2_assets(graph)


def get_skills(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    skills = graph.get("skills", {})
    return skills if isinstance(skills, dict) else {}


def get_nodes(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = normalize_node_payload(graph.get("nodes"))
    for skill_id, skill in get_skills(graph).items():
        nodes.setdefault(
            skill_id,
            {
                "id": skill_id,
                "type": "skill",
                "name": skill.get("name", skill_id),
                "source": "legacy_skill_graph",
            },
        )
    return nodes


def node_exists(graph: dict[str, Any], node_id: Any) -> bool:
    node_id = str(node_id)
    return node_id in get_nodes(graph) or node_id.startswith("ERR-")


def explicit_edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    edges = graph.get("edges", [])
    return [edge for edge in edges if isinstance(edge, dict)] if isinstance(edges, list) else []


def legacy_prerequisite_edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for skill_id, skill in get_skills(graph).items():
        prereqs = skill.get("prerequisites", [])
        if not isinstance(prereqs, list):
            continue
        for prereq_id in prereqs:
            edges.append({
                "from": str(prereq_id),
                "to": str(skill_id),
                "type": PREREQUISITE,
                "weight": 1.0,
                "source": "legacy_prerequisites",
            })
    return edges


def normalize_edges(graph: dict[str, Any], include_legacy: bool = True) -> list[dict[str, Any]]:
    raw_edges = list(explicit_edges(graph))
    if include_legacy:
        explicit_prereq_pairs = {
            (edge.get("from"), edge.get("to"))
            for edge in raw_edges
            if edge.get("type") == PREREQUISITE
        }
        for edge in legacy_prerequisite_edges(graph):
            if (edge["from"], edge["to"]) not in explicit_prereq_pairs:
                raw_edges.append(edge)

    edges: list[dict[str, Any]] = []
    index: dict[tuple[Any, Any, Any], int] = {}
    seen = set()
    for edge in raw_edges:
        key = (edge.get("from"), edge.get("to"), edge.get("type"))
        if key in seen:
            edges[index[key]] = {**edges[index[key]], **edge}
            continue
        seen.add(key)
        index[key] = len(edges)
        edges.append(edge)
    return edges


def edges_from(
    graph: dict[str, Any],
    node_id: str,
    edge_type: Optional[str] = None,
    include_legacy: bool = True,
) -> list[dict[str, Any]]:
    return [
        edge for edge in normalize_edges(graph, include_legacy)
        if edge.get("from") == node_id and (edge_type is None or edge.get("type") == edge_type)
    ]


def edges_to(
    graph: dict[str, Any],
    node_id: str,
    edge_type: Optional[str] = None,
    include_legacy: bool = True,
) -> list[dict[str, Any]]:
    return [
        edge for edge in normalize_edges(graph, include_legacy)
        if edge.get("to") == node_id and (edge_type is None or edge.get("type") == edge_type)
    ]


def prerequisite_ids(graph: dict[str, Any], skill_id: str) -> list[str]:
    return sorted({
        str(edge["from"])
        for edge in edges_to(graph, skill_id, PREREQUISITE)
        if edge.get("from") in get_skills(graph)
    })


def dependent_ids(graph: dict[str, Any], skill_id: str) -> list[str]:
    return sorted({
        str(edge["to"])
        for edge in edges_from(graph, skill_id, PREREQUISITE)
        if edge.get("to") in get_skills(graph)
    })


def confusable_ids(graph: dict[str, Any], skill_id: str) -> list[str]:
    related = set()
    for edge in normalize_edges(graph, include_legacy=False):
        if edge.get("type") != CONFUSABLE_WITH:
            continue
        if edge.get("from") == skill_id and edge.get("to") in get_skills(graph):
            related.add(str(edge["to"]))
        if edge.get("to") == skill_id and edge.get("from") in get_skills(graph):
            related.add(str(edge["from"]))
    return sorted(related)


def component_edges(graph: dict[str, Any], skill_id: str) -> list[dict[str, Any]]:
    """
    Return edges that imply practicing skill_id also reviews a component skill.
    """
    results: list[dict[str, Any]] = []
    for edge in normalize_edges(graph, include_legacy=False):
        edge_type = edge.get("type")
        if edge_type == ENCOMPASSES and edge.get("from") == skill_id:
            results.append(edge)
        elif edge_type == COMPONENT_OF and edge.get("to") == skill_id:
            results.append({
                **edge,
                "from": edge.get("to"),
                "to": edge.get("from"),
                "type": ENCOMPASSES,
                "source": edge.get("source", COMPONENT_OF),
            })
    return results


def encompassed_components(
    graph: dict[str, Any],
    skill_id: str,
    max_depth: int = 3,
    min_flow: float = 0.01,
    default_weight: float = 1.0,
    depth_decay: float = 0.65,
) -> list[dict[str, Any]]:
    """
    Traverse typed component edges and return fractional review flow.
    """
    skills = get_skills(graph)
    queue = deque([(skill_id, 1.0, 0, [])])
    best_credit: dict[str, float] = {}
    results: list[dict[str, Any]] = []

    while queue:
        node_id, credit, depth, path = queue.popleft()
        if depth >= max_depth:
            continue
        for edge in component_edges(graph, node_id):
            component_id = edge.get("to")
            if component_id not in skills or component_id == skill_id:
                continue
            weight = float(edge.get("weight", default_weight) or default_weight)
            next_credit = credit * weight * (depth_decay ** depth)
            if next_credit < min_flow:
                continue
            if next_credit <= best_credit.get(component_id, 0.0):
                continue
            best_credit[component_id] = next_credit
            edge_path = path + [f"{edge.get('from')}->{component_id}:{edge.get('type')}"]
            results.append({
                "skill_id": str(component_id),
                "credit": round(next_credit, 4),
                "depth": depth + 1,
                "path": edge_path,
            })
            queue.append((str(component_id), next_credit, depth + 1, edge_path))

    results.sort(key=lambda item: (-item["credit"], item["skill_id"]))
    return results


@click.group()
def cli():
    """Typed knowledge graph utilities."""


@cli.command("nodes")
@click.option("--type", "node_type", default=None)
def nodes_cmd(node_type: Optional[str]):
    """List normalized graph nodes."""
    graph = load_graph()
    rows = [
        node for node in get_nodes(graph).values()
        if node_type is None or node.get("type") == node_type
    ]
    table = Table(box=box.SIMPLE)
    table.add_column("id")
    table.add_column("type")
    table.add_column("name")
    table.add_column("source")
    for node in sorted(rows, key=lambda item: str(item.get("id", ""))):
        table.add_row(
            str(node.get("id", "")),
            str(node.get("type", "")),
            str(node.get("name", "")),
            str(node.get("source", "")),
        )
    console.print(table)


@cli.command("edges")
@click.option("--type", "edge_type", default=None)
@click.option("--no-legacy", is_flag=True)
def edges_cmd(edge_type: Optional[str], no_legacy: bool):
    """List normalized graph edges."""
    graph = load_graph()
    rows = [
        edge for edge in normalize_edges(graph, include_legacy=not no_legacy)
        if edge_type is None or edge.get("type") == edge_type
    ]
    table = Table(box=box.SIMPLE)
    table.add_column("from")
    table.add_column("type")
    table.add_column("to")
    table.add_column("weight", justify="right")
    table.add_column("source")
    for edge in rows:
        table.add_row(
            str(edge.get("from", "")),
            str(edge.get("type", "")),
            str(edge.get("to", "")),
            str(edge.get("weight", "")),
            str(edge.get("source", "explicit")),
        )
    console.print(table)


@cli.command("components")
@click.argument("skill_id")
@click.option("--max-depth", type=int, default=3)
def components_cmd(skill_id: str, max_depth: int):
    """Preview encompassed component skills for FIRe v2."""
    graph = load_graph()
    components = encompassed_components(graph, skill_id, max_depth=max_depth)
    if not components:
        console.print("[dim]No encompassed components found[/dim]")
        return
    table = Table(box=box.SIMPLE)
    table.add_column("skill")
    table.add_column("credit", justify="right")
    table.add_column("depth", justify="right")
    table.add_column("path")
    for item in components:
        table.add_row(
            item["skill_id"],
            f"{item['credit']:.4f}",
            str(item["depth"]),
            " / ".join(item["path"]),
        )
    console.print(table)


if __name__ == "__main__":
    cli()
