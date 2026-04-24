"""
content.py — 题库与 rubric 资产管理

核心职责：
- 读取结构化题库与 rubric
- 检查 skill 内容覆盖度
- 审计题库质量与模板化风险
- 输出最小内容缺口报告

用法：
    python -m engine.content coverage
    python -m engine.content audit
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

try:
    import click
    from rich.console import Console
    from rich.table import Table
    from rich import box
except ImportError:
    print("请安装依赖: pip install click rich")
    sys.exit(1)

from engine.state import load_graph

console = Console()

CONTENT_DIR = Path(__file__).parent.parent / "content"
QUESTION_BANK_DIR = CONTENT_DIR / "question_banks"
RUBRIC_DIR = CONTENT_DIR / "rubrics"
SCHEMA_DIR = CONTENT_DIR / "schema"

REQUIRED_COVERAGES = ("core", "misconception", "boundary", "transfer")
REQUIRED_DEMO_STAGE_FITS = ("demo_worked", "demo_faded", "demo_independent")
MIN_RECOMMENDED_ENTRY_COUNT = 10
THICK_BANK_ENTRY_COUNT = 14
MAX_RECOMMENDED_MC_COUNT = 2
MAX_RECOMMENDED_COARSE_ANCHOR_RATIO = 0.8


def _normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    text = re.sub(r"SK-\d{3}B?", "SK-XXX", text)
    return text


def _prompt_opener(prompt: str) -> str:
    normalized = _normalize_text(prompt)
    for marker in ("：", ":", "，", ",", "。", "？", "?"):
        if marker in normalized:
            normalized = normalized.split(marker, 1)[0]
            break
    return normalized[:18]


def _shape_signature(entries: list[dict]) -> str:
    parts = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        parts.append(
            ":".join(
                [
                    str(entry.get("coverage", "")),
                    str(entry.get("question_type", "")),
                    str(entry.get("recommended_format", "")),
                ]
            )
        )
    return " | ".join(parts)


def _load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_question_bank(skill_id: str) -> Optional[dict]:
    """读取某个 skill 的结构化题库。"""
    return _load_json(QUESTION_BANK_DIR / f"{skill_id}.json")


def load_skill_rubrics(skill_id: str) -> dict[str, dict]:
    """读取某个 skill 的 rubric 映射。"""
    payload = _load_json(RUBRIC_DIR / f"{skill_id}.json") or {}
    rubrics = payload.get("rubrics", [])
    rubric_map: dict[str, dict] = {}
    if isinstance(rubrics, list):
        for rubric in rubrics:
            if not isinstance(rubric, dict):
                continue
            rubric_id = rubric.get("id")
            if rubric_id:
                rubric_map[str(rubric_id)] = rubric
    return rubric_map


def assess_skill_content(skill_id: str, skill: dict) -> dict:
    """检查单个 skill 的题库/rubric 覆盖度。"""
    question_bank = load_question_bank(skill_id)
    rubrics = load_skill_rubrics(skill_id)

    result = {
        "skill_id": skill_id,
        "name": skill.get("name", skill_id),
        "has_question_bank": question_bank is not None,
        "has_rubrics": bool(rubrics),
        "entry_count": 0,
        "rubric_count": len(rubrics),
        "missing_coverages": [],
        "missing_demo_stage_fits": [],
        "missing_bridge": False,
        "missing_rubric_refs": [],
    }

    if not question_bank:
        result["missing_coverages"] = list(REQUIRED_COVERAGES)
        result["missing_demo_stage_fits"] = list(REQUIRED_DEMO_STAGE_FITS)
        result["missing_bridge"] = bool(skill.get("prerequisites"))
        return result

    entries = question_bank.get("entries", [])
    if not isinstance(entries, list):
        entries = []
    result["entry_count"] = len(entries)

    coverage_present = set()
    demo_stage_fit_present = set()
    bridge_present = False

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        coverage = entry.get("coverage")
        if coverage:
            coverage_present.add(str(coverage))
            if coverage == "bridge":
                bridge_present = True
        stage_fit = entry.get("stage_fit", [])
        if isinstance(stage_fit, list):
            demo_stage_fit_present.update(str(item) for item in stage_fit)
        rubric_id = entry.get("rubric_id")
        if rubric_id and str(rubric_id) not in rubrics:
            result["missing_rubric_refs"].append(str(rubric_id))

    result["missing_coverages"] = [
        coverage for coverage in REQUIRED_COVERAGES if coverage not in coverage_present
    ]
    result["missing_demo_stage_fits"] = [
        stage for stage in REQUIRED_DEMO_STAGE_FITS if stage not in demo_stage_fit_present
    ]
    result["missing_bridge"] = bool(skill.get("prerequisites")) and not bridge_present
    result["missing_rubric_refs"] = sorted(set(result["missing_rubric_refs"]))
    return result


def assess_skill_quality(skill_id: str, skill: dict) -> dict:
    """检查单个 skill 的题库质量与模板化风险。"""
    question_bank = load_question_bank(skill_id)
    rubrics = load_skill_rubrics(skill_id)

    result = {
        "skill_id": skill_id,
        "name": skill.get("name", skill_id),
        "entry_count": 0,
        "family_count": 0,
        "question_type_count": 0,
        "answer_format_count": 0,
        "multiple_choice_count": 0,
        "counterexample_count": 0,
        "bridge_count": 0,
        "same_section_anchor_ratio": 0.0,
        "empty_common_failures_count": 0,
        "empty_partial_credit_count": 0,
        "shape_signature": "",
        "prompt_openers": [],
        "flags": [],
    }

    def add_flag(code: str, message: str):
        result["flags"].append({"code": code, "message": message})

    if not question_bank:
        add_flag("missing_question_bank", "题库缺失，无法做质量审计。")
        if not rubrics:
            add_flag("missing_rubrics", "rubric 缺失，无法做判分质量审计。")
        return result

    entries = question_bank.get("entries", [])
    if not isinstance(entries, list):
        entries = []
    rubric_items = list(rubrics.values())
    source = question_bank.get("source", {})
    source_section = str(source.get("section", ""))

    families = set()
    question_types = set()
    answer_formats = set()
    prompt_openers = []
    same_section_anchor_count = 0

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        family = entry.get("family")
        if family:
            families.add(str(family))
        question_type = entry.get("question_type")
        if question_type:
            question_types.add(str(question_type))
            if question_type == "counterexample":
                result["counterexample_count"] += 1
        answer_format = entry.get("recommended_format")
        if answer_format:
            answer_formats.add(str(answer_format))
            if answer_format == "multiple_choice_explained":
                result["multiple_choice_count"] += 1
        if entry.get("coverage") == "bridge":
            result["bridge_count"] += 1

        prompt = entry.get("prompt")
        if prompt:
            prompt_openers.append(_prompt_opener(str(prompt)))

        source_sections = entry.get("source_sections", [])
        if (
            isinstance(source_sections, list)
            and len(source_sections) == 1
            and source_section
            and str(source_sections[0]) == source_section
        ):
            same_section_anchor_count += 1

    result["entry_count"] = len(entries)
    result["family_count"] = len(families)
    result["question_type_count"] = len(question_types)
    result["answer_format_count"] = len(answer_formats)
    result["prompt_openers"] = prompt_openers
    result["shape_signature"] = _shape_signature(entries)
    result["same_section_anchor_ratio"] = (
        same_section_anchor_count / len(entries) if entries else 0.0
    )

    result["empty_common_failures_count"] = sum(
        1 for rubric in rubric_items if not rubric.get("common_failures")
    )
    result["empty_partial_credit_count"] = sum(
        1 for rubric in rubric_items if not rubric.get("partial_credit_rules")
    )

    if result["entry_count"] <= MIN_RECOMMENDED_ENTRY_COUNT:
        add_flag(
            "thin_bank",
            f"题库目前只有 {result['entry_count']} 题，仍处于最低可用线，建议扩到 {THICK_BANK_ENTRY_COUNT}+。",
        )
    if result["family_count"] < 4:
        add_flag("family_sparse", "题目 family 过少，变体覆盖可能不足。")
    if result["multiple_choice_count"] > MAX_RECOMMENDED_MC_COUNT:
        add_flag("multiple_choice_heavy", "选择题数量偏高，可能削弱主动提取训练。")
    if result["counterexample_count"] < 1:
        add_flag("missing_counterexample", "缺少反例题，边界训练不够。")
    if result["same_section_anchor_ratio"] >= MAX_RECOMMENDED_COARSE_ANCHOR_RATIO:
        add_flag("coarse_section_anchors", "原文锚点大多仍停留在 section 级，建议补到句段或关键词层。")
    if rubric_items and result["empty_common_failures_count"] == len(rubric_items):
        add_flag("rubric_common_failures_blank", "rubric 的 common_failures 仍是空白，判分稳定性不够。")
    if rubric_items and result["empty_partial_credit_count"] == len(rubric_items):
        add_flag("rubric_partial_credit_blank", "rubric 的 partial_credit_rules 仍是空白，部分分策略不够稳。")

    return result


def collect_content_coverage(graph: dict) -> list[dict]:
    """汇总所有 skill 的内容覆盖度。"""
    rows = []
    for skill_id, skill in graph["skills"].items():
        rows.append(assess_skill_content(skill_id, skill))
    return rows


def collect_content_audit(graph: dict) -> dict:
    """汇总题库质量审计结果。"""
    rows = []
    shape_counter: Counter[str] = Counter()
    opener_counter: Counter[str] = Counter()

    for skill_id, skill in graph["skills"].items():
        row = assess_skill_quality(skill_id, skill)
        rows.append(row)
        if row["shape_signature"]:
            shape_counter[row["shape_signature"]] += 1
        opener_counter.update(row["prompt_openers"])

    top_shape, top_shape_count = ("", 0)
    if shape_counter:
        top_shape, top_shape_count = shape_counter.most_common(1)[0]

    top_openers = [
        {"opener": opener, "count": count}
        for opener, count in opener_counter.most_common(8)
    ]

    summary = {
        "total_skills": len(rows),
        "skills_with_quality_flags": sum(1 for row in rows if row["flags"]),
        "skills_at_minimum_entry_count": sum(
            1 for row in rows if row["entry_count"] == MIN_RECOMMENDED_ENTRY_COUNT
        ),
        "skills_with_blank_common_failures": sum(
            1 for row in rows if row["empty_common_failures_count"] > 0
        ),
        "skills_with_coarse_anchors": sum(
            1 for row in rows if row["same_section_anchor_ratio"] >= MAX_RECOMMENDED_COARSE_ANCHOR_RATIO
        ),
        "most_reused_shape_count": top_shape_count,
        "most_reused_shape_signature": top_shape,
    }
    return {
        "summary": summary,
        "skills": rows,
        "global_findings": {
            "top_prompt_openers": top_openers,
        },
    }


@click.group()
def cli():
    """题库与 rubric 内容资产"""
    pass


@cli.command()
@click.option("--only-missing", is_flag=True, help="只显示存在缺口的 skill")
def coverage(only_missing: bool):
    """检查题库与 rubric 覆盖度"""
    graph = load_graph()
    rows = collect_content_coverage(graph)

    def has_gap(row: dict) -> bool:
        return (
            not row["has_question_bank"]
            or not row["has_rubrics"]
            or bool(row["missing_coverages"])
            or bool(row["missing_demo_stage_fits"])
            or row["missing_bridge"]
            or bool(row["missing_rubric_refs"])
        )

    filtered = [row for row in rows if has_gap(row)] if only_missing else rows
    if not filtered:
        console.print("[green]✨ 当前没有内容覆盖缺口[/green]")
        return

    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("技能点")
    table.add_column("题库", justify="center")
    table.add_column("Rubric", justify="center")
    table.add_column("缺失覆盖")
    table.add_column("缺失示范阶段")
    table.add_column("桥接")

    for row in filtered:
        table.add_row(
            row["skill_id"],
            "✓" if row["has_question_bank"] else "✗",
            "✓" if row["has_rubrics"] else "✗",
            ", ".join(row["missing_coverages"]) or "—",
            ", ".join(row["missing_demo_stage_fits"]) or "—",
            "缺" if row["missing_bridge"] else "—",
        )

    console.print(table)

    broken_refs = [row for row in filtered if row["missing_rubric_refs"]]
    if broken_refs:
        console.print("\n[bold red]缺失 rubric 引用：[/bold red]")
        for row in broken_refs:
            console.print(f"   {row['skill_id']}：{', '.join(row['missing_rubric_refs'])}")

    summary = {
        "total_skills": len(rows),
        "skills_with_question_bank": sum(1 for row in rows if row["has_question_bank"]),
        "skills_with_rubrics": sum(1 for row in rows if row["has_rubrics"]),
        "skills_with_gaps": sum(1 for row in rows if has_gap(row)),
    }
    console.print("\n[dim]JSON 输出：[/dim]")
    console.print(json.dumps({"summary": summary, "skills": filtered}, ensure_ascii=False, indent=2))
    console.print()


@cli.command()
@click.option("--only-flagged", is_flag=True, help="只显示存在质量风险的 skill")
def audit(only_flagged: bool):
    """审计题库质量与模板化风险"""
    graph = load_graph()
    report = collect_content_audit(graph)
    rows = report["skills"]
    filtered = [row for row in rows if row["flags"]] if only_flagged else rows

    if not filtered:
        console.print("[green]✨ 当前没有内容质量风险[/green]")
        return

    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("技能点")
    table.add_column("题数", justify="right")
    table.add_column("Family", justify="right")
    table.add_column("题型", justify="right")
    table.add_column("形式", justify="right")
    table.add_column("选择", justify="right")
    table.add_column("反例", justify="right")
    table.add_column("Flags")

    for row in filtered:
        table.add_row(
            row["skill_id"],
            str(row["entry_count"]),
            str(row["family_count"]),
            str(row["question_type_count"]),
            str(row["answer_format_count"]),
            str(row["multiple_choice_count"]),
            str(row["counterexample_count"]),
            ", ".join(flag["code"] for flag in row["flags"]) or "—",
        )

    console.print(table)

    summary = report["summary"]
    console.print("\n[bold]全局摘要：[/bold]")
    console.print(
        f"  - 有质量风险的 skill：{summary['skills_with_quality_flags']}/{summary['total_skills']}"
    )
    console.print(
        f"  - 仍停留在最低题量线（{MIN_RECOMMENDED_ENTRY_COUNT} 题）的 skill：{summary['skills_at_minimum_entry_count']}"
    )
    console.print(
        f"  - rubric 缺少 common_failures 的 skill：{summary['skills_with_blank_common_failures']}"
    )
    console.print(
        f"  - 原文锚点仍偏 section 级的 skill：{summary['skills_with_coarse_anchors']}"
    )
    console.print(
        f"  - 最常复用的题型/形式骨架出现次数：{summary['most_reused_shape_count']}"
    )

    top_openers = report["global_findings"]["top_prompt_openers"]
    if top_openers:
        console.print("\n[bold]高频题干开头：[/bold]")
        for item in top_openers:
            console.print(f"  - {item['opener']}：{item['count']}")

    console.print("\n[dim]JSON 输出：[/dim]")
    console.print(
        json.dumps(
            {
                "summary": summary,
                "skills": filtered,
                "global_findings": report["global_findings"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    console.print()


if __name__ == "__main__":
    cli()
