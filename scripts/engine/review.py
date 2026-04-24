"""
review.py — 间隔复习调度 + 最简 FIRe

核心职责：
- 计算哪些技能点复习到期
- 处理 FIRe 隐式复习学分（单向、直接前置、固定权重）
- 完成复习后更新下次复习时间
- 生成复习队列

用法：
    python -m engine.review due                  # 今日到期复习
    python -m engine.review schedule SK-001       # 某技能点复习时间表
    python -m engine.review complete SK-001 0.85  # 记录复习结果
    python -m engine.review fire                  # FIRe 学分概览
"""

import json
import sys
from datetime import date, timedelta
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

# 复用 state.py 的数据层
from engine.state import (
    load_config, load_graph, save_graph, get_skill,
    STATUS_ICONS, get_mastery_score, set_mastery_score,
    set_mastery_score_from_status, get_status_mastery_floor,
)

console = Console()


# ─── 复习调度核心逻辑 ───────────────────────────────────────

def get_review_interval(config: dict, review_round: int) -> int:
    """根据复习轮次获取间隔天数"""
    schedule = config.get("review_schedule", [1, 3, 7, 21, 60, 90])
    if review_round < len(schedule):
        return schedule[review_round]
    return schedule[-1]  # 最后一个间隔持续使用


def get_review_question_count(review_round: int) -> int:
    """前两轮 4 题，之后固定 5 题。"""
    return 4 if review_round < 2 else 5


def get_due_reviews(graph: dict, config: dict, today: Optional[date] = None) -> list[dict]:
    """获取今日到期的复习列表（不扣除 FIRe 学分）"""
    if today is None:
        today = date.today()

    due = []
    for sk_id, sk in graph["skills"].items():
        if sk["status"] not in ("mastered", "review_due", "long_term"):
            continue
        review = sk.get("review", {})
        next_due = review.get("next_due")
        if not next_due:
            continue
        due_date = date.fromisoformat(next_due)
        if due_date <= today:
            days_overdue = (today - due_date).days
            due.append({
                "skill_id": sk_id,
                "name": sk["name"],
                "due_date": next_due,
                "days_overdue": days_overdue,
                "review_round": review.get("current_round", 0),
                "fire_credits": review.get("fire_credits", 0.0),
            })

    # 最过期的排前面
    due.sort(key=lambda x: x["days_overdue"], reverse=True)
    return due


def split_due_reviews_with_fire(
    graph: dict, config: dict, today: Optional[date] = None
) -> tuple[list[dict], list[dict]]:
    """纯函数：返回今日需复习列表和会被 FIRe 延后的列表。"""
    due = get_due_reviews(graph, config, today)

    fire_config = config.get("fire", {})
    if not fire_config.get("enabled", True):
        return due, []

    credits_needed = fire_config.get("credits_per_review_equivalent", 2.0)

    filtered = []
    delayed = []
    for item in due:
        sk = graph["skills"][item["skill_id"]]
        review = sk.get("review", {})
        review_round = review.get("current_round", 0)

        # FIRe 只对复习轮次 >= 3 的技能点生效
        if review_round < 3:
            filtered.append({**item, "delayed_by_fire": False})
            continue

        fire_credits = review.get("fire_credits", 0.0)
        if fire_credits >= credits_needed:
            # 隐式学分足够 → 延迟此次复习
            max_delay = fire_config.get("max_delay_factor", 0.5)
            current_interval = get_review_interval(config, review_round)
            delay_days = int(current_interval * max_delay)

            new_due = date.fromisoformat(item["due_date"]) + timedelta(days=delay_days)
            delayed.append({
                **item,
                "delayed_by_fire": True,
                "new_due_date": new_due.isoformat(),
                "delay_days": delay_days,
                "credits_consumed": credits_needed,
            })
        else:
            filtered.append({**item, "delayed_by_fire": False})

    return filtered, delayed


def get_due_reviews_with_fire(graph: dict, config: dict, today: Optional[date] = None) -> list[dict]:
    """获取今日到期的复习列表，扣除 FIRe 学分后的纯预览结果。"""
    filtered, _ = split_due_reviews_with_fire(graph, config, today)
    return filtered


def apply_fire_delays(graph: dict, delayed_reviews: list[dict]) -> None:
    """显式应用 FIRe 延后，避免在查询命令中隐式写状态。"""
    for item in delayed_reviews:
        sk = graph["skills"].get(item["skill_id"])
        if not sk:
            continue
        review = sk.setdefault("review", {})
        review["next_due"] = item["new_due_date"]
        remaining_credits = review.get("fire_credits", 0.0) - item.get("credits_consumed", 0.0)
        review["fire_credits"] = max(0.0, remaining_credits)


def award_fire_credits(graph: dict, config: dict, skill_id: str, passed: bool) -> list[dict]:
    """
    练习/复习 skill_id 后，给其直接前置技能点发放 FIRe 学分。
    最简实现：单向、直接前置、固定权重。
    
    返回获得学分的技能点列表。
    """
    fire_config = config.get("fire", {})
    if not fire_config.get("enabled", True):
        return []
    if not passed:
        return []

    sk = graph["skills"].get(skill_id, {})
    prereqs = sk.get("prerequisites", [])
    default_weight = fire_config.get("default_weight", 1.0)

    awarded = []
    for prereq_id in prereqs:
        prereq = graph["skills"].get(prereq_id)
        if not prereq:
            continue
        # 只给已掌握/长期掌握的前置技能点加学分
        if prereq["status"] not in ("mastered", "review_due", "long_term"):
            continue
        if "review" not in prereq:
            continue

        credit = 0.5 * default_weight  # 每次通过给 0.5 * weight
        prereq["review"]["fire_credits"] = prereq["review"].get("fire_credits", 0.0) + credit
        awarded.append({
            "skill_id": prereq_id,
            "name": prereq["name"],
            "credit": credit,
            "total": prereq["review"]["fire_credits"],
        })

    return awarded


def complete_review(graph: dict, config: dict, skill_id: str, accuracy: float) -> dict:
    """
    完成一次复习，更新状态。
    
    返回结果字典。
    """
    sk = get_skill(graph, skill_id)
    review = sk.get("review", {})
    current_round = review.get("current_round", 0)

    # 判定通过
    intensity = config.get("intensity", "medium")
    threshold = config.get("mastery_threshold", {})
    if isinstance(threshold, dict):
        threshold = threshold.get(intensity, 0.8)

    # 复习的通过标准是掌握标准的 80%
    review_threshold = threshold * 0.8
    passed = accuracy >= review_threshold

    result = {
        "skill_id": skill_id,
        "accuracy": accuracy,
        "passed": passed,
        "review_round": current_round,
    }
    mastery_score_before = get_mastery_score(sk, config)

    # 记录练习历史
    if "practice_history" not in sk:
        sk["practice_history"] = []
    review_question_count = get_review_question_count(current_round)
    correct_count = int(round(accuracy * review_question_count))
    history_entry = {
        "date": date.today().isoformat(),
        "accuracy": accuracy,
        "passed": passed,
        "type": "review",
        "errors": [],
        "review_round": current_round,
        "total_questions": review_question_count,
        "correct_count": correct_count,
        "planned_questions": review_question_count,
        "completed_questions": review_question_count,
        "question_types": [],
        "question_type_map": {},
        "source_skills": [skill_id],
        "source_skill_map": {},
        "used_exercises": [],
        "termination_reason": "completed",
        "early_terminated": False,
        "mastery_score_before": mastery_score_before,
    }
    sk["practice_history"].append(history_entry)

    if passed:
        # 复习通过 → 下一轮
        new_round = current_round + 1
        interval = get_review_interval(config, new_round)
        next_due = date.today() + timedelta(days=interval)

        sk["consecutive_failures"] = 0
        review["current_round"] = new_round
        review["next_due"] = next_due.isoformat()
        review["fire_credits"] = 0.0  # 复习后清零 FIRe 学分

        # 长期掌握判定
        long_term_after = config.get("long_term_mastery_after_round", 4)
        if new_round >= long_term_after:
            sk["status"] = "long_term"
            result["new_status"] = "long_term"
        else:
            sk["status"] = "mastered"
            result["new_status"] = "mastered"

        review_cfg = config.get("mastery_score", {}).get("review", {})
        mastery_gain = (
            float(review_cfg.get("pass_base_gain", 0.08))
            + accuracy * float(review_cfg.get("pass_accuracy_weight", 0.1))
            + min(new_round, long_term_after)
            * float(review_cfg.get("pass_round_bonus", 0.015))
        )
        mastery_target_status = "long_term" if result["new_status"] == "long_term" else "mastered"
        mastery_score_after = set_mastery_score(
            sk,
            config,
            max(
                mastery_score_before + mastery_gain,
                get_status_mastery_floor(config, mastery_target_status),
            ),
        )

        result["next_review"] = next_due.isoformat()
        result["new_round"] = new_round

        # 发放 FIRe 学分
        fire_awarded = award_fire_credits(graph, config, skill_id, True)
        result["fire_awarded"] = fire_awarded

    else:
        # 复习未通过 → 回退到 learning
        sk["status"] = "learning"
        review["current_round"] = max(0, current_round - 1)
        review["fire_credits"] = 0.0
        sk["consecutive_failures"] = sk.get("consecutive_failures", 0) + 1
        review_cfg = config.get("mastery_score", {}).get("review", {})
        mastery_penalty = (
            float(review_cfg.get("fail_base_penalty", 0.15))
            + (current_round + 1) * float(review_cfg.get("fail_round_penalty", 0.03))
        )
        mastery_score_after = set_mastery_score(
            sk,
            config,
            min(
                mastery_score_before - mastery_penalty,
                get_status_mastery_floor(config, "mastered") - 0.01,
            ),
        )

        result["new_status"] = "learning"
        result["message"] = "复习未通过，需要重新练习"
        result["fire_awarded"] = []

        # 检查前置技能稳定性（规则三）
        prereqs = sk.get("prerequisites", [])
        needs_check = []
        for prereq_id in prereqs:
            prereq = graph["skills"].get(prereq_id, {})
            history = prereq.get("practice_history", [])
            if history:
                last_accuracy = history[-1].get("accuracy", 1.0)
                if last_accuracy < 0.8:
                    prereq["status"] = "needs_validation"
                    set_mastery_score_from_status(
                        prereq, config, "needs_validation", preserve_higher=False
                    )
                    needs_check.append(prereq_id)
        if needs_check:
            result["prerequisites_flagged"] = needs_check

    sk["review"] = review
    sk["dates"] = sk.get("dates", {})
    sk["dates"]["last_practiced"] = date.today().isoformat()
    history_entry["mastery_score_after"] = mastery_score_after
    result["mastery_score_before"] = mastery_score_before
    result["mastery_score_after"] = mastery_score_after

    return result


# ─── CLI ────────────────────────────────────────────────────

@click.group()
def cli():
    """间隔复习调度"""
    pass


@cli.command()
@click.option("--fire/--no-fire", default=True, help="是否扣除 FIRe 学分")
@click.option("--apply-fire", is_flag=True, help="显式应用 FIRe 延后并写回图谱")
def due(fire: bool, apply_fire: bool):
    """列出今日到期复习"""
    graph = load_graph()
    config = load_config()
    delayed_reviews = []

    if fire:
        reviews, delayed_reviews = split_due_reviews_with_fire(graph, config)
        if apply_fire and delayed_reviews:
            apply_fire_delays(graph, delayed_reviews)
            save_graph(graph)
    else:
        reviews = get_due_reviews(graph, config)

    if not reviews and not delayed_reviews:
        console.print("[green]✨ 今日无复习到期[/green]")
        return

    if reviews:
        console.print(f"\n[bold]🔄 今日复习到期：{len(reviews)} 个技能点[/bold]\n")

        table = Table(box=box.ROUNDED)
        table.add_column("技能点", style="bold")
        table.add_column("名称")
        table.add_column("复习轮次", justify="center")
        table.add_column("过期天数", justify="right", style="red")
        table.add_column("FIRe 学分", justify="right")

        for r in reviews:
            overdue = f"+{r['days_overdue']}天" if r["days_overdue"] > 0 else "今天"
            fire_str = f"{r['fire_credits']:.1f}"
            table.add_row(
                r["skill_id"],
                r["name"],
                f"第{r['review_round']+1}次",
                overdue,
                fire_str,
            )

        console.print(table)
        console.print()
    else:
        console.print("[green]✨ 今日无需要立即复习的技能点[/green]\n")

    if delayed_reviews:
        mode_label = "已应用" if apply_fire else "预览"
        console.print(f"[bold]🔥 FIRe 延后（{mode_label}）：{len(delayed_reviews)} 个技能点[/bold]\n")
        table = Table(box=box.SIMPLE)
        table.add_column("技能点", style="bold")
        table.add_column("名称")
        table.add_column("原到期")
        table.add_column("新到期")
        table.add_column("消耗学分", justify="right")

        for item in delayed_reviews:
            table.add_row(
                item["skill_id"],
                item["name"],
                item["due_date"],
                item["new_due_date"],
                f"{item['credits_consumed']:.1f}",
            )

        console.print(table)
        if not apply_fire:
            console.print("\n[dim]提示：当前仅为预览，若要写回图谱，请加 --apply-fire[/dim]")
        console.print()


@cli.command()
@click.argument("skill_id")
def schedule(skill_id: str):
    """显示某技能点的复习时间表"""
    graph = load_graph()
    config = load_config()
    sk = get_skill(graph, skill_id)

    review = sk.get("review", {})
    sched = config.get("review_schedule", [1, 3, 7, 21, 60, 90])

    icon = STATUS_ICONS.get(sk["status"], "?")
    console.print(f"\n[bold]{icon} {skill_id}：{sk['name']} 复习时间表[/bold]\n")

    current_round = review.get("current_round", 0)
    mastered_date = sk.get("dates", {}).get("first_mastered")

    table = Table(box=box.SIMPLE)
    table.add_column("轮次")
    table.add_column("间隔")
    table.add_column("到期日期")
    table.add_column("状态")

    for i, days in enumerate(sched):
        status_str = ""
        due_date = "—"
        if mastered_date:
            base = date.fromisoformat(mastered_date)
            cumulative = sum(sched[:i+1])
            due_date = (base + timedelta(days=cumulative)).isoformat()

        if i < current_round:
            status_str = "[green]✓ 已完成[/green]"
        elif i == current_round:
            next_due = review.get("next_due", "—")
            status_str = f"[yellow]→ 下次 ({next_due})[/yellow]"
        else:
            status_str = "[dim]待定[/dim]"

        table.add_row(
            f"第{i+1}次",
            f"+{days}天",
            due_date,
            status_str,
        )

    console.print(table)
    console.print(f"\n   FIRe 学分累积：{review.get('fire_credits', 0):.1f}")
    console.print()


@cli.command("complete")
@click.argument("skill_id")
@click.argument("accuracy", type=float)
def complete_cmd(skill_id: str, accuracy: float):
    """记录复习结果"""
    graph = load_graph()
    config = load_config()

    result = complete_review(graph, config, skill_id, accuracy)
    save_graph(graph)

    if result["passed"]:
        console.print(f"[green]✅ {skill_id} 复习通过[/green]（准确率 {accuracy:.0%}）")
        console.print(
            f"   掌握度：{result['mastery_score_before']:.0%} → {result['mastery_score_after']:.0%}"
        )
        console.print(f"   下次复习：{result.get('next_review', '—')}")
        if result.get("new_status") == "long_term":
            console.print(f"   [bold green]🎉 进入长期掌握！[/bold green]")
        fire = result.get("fire_awarded", [])
        if fire:
            console.print(f"   FIRe 学分发放：")
            for f in fire:
                console.print(f"     {f['skill_id']}：+{f['credit']:.1f}（累计 {f['total']:.1f}）")
    else:
        console.print(f"[red]❌ {skill_id} 复习未通过[/red]（准确率 {accuracy:.0%}）")
        console.print(
            f"   掌握度：{result['mastery_score_before']:.0%} → {result['mastery_score_after']:.0%}"
        )
        console.print(f"   状态回退为 🟡 学习中，需要重新练习")
        flagged = result.get("prerequisites_flagged", [])
        if flagged:
            console.print(f"   [yellow]⚠️ 前置技能需验证：{', '.join(flagged)}[/yellow]")


@cli.command()
def fire():
    """显示 FIRe 学分概览"""
    graph = load_graph()
    config = load_config()

    fire_config = config.get("fire", {})
    if not fire_config.get("enabled", True):
        console.print("[dim]FIRe 机制未启用[/dim]")
        return

    credits_needed = fire_config.get("credits_per_review_equivalent", 2.0)

    console.print(f"\n[bold]🔥 FIRe 隐式复习学分概览[/bold]")
    console.print(f"   等效一次显式复习所需学分：{credits_needed:.1f}\n")

    table = Table(box=box.SIMPLE)
    table.add_column("技能点")
    table.add_column("名称")
    table.add_column("复习轮次", justify="center")
    table.add_column("FIRe 学分", justify="right")
    table.add_column("进度", justify="right")

    has_data = False
    for sk_id, sk in graph["skills"].items():
        if sk["status"] not in ("mastered", "review_due", "long_term"):
            continue
        review = sk.get("review", {})
        credits = review.get("fire_credits", 0.0)
        if credits > 0:
            has_data = True
            progress = f"{credits/credits_needed*100:.0f}%"
            table.add_row(
                sk_id, sk["name"],
                f"第{review.get('current_round', 0)+1}次",
                f"{credits:.1f}",
                progress,
            )

    if has_data:
        console.print(table)
    else:
        console.print("[dim]   暂无 FIRe 学分记录[/dim]")
    console.print()


if __name__ == "__main__":
    cli()
