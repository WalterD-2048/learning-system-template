"""
demo.py — 示范练习蓝图生成

核心职责：
- 检查示范练习前置条件
- 为示范练习生成三阶段渐退蓝图
- 保持题库覆盖维度完整，但不膨胀单次题量

用法：
    python -m engine.demo start SK-001
"""

import json
import sys
from typing import Any, Optional

try:
    import click
    from rich.console import Console
    from rich.table import Table
    from rich import box
except ImportError:
    print("请安装依赖: pip install click rich")
    sys.exit(1)

from engine.content import load_question_bank, load_skill_rubrics
from engine.state import load_config, load_graph, get_skill

console = Console()

DEFAULT_DEMO_BLUEPRINT = [
    {
        "stage": "worked_example",
        "coverage": "core",
        "question_type": "conceptual",
        "response_mode": "full_solution",
    },
    {
        "stage": "worked_example",
        "coverage": "misconception",
        "question_type": "argument_analysis",
        "response_mode": "full_solution",
    },
    {
        "stage": "faded_example",
        "coverage": "boundary",
        "question_type": "boundary",
        "response_mode": "scaffolded_fill",
    },
    {
        "stage": "faded_example",
        "coverage": "transfer",
        "question_type": "scenario",
        "response_mode": "scaffolded_fill",
    },
    {
        "stage": "independent_try",
        "coverage": "core",
        "question_type": "counterexample",
        "response_mode": "independent_short",
    },
    {
        "stage": "independent_try",
        "coverage": "bridge",
        "question_type": "cross_skill",
        "response_mode": "independent_short",
    },
]

STAGE_LABELS = {
    "worked_example": "完整示范",
    "faded_example": "部分提示",
    "independent_try": "独立尝试",
}

RESPONSE_MODE_HINTS = {
    "full_solution": "魏教授完整示范解题过程",
    "scaffolded_fill": "魏教授给骨架，学习者填空",
    "independent_short": "学习者独立短答，魏教授只做简短反馈",
}

DEMO_STAGE_FIT_MAP = {
    "worked_example": "demo_worked",
    "faded_example": "demo_faded",
    "independent_try": "demo_independent",
}


def _normalize_blueprint_entries(raw_entries: Any) -> list[dict[str, str]]:
    if not isinstance(raw_entries, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        stage = item.get("stage")
        coverage = item.get("coverage")
        question_type = item.get("question_type")
        response_mode = item.get("response_mode")
        if None in (stage, coverage, question_type, response_mode):
            continue
        normalized.append(
            {
                "stage": str(stage),
                "coverage": str(coverage),
                "question_type": str(question_type),
                "response_mode": str(response_mode),
            }
        )
    return normalized


def _count_values(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _select_question_bank_entry(
    question_bank: dict,
    used_entry_ids: set[str],
    template: dict[str, str],
    source_skills: list[str],
) -> Optional[dict]:
    entries = question_bank.get("entries", [])
    if not isinstance(entries, list):
        return None

    desired_stage_fit = DEMO_STAGE_FIT_MAP.get(template["stage"], "")
    desired_coverage = template["coverage"]
    desired_question_type = template["question_type"]

    def matches(entry: dict, strict_stage: bool, strict_type: bool, strict_related: bool) -> bool:
        if not isinstance(entry, dict):
            return False
        entry_id = entry.get("id")
        if not entry_id or str(entry_id) in used_entry_ids:
            return False
        if entry.get("coverage") != desired_coverage:
            return False
        if strict_type and entry.get("question_type") != desired_question_type:
            return False
        stage_fit = entry.get("stage_fit", [])
        if strict_stage and desired_stage_fit not in stage_fit:
            return False
        related_skills = entry.get("related_skills", [])
        if strict_related and len(source_skills) > 1:
            if not all(skill_id in source_skills for skill_id in related_skills):
                return False
        return True

    for strict_stage, strict_type, strict_related in (
        (True, True, True),
        (True, True, False),
        (True, False, False),
        (False, False, False),
    ):
        for entry in entries:
            if matches(entry, strict_stage, strict_type, strict_related):
                return entry
    return None


def generate_demo_plan(graph: dict, config: dict, skill_id: str) -> dict:
    """生成示范练习蓝图。"""
    sk = get_skill(graph, skill_id)
    classification = config.get("classification", "C")

    errors = []
    if sk["status"] not in ("concept_done", "demo_done"):
        if sk["status"] in ("locked", "unlocked"):
            errors.append(f"{skill_id} 尚未完成概念课")
        else:
            errors.append(f"{skill_id} 当前状态为 {sk['status']}，不适合开始示范练习")

    prerequisites = sk.get("prerequisites", [])
    for prereq_id in prerequisites:
        prereq = graph["skills"].get(prereq_id, {})
        if prereq.get("status") not in ("mastered", "long_term", "review_due"):
            errors.append(f"前置技能 {prereq_id} 未掌握（状态：{prereq.get('status', '?')}）")

    if errors:
        return {"error": errors, "skill_id": skill_id}

    demo_design = config.get("demo_question_design", {})
    blueprint = _normalize_blueprint_entries(demo_design.get("blueprint")) or DEFAULT_DEMO_BLUEPRINT
    total_questions = int(demo_design.get("total_questions", len(blueprint)) or len(blueprint))
    if total_questions < len(blueprint):
        blueprint = blueprint[:total_questions]
    elif total_questions > len(blueprint):
        extension = DEFAULT_DEMO_BLUEPRINT[len(blueprint) % len(DEFAULT_DEMO_BLUEPRINT):] or DEFAULT_DEMO_BLUEPRINT
        while len(blueprint) < total_questions:
            blueprint.extend(extension)
        blueprint = blueprint[:total_questions]

    question_bank = load_question_bank(skill_id)
    rubrics = load_skill_rubrics(skill_id)
    question_plan: list[dict[str, Any]] = []
    related_skill_ids = [prereq_id for prereq_id in prerequisites if prereq_id in graph["skills"]]
    used_entry_ids: set[str] = set()
    content_source = "question_bank" if question_bank else "blueprint_only"

    for index, template in enumerate(blueprint, start=1):
        question_type = template["question_type"]
        coverage = template["coverage"]
        source_skills = [skill_id]

        if coverage in ("bridge", "transfer") and related_skill_ids:
            source_skills = [related_skill_ids[0], skill_id]

        if question_type == "cross_skill" and len(source_skills) < 2:
            question_type = "argument_analysis"
            coverage = "misconception"

        selection_template = {**template, "question_type": question_type, "coverage": coverage}
        bank_entry = (
            _select_question_bank_entry(question_bank, used_entry_ids, selection_template, source_skills)
            if question_bank else None
        )

        item = {
            "question_index": index,
            "stage": template["stage"],
            "stage_label": STAGE_LABELS.get(template["stage"], template["stage"]),
            "coverage": coverage,
            "question_type": question_type,
            "response_mode": template["response_mode"],
            "response_hint": RESPONSE_MODE_HINTS.get(
                template["response_mode"], template["response_mode"]
            ),
            "source_skills": source_skills,
        }
        if bank_entry:
            entry_id = str(bank_entry["id"])
            used_entry_ids.add(entry_id)
            item.update(
                {
                    "bank_entry_id": entry_id,
                    "prompt": bank_entry.get("prompt"),
                    "source_sections": bank_entry.get("source_sections", []),
                    "expected_points": bank_entry.get("expected_points", []),
                    "difficulty": bank_entry.get("difficulty"),
                    "stage_fit": bank_entry.get("stage_fit", []),
                    "recommended_format": bank_entry.get("recommended_format"),
                    "rubric_id": bank_entry.get("rubric_id"),
                }
            )
            rubric_id = bank_entry.get("rubric_id")
            if rubric_id and str(rubric_id) in rubrics:
                rubric = rubrics[str(rubric_id)]
                item["rubric"] = {
                    "must_hit": rubric.get("must_hit", []),
                    "common_failures": rubric.get("common_failures", []),
                    "partial_credit_rules": rubric.get("partial_credit_rules", []),
                }

        question_plan.append(item)

    stage_counts = _count_values([item["stage"] for item in question_plan])
    coverage_counts = _count_values([item["coverage"] for item in question_plan])

    return {
        "skill_id": skill_id,
        "skill_name": sk.get("name", skill_id),
        "classification": classification,
        "total_questions": len(question_plan),
        "question_plan": question_plan,
        "stage_counts": stage_counts,
        "coverage_counts": coverage_counts,
        "related_skills": related_skill_ids,
        "content_source": content_source,
        "question_bank_loaded": question_bank is not None,
        "rubrics_loaded": bool(rubrics),
        "error": None,
    }


@click.group()
def cli():
    """示范练习蓝图"""
    pass


@cli.command()
@click.argument("skill_id")
def start(skill_id: str):
    """生成示范练习蓝图"""
    graph = load_graph()
    config = load_config()

    plan = generate_demo_plan(graph, config, skill_id)
    if plan.get("error"):
        console.print("[red]示范练习无法开始：[/red]")
        for err in plan["error"]:
            console.print(f"   ❌ {err}")
        sys.exit(1)

    console.print(f"\n[bold]📘 示范练习蓝图：{skill_id}[/bold]\n")
    console.print(f"   技能点：{plan['skill_name']}")
    console.print(f"   总题量：{plan['total_questions']}")
    console.print(f"   内容来源：{plan['content_source']}")
    if plan.get("related_skills"):
        console.print(f"   关联技能：{', '.join(plan['related_skills'])}")

    stage_table = Table(box=box.SIMPLE, title="阶段配额")
    stage_table.add_column("阶段")
    stage_table.add_column("题数", justify="right")
    for stage, count in plan["stage_counts"].items():
        stage_table.add_row(STAGE_LABELS.get(stage, stage), str(count))
    console.print(stage_table)

    coverage_table = Table(box=box.SIMPLE, title="覆盖维度")
    coverage_table.add_column("维度")
    coverage_table.add_column("题数", justify="right")
    for coverage, count in plan["coverage_counts"].items():
        coverage_table.add_row(coverage, str(count))
    console.print(coverage_table)

    blueprint_table = Table(box=box.SIMPLE, title="逐题蓝图")
    blueprint_table.add_column("#", justify="right")
    blueprint_table.add_column("阶段")
    blueprint_table.add_column("覆盖")
    blueprint_table.add_column("题型")
    blueprint_table.add_column("作答方式")
    blueprint_table.add_column("来源技能")
    blueprint_table.add_column("题库ID")
    for item in plan["question_plan"]:
        blueprint_table.add_row(
            str(item["question_index"]),
            item["stage_label"],
            item["coverage"],
            item["question_type"],
            item["response_mode"],
            ",".join(item["source_skills"]),
            item.get("bank_entry_id", "—"),
        )
    console.print(blueprint_table)

    console.print("\n[dim]JSON 输出（供系统解析）：[/dim]")
    console.print(json.dumps(plan, ensure_ascii=False, indent=2))
    console.print()


if __name__ == "__main__":
    cli()
