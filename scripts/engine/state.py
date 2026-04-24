"""
state.py — 学习系统状态管理

核心职责：
- 读写 skill_graph.json（技能图谱的权威数据源）
- 生成人类可读的 .md 视图
- 提供技能点 CRUD 操作
- 检查并解锁满足前置条件的技能点

用法：
    python -m engine.state show                   # 进度概览
    python -m engine.state skill SK-001            # 单个技能点详情
    python -m engine.state update SK-001 mastered  # 更新状态
    python -m engine.state unlock                  # 检查解锁
    python -m engine.state export                  # 生成 progress.md
"""

import json
import sys
from datetime import date, datetime
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

console = Console()

# ─── 数据路径 ───────────────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "data"
SKILL_GRAPH_FILE = DATA_DIR / "skill_graph.json"
CONFIG_FILE = Path(__file__).parent.parent / "config.json"
TEACHER_DIR = Path(__file__).parent.parent.parent / "teacher"

# ─── 状态常量 ───────────────────────────────────────────────

STATUS_ICONS = {
    "locked":           "🔒",
    "unlocked":         "⬜",
    "concept_done":     "🔵",
    "demo_done":        "📘",
    "learning":         "🟡",
    "mastered":         "✅",
    "review_due":       "🔄",
    "long_term":        "💚",
    "needs_validation": "⚠️",
}

STATUS_ORDER = [
    "locked", "unlocked", "concept_done", "demo_done",
    "learning", "mastered", "review_due", "long_term", "needs_validation"
]

DEFAULT_MASTERY_SCORE_BY_STATUS = {
    "locked": 0.0,
    "unlocked": 0.05,
    "concept_done": 0.25,
    "demo_done": 0.45,
    "learning": 0.35,
    "needs_validation": 0.2,
    "mastered": 0.75,
    "review_due": 0.72,
    "long_term": 0.92,
}

# ─── 数据读写 ───────────────────────────────────────────────

def load_config() -> dict:
    """加载系统配置"""
    if not CONFIG_FILE.exists():
        console.print("[red]错误：找不到 config.json[/red]")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_graph() -> dict:
    """加载技能图谱"""
    if not SKILL_GRAPH_FILE.exists():
        console.print("[red]错误：找不到 skill_graph.json[/red]")
        console.print("请先通过 GENERATE.md 流程生成学习系统。")
        sys.exit(1)
    with open(SKILL_GRAPH_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_graph(graph: dict) -> None:
    """保存技能图谱"""
    graph["metadata"]["last_modified"] = date.today().isoformat()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SKILL_GRAPH_FILE, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)


def get_skill(graph: dict, skill_id: str) -> dict:
    """获取单个技能点，不存在则报错退出"""
    skills = graph.get("skills", {})
    if skill_id not in skills:
        console.print(f"[red]错误：技能点 {skill_id} 不存在[/red]")
        available = ", ".join(sorted(skills.keys())[:10])
        console.print(f"可用的技能点：{available}...")
        sys.exit(1)
    return skills[skill_id]


def clamp_mastery_score(score: float) -> float:
    """将掌握度压到 [0, 1] 区间。"""
    return round(min(1.0, max(0.0, float(score))), 4)


def get_mastery_config(config: Optional[dict]) -> dict:
    """获取掌握度配置。"""
    if not config:
        return {}
    return config.get("mastery_score", {})


def get_mastery_score_defaults(config: Optional[dict]) -> dict[str, float]:
    """状态到默认掌握度的映射。"""
    mastery_config = get_mastery_config(config)
    overrides = mastery_config.get("defaults_by_status", {})
    defaults = DEFAULT_MASTERY_SCORE_BY_STATUS.copy()
    defaults.update({key: float(value) for key, value in overrides.items()})
    return defaults


def get_status_mastery_floor(config: Optional[dict], status: str) -> float:
    """获取某状态的默认掌握度基线。"""
    return clamp_mastery_score(get_mastery_score_defaults(config).get(status, 0.0))


def get_mastery_score(skill: dict, config: Optional[dict] = None) -> float:
    """读取技能点掌握度；若缺失则按当前状态回退到默认值。"""
    raw = skill.get("mastery_score")
    if isinstance(raw, (int, float)):
        return clamp_mastery_score(raw)
    return get_status_mastery_floor(config, skill.get("status", "locked"))


def set_mastery_score(skill: dict, config: Optional[dict], score: float) -> float:
    """写入并返回归一化后的掌握度。"""
    normalized = clamp_mastery_score(score)
    skill["mastery_score"] = normalized
    return normalized


def set_mastery_score_from_status(
    skill: dict,
    config: Optional[dict],
    status: Optional[str] = None,
    preserve_higher: bool = False,
) -> float:
    """根据状态设置掌握度，可选择保留更高的既有分数。"""
    target_status = status or skill.get("status", "locked")
    baseline = get_status_mastery_floor(config, target_status)
    current = get_mastery_score(skill, config)
    score = max(current, baseline) if preserve_higher else baseline
    return set_mastery_score(skill, config, score)


# ─── 图谱操作 ───────────────────────────────────────────────

def check_unlockable(graph: dict) -> list[str]:
    """检查哪些 locked 技能点现在可以解锁（所有前置已掌握或长期掌握）"""
    skills = graph["skills"]
    newly_unlocked = []

    for sk_id, sk in skills.items():
        if sk["status"] != "locked":
            continue
        prereqs = sk.get("prerequisites", [])
        if not prereqs:
            # 无前置 → 不应该是 locked，解锁
            sk["status"] = "unlocked"
            newly_unlocked.append(sk_id)
            continue
        all_met = all(
            skills.get(p, {}).get("status") in ("mastered", "long_term", "review_due")
            for p in prereqs
        )
        if all_met:
            sk["status"] = "unlocked"
            newly_unlocked.append(sk_id)

    return newly_unlocked


def count_by_status(graph: dict) -> dict[str, int]:
    """按状态统计技能点数量"""
    counts = {s: 0 for s in STATUS_ORDER}
    for sk in graph["skills"].values():
        status = sk["status"]
        counts[status] = counts.get(status, 0) + 1
    return counts


def get_available_skills(graph: dict) -> list[str]:
    """获取当前可以开始学习的技能点（unlocked 状态）"""
    return [
        sk_id for sk_id, sk in graph["skills"].items()
        if sk["status"] == "unlocked"
    ]


def get_in_progress_skills(graph: dict) -> list[str]:
    """获取正在进行中的技能点（concept_done, demo_done, learning）"""
    active = ("concept_done", "demo_done", "learning")
    return [
        sk_id for sk_id, sk in graph["skills"].items()
        if sk["status"] in active
    ]


# ─── MD 导出 ────────────────────────────────────────────────

def export_progress_md(graph: dict, config: dict) -> str:
    """生成 progress.md 内容"""
    skills = graph["skills"]
    counts = count_by_status(graph)
    total = len(skills)

    lines = [
        "# 学习进度\n",
        f"> 学科：{config.get('subject', '未设置')}",
        f"> 学科分级：{config.get('classification', '?')}类",
        f"> 最后更新：{graph['metadata'].get('last_modified', '—')}\n",
        "## 总体进度\n",
        "| 状态 | 数量 |",
        "|------|------|",
    ]

    for status in STATUS_ORDER:
        icon = STATUS_ICONS.get(status, "?")
        label = {
            "locked": "未解锁",
            "unlocked": "可学习",
            "concept_done": "概念课完成",
            "demo_done": "示范完成",
            "learning": "学习中",
            "mastered": "已掌握",
            "review_due": "复习到期",
            "long_term": "长期掌握",
            "needs_validation": "待验证",
        }.get(status, status)
        count = counts.get(status, 0)
        if count > 0:
            lines.append(f"| {icon} {label} | {count} |")

    lines.append(f"| **总计** | **{total}** |")

    # 可学习的技能点
    available = get_available_skills(graph)
    if available:
        lines.append("\n## 可以开始学习的技能点\n")
        for sk_id in available:
            sk = skills[sk_id]
            lines.append(f"- {sk_id}：{sk['name']}")

    # 进行中的
    in_progress = get_in_progress_skills(graph)
    if in_progress:
        lines.append("\n## 进行中\n")
        for sk_id in in_progress:
            sk = skills[sk_id]
            icon = STATUS_ICONS.get(sk["status"], "?")
            lines.append(f"- {icon} {sk_id}：{sk['name']}")

    # 已掌握（带复习信息）
    mastered = [
        (sk_id, sk) for sk_id, sk in skills.items()
        if sk["status"] in ("mastered", "review_due", "long_term")
    ]
    if mastered:
        lines.append("\n## 已掌握技能点\n")
        lines.append("| 技能点 | 状态 | 掌握日期 | 下次复习 |")
        lines.append("|--------|------|----------|----------|")
        for sk_id, sk in mastered:
            icon = STATUS_ICONS.get(sk["status"], "?")
            mastered_date = sk.get("dates", {}).get("first_mastered", "—")
            next_review = sk.get("review", {}).get("next_due", "—")
            lines.append(f"| {sk_id} {sk['name']} | {icon} | {mastered_date} | {next_review} |")

    return "\n".join(lines)


# ─── CLI ────────────────────────────────────────────────────

@click.group()
def cli():
    """学习系统状态管理"""
    pass


@cli.command()
def show():
    """显示当前进度概览"""
    graph = load_graph()
    config = load_config()
    counts = count_by_status(graph)
    total = len(graph["skills"])
    avg_mastery = (
        sum(get_mastery_score(skill, config) for skill in graph["skills"].values()) / total
        if total > 0 else 0.0
    )

    console.print()
    console.print(f"[bold]📚 {config.get('subject', '学习系统')}[/bold]", style="cyan")
    console.print(f"分级：{config.get('classification', '?')}类  |  "
                  f"强度：{config.get('intensity', '?')}  |  "
                  f"技能点：{total}  |  平均掌握度：{avg_mastery:.0%}")
    console.print()

    table = Table(box=box.SIMPLE)
    table.add_column("状态", style="bold")
    table.add_column("数量", justify="right")
    table.add_column("占比", justify="right")

    for status in STATUS_ORDER:
        count = counts.get(status, 0)
        if count == 0:
            continue
        icon = STATUS_ICONS.get(status, "?")
        pct = f"{count/total*100:.0f}%" if total > 0 else "—"
        table.add_row(f"{icon} {status}", str(count), pct)

    console.print(table)

    # 可学习
    available = get_available_skills(graph)
    if available:
        console.print("\n[green]⬜ 可以开始学习：[/green]")
        for sk_id in available:
            sk = graph["skills"][sk_id]
            console.print(f"   {sk_id}：{sk['name']}")

    # 进行中
    in_progress = get_in_progress_skills(graph)
    if in_progress:
        console.print("\n[yellow]🟡 进行中：[/yellow]")
        for sk_id in in_progress:
            sk = graph["skills"][sk_id]
            icon = STATUS_ICONS.get(sk["status"], "?")
            console.print(f"   {icon} {sk_id}：{sk['name']}")

    console.print()


@cli.command()
@click.argument("skill_id")
def skill(skill_id: str):
    """显示单个技能点详情"""
    graph = load_graph()
    config = load_config()
    sk = get_skill(graph, skill_id)

    icon = STATUS_ICONS.get(sk["status"], "?")
    console.print()
    console.print(f"[bold]{icon} {skill_id}：{sk['name']}[/bold]")
    console.print(f"   描述：{sk.get('description', '—')}")
    console.print(f"   状态：{sk['status']}")
    console.print(f"   掌握度：{get_mastery_score(sk, config):.0%}")
    console.print(f"   复杂度：{sk.get('complexity', '—')}")

    prereqs = sk.get("prerequisites", [])
    console.print(f"   前置：{', '.join(prereqs) if prereqs else '无'}")

    source = sk.get("source", {})
    if source:
        console.print(f"   教材来源：{source.get('textbook', '—')} {source.get('chapter', '')} {source.get('section', '')}")

    dates = sk.get("dates", {})
    if dates:
        console.print(f"   概念课：{dates.get('concept_completed', '—')}")
        console.print(f"   示范课：{dates.get('demo_completed', '—')}")
        console.print(f"   首次掌握：{dates.get('first_mastered', '—')}")

    review = sk.get("review", {})
    if review:
        console.print(f"   复习轮次：{review.get('current_round', 0)}")
        console.print(f"   下次复习：{review.get('next_due', '—')}")
        console.print(f"   FIRe 学分：{review.get('fire_credits', 0):.1f}")

    history = sk.get("practice_history", [])
    if history:
        console.print(f"\n   练习记录（最近5次）：")
        table = Table(box=box.SIMPLE, padding=(0, 1))
        table.add_column("日期")
        table.add_column("准确率", justify="right")
        table.add_column("结果")
        table.add_column("错误类型")
        for rec in history[-5:]:
            icon = "✅" if rec.get("passed") else "❌"
            acc = f"{rec.get('accuracy', 0):.0%}"
            errs = ", ".join(rec.get("errors", [])) or "—"
            table.add_row(rec.get("date", "—"), acc, icon, errs)
        console.print(table)

    console.print()


@cli.command()
@click.argument("skill_id")
@click.argument("new_status", type=click.Choice([
    "unlocked", "concept_done", "demo_done", "learning",
    "mastered", "needs_validation", "locked"
]))
@click.option("--date", "update_date", default=None, help="日期 YYYY-MM-DD，默认今天")
def update(skill_id: str, new_status: str, update_date: Optional[str]):
    """更新技能点状态"""
    graph = load_graph()
    config = load_config()
    sk = get_skill(graph, skill_id)

    old_status = sk["status"]
    d = update_date or date.today().isoformat()

    # 更新状态
    sk["status"] = new_status

    # 根据状态更新对应日期
    if "dates" not in sk:
        sk["dates"] = {}

    if new_status == "concept_done":
        sk["dates"]["concept_completed"] = d
        set_mastery_score_from_status(sk, config, new_status, preserve_higher=True)
    elif new_status == "demo_done":
        sk["dates"]["demo_completed"] = d
        set_mastery_score_from_status(sk, config, new_status, preserve_higher=True)
    elif new_status == "mastered":
        if "first_mastered" not in sk["dates"]:
            sk["dates"]["first_mastered"] = d
        sk["dates"]["last_practiced"] = d
        # 设置首次复习
        if "review" not in sk:
            sk["review"] = {}
        schedule = config.get("review_schedule", [1, 3, 7, 21, 60, 90])
        sk["review"]["current_round"] = 0
        from datetime import timedelta
        next_due = date.fromisoformat(d) + timedelta(days=schedule[0])
        sk["review"]["next_due"] = next_due.isoformat()
        sk["review"]["fire_credits"] = 0.0
        set_mastery_score_from_status(sk, config, new_status, preserve_higher=True)
    else:
        set_mastery_score_from_status(sk, config, new_status)

    # 检查解锁
    newly_unlocked = check_unlockable(graph)
    for unlocked_id in newly_unlocked:
        set_mastery_score_from_status(graph["skills"][unlocked_id], config, "unlocked", preserve_higher=True)

    save_graph(graph)

    console.print(f"[green]✓[/green] {skill_id} 状态：{old_status} → {new_status}")
    console.print(f"   掌握度：{get_mastery_score(sk, config):.0%}")
    if newly_unlocked:
        console.print(f"[cyan]🔓 新解锁：{', '.join(newly_unlocked)}[/cyan]")


@cli.command()
def unlock():
    """检查并解锁满足前置条件的技能点"""
    graph = load_graph()
    config = load_config()
    newly_unlocked = check_unlockable(graph)

    if newly_unlocked:
        for sk_id in newly_unlocked:
            set_mastery_score_from_status(graph["skills"][sk_id], config, "unlocked", preserve_higher=True)
        save_graph(graph)
        console.print(f"[green]🔓 新解锁 {len(newly_unlocked)} 个技能点：[/green]")
        for sk_id in newly_unlocked:
            sk = graph["skills"][sk_id]
            console.print(f"   ⬜ {sk_id}：{sk['name']}（掌握度 {get_mastery_score(sk, config):.0%}）")
    else:
        console.print("[dim]没有新的可解锁技能点[/dim]")


@cli.command()
def export():
    """生成 progress.md"""
    graph = load_graph()
    config = load_config()

    md_content = export_progress_md(graph, config)

    # 写到 teacher/ 目录
    output_path = TEACHER_DIR / "progress.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    console.print(f"[green]✓[/green] 已生成 {output_path}")


@cli.command()
@click.argument("skill_id")
@click.argument("accuracy", type=float)
@click.option("--errors", default="", help="逗号分隔的错误类型")
def record(skill_id: str, accuracy: float, errors: str):
    """记录一次练习结果（供其他脚本调用）"""
    graph = load_graph()
    config = load_config()
    sk = get_skill(graph, skill_id)

    error_list = [e.strip() for e in errors.split(",") if e.strip()]

    # 掌握判定
    intensity = config.get("intensity", "medium")
    threshold = config.get("mastery_threshold", {})
    if isinstance(threshold, dict):
        threshold = threshold.get(intensity, 0.8)

    passed = accuracy >= threshold
    mastery_score_before = get_mastery_score(sk, config)
    mastery_score_after = set_mastery_score(sk, config, mastery_score_before)

    # 追加练习记录
    if "practice_history" not in sk:
        sk["practice_history"] = []
    sk["practice_history"].append({
        "date": date.today().isoformat(),
        "accuracy": accuracy,
        "passed": passed,
        "type": "practice",
        "errors": error_list,
        "mastery_score_before": mastery_score_before,
        "mastery_score_after": mastery_score_after,
    })

    # 更新连续失败计数
    if passed:
        sk["consecutive_failures"] = 0
    else:
        sk["consecutive_failures"] = sk.get("consecutive_failures", 0) + 1

    # 更新日期
    if "dates" not in sk:
        sk["dates"] = {}
    sk["dates"]["last_practiced"] = date.today().isoformat()

    save_graph(graph)

    result_icon = "✅" if passed else "❌"
    console.print(f"{result_icon} {skill_id} 准确率 {accuracy:.0%}，{'通过' if passed else '未通过'}")
    console.print(f"   掌握度：{mastery_score_before:.0%} → {mastery_score_after:.0%}")

    return {
        "passed": passed,
        "accuracy": accuracy,
        "mastery_score_before": mastery_score_before,
        "mastery_score_after": mastery_score_after,
    }


if __name__ == "__main__":
    cli()
