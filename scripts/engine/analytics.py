"""
analytics.py — 学习数据分析

核心职责：
- 生成学习趋势报告
- 错误类型分布分析
- 复习效果统计
- 系统性薄弱警报
- 输出下一步学习建议

用法：
    python -m engine.analytics report     # 完整报告
    python -m engine.analytics today      # 今日建议
    python -m engine.analytics errors     # 错误分布
    python -m engine.analytics speed      # 学习速度趋势
    python -m engine.analytics alerts     # 系统性薄弱警报
"""

import json
import sys
from collections import Counter
from datetime import date, timedelta
from itertools import combinations
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

from engine.review import get_due_reviews_with_fire
from engine.state import load_config, load_graph, STATUS_ICONS, get_mastery_score

console = Console()

TEACHER_DIR = Path(__file__).parent.parent.parent / "teacher"

ACTIVE_STATUSES = ("needs_validation", "learning", "demo_done", "concept_done")
REVIEWABLE_STATUSES = ("mastered", "review_due", "long_term")
CONFUSION_ERROR_TYPES = {
    "conceptual", "概念混淆",
    "boundary", "边界混淆",
}
QUESTION_FOCUS_MAP = {
    "conceptual": {
        "label": "概念辨析",
        "message": "最近错误以概念混淆为主，下一轮应增加概念辨析题，先压缩新概念引入。",
    },
    "概念混淆": {
        "label": "概念辨析",
        "message": "最近错误以概念混淆为主，下一轮应增加概念辨析题，先压缩新概念引入。",
    },
    "boundary": {
        "label": "边界/反例",
        "message": "最近边界判断错误偏多，下一轮应增加反例构造和概念边界题。",
    },
    "边界混淆": {
        "label": "边界/反例",
        "message": "最近边界判断错误偏多，下一轮应增加反例构造和概念边界题。",
    },
    "retrieval": {
        "label": "提取回忆",
        "message": "最近提取失败偏多，下一轮应缩短复习间隔并增加不看笔记的回忆题。",
    },
    "提取失败": {
        "label": "提取回忆",
        "message": "最近提取失败偏多，下一轮应缩短复习间隔并增加不看笔记的回忆题。",
    },
    "procedural": {
        "label": "流程复现",
        "message": "最近流程性错误偏多，下一轮应增加按步骤复现和操作顺序题。",
    },
    "transfer": {
        "label": "迁移综合",
        "message": "最近迁移错误偏多，下一轮应增加跨节综合和场景迁移题。",
    },
}


# ─── 统计函数 ───────────────────────────────────────────────

def collect_all_sessions(graph: dict) -> list[dict]:
    """从所有技能点收集练习记录"""
    sessions = []
    for sk_id, sk in graph["skills"].items():
        for h in sk.get("practice_history", []):
            sessions.append({
                "skill_id": sk_id,
                "name": sk["name"],
                **h,
            })
    sessions.sort(key=lambda x: x.get("date", ""))
    return sessions


def calc_error_distribution(sessions: list[dict]) -> dict[str, int]:
    """计算所有练习的错误类型分布"""
    counter = Counter()
    for s in sessions:
        # 优先用 error_counts（精确计数）
        if "error_counts" in s:
            for err_type, count in s["error_counts"].items():
                counter[err_type] += count
        else:
            for err in s.get("errors", []):
                counter[err] += 1
    return dict(counter.most_common())


def calc_answer_format_stats(sessions: list[dict]) -> dict[str, dict[str, float]]:
    """统计不同作答形式的题量和准确率。"""
    stats: dict[str, dict[str, float]] = {}
    for session in sessions:
        counts = session.get("answer_format_counts", {})
        correct_counts = session.get("answer_format_correct_counts", {})
        for answer_format, total in counts.items():
            if answer_format not in stats:
                stats[answer_format] = {"total": 0, "correct": 0}
            stats[answer_format]["total"] += total
            stats[answer_format]["correct"] += correct_counts.get(answer_format, 0)

    for answer_format, item in stats.items():
        total = item["total"]
        item["accuracy"] = item["correct"] / total if total > 0 else 0.0
    return dict(
        sorted(
            stats.items(),
            key=lambda pair: (-pair[1]["total"], pair[0]),
        )
    )


def get_recent_sessions(sessions: list[dict], limit: int = 5) -> list[dict]:
    """获取最近若干次练习/复习记录。"""
    filtered = [
        session for session in sessions
        if session.get("type") in ("practice", "review")
    ]
    return filtered[-limit:]


def calc_review_effectiveness(graph: dict, config: dict) -> dict:
    """按复习轮次统计通过率"""
    schedule = config.get("review_schedule", [1, 3, 7, 21, 60, 90])
    stats = {i: {"total": 0, "passed": 0} for i in range(len(schedule))}

    for sk in graph["skills"].values():
        for h in sk.get("practice_history", []):
            if h.get("type") != "review":
                continue
            recorded_round = h.get("review_round")
            if recorded_round is not None:
                round_idx = min(recorded_round, len(schedule) - 1)
            else:
                # 兼容旧记录：用当前 review_round 粗略回推
                round_num = sk.get("review", {}).get("current_round", 0)
                if h.get("passed"):
                    round_idx = min(round_num, len(schedule) - 1)
                else:
                    round_idx = min(round_num + 1, len(schedule) - 1)

            if round_idx in stats:
                stats[round_idx]["total"] += 1
                if h.get("passed"):
                    stats[round_idx]["passed"] += 1

    return stats


def calc_confusion_pairs(
    sessions: list[dict], graph: dict, limit: int = 5
) -> list[dict]:
    """
    基于显式 source_skills 和 conceptual/boundary 错误，推断容易混淆的技能点对。
    这是启发式统计，不是逐题精确归因。
    """
    pair_counter = Counter()
    latest_dates: dict[tuple[str, str], str] = {}

    for session in sessions:
        source_skills = sorted(set(session.get("source_skills", [])))
        if len(source_skills) < 2:
            continue

        error_counts = session.get("error_counts", {})
        confusion_weight = sum(
            count for err_type, count in error_counts.items()
            if err_type in CONFUSION_ERROR_TYPES
        )
        if confusion_weight <= 0:
            confusion_weight = sum(
                1 for err_type in session.get("errors", [])
                if err_type in CONFUSION_ERROR_TYPES
            )
        if confusion_weight <= 0:
            continue

        session_date = session.get("date", "")
        for pair in combinations(source_skills, 2):
            pair_counter[pair] += confusion_weight
            previous_date = latest_dates.get(pair, "")
            if session_date > previous_date:
                latest_dates[pair] = session_date

    results = []
    for pair, count in pair_counter.most_common(limit):
        left, right = pair
        results.append({
            "skills": [left, right],
            "names": [
                graph["skills"].get(left, {}).get("name", left),
                graph["skills"].get(right, {}).get("name", right),
            ],
            "count": count,
            "latest_date": latest_dates.get(pair, "—"),
        })
    return results


def calc_question_focus(sessions: list[dict], window: int = 5) -> dict:
    """根据最近若干次记录，给出下一轮题型侧重点。"""
    recent_sessions = get_recent_sessions(sessions, limit=window)
    recent_errors = calc_error_distribution(recent_sessions)

    if not recent_errors:
        return {
            "error_type": None,
            "label": "维持混合覆盖",
            "message": "最近几次没有明显错误集中，继续保持多题型覆盖即可。",
            "window": len(recent_sessions),
            "count": 0,
        }

    top_error, top_count = next(iter(recent_errors.items()))
    focus = QUESTION_FOCUS_MAP.get(
        top_error,
        {
            "label": "基础纠错",
            "message": f"最近 `{top_error}` 错误最多，下一轮应围绕这一类错误做定向练习。",
        },
    )
    return {
        "error_type": top_error,
        "label": focus["label"],
        "message": focus["message"],
        "window": len(recent_sessions),
        "count": top_count,
    }


def calc_speed_trend(graph: dict, batch_size: int = 5) -> list[dict]:
    """每 batch_size 个掌握的技能点为一批，计算学习速度趋势"""
    mastered = []
    for sk_id, sk in graph["skills"].items():
        if sk["status"] in ("mastered", "long_term", "review_due"):
            history = sk.get("practice_history", [])
            practice_count = sum(1 for h in history if h.get("type", "practice") == "practice")
            avg_accuracy = sum(h.get("accuracy", 0) for h in history) / len(history) if history else 0

            mastered_date = sk.get("dates", {}).get("first_mastered")
            concept_date = sk.get("dates", {}).get("concept_completed")

            days_to_master = None
            if mastered_date and concept_date:
                d1 = date.fromisoformat(concept_date)
                d2 = date.fromisoformat(mastered_date)
                days_to_master = (d2 - d1).days

            mastered.append({
                "skill_id": sk_id,
                "practice_count": practice_count,
                "avg_accuracy": avg_accuracy,
                "days_to_master": days_to_master,
                "mastered_date": mastered_date,
            })

    mastered.sort(key=lambda x: x.get("mastered_date") or "9999")

    # 分批
    batches = []
    for i in range(0, len(mastered), batch_size):
        batch = mastered[i:i + batch_size]
        if not batch:
            continue
        avg_practice = sum(m["practice_count"] for m in batch) / len(batch)
        avg_acc = sum(m["avg_accuracy"] for m in batch) / len(batch)
        avg_days = None
        days_list = [m["days_to_master"] for m in batch if m["days_to_master"] is not None]
        if days_list:
            avg_days = sum(days_list) / len(days_list)

        batches.append({
            "batch": i // batch_size + 1,
            "skills": [m["skill_id"] for m in batch],
            "avg_practice_count": avg_practice,
            "avg_accuracy": avg_acc,
            "avg_days_to_master": avg_days,
        })

    # 趋势标注
    for i, batch in enumerate(batches):
        if i == 0:
            batch["trend"] = "—"
        else:
            prev = batches[i - 1]["avg_practice_count"]
            curr = batch["avg_practice_count"]
            if curr < prev * 0.85:
                batch["trend"] = "🟢 加速"
            elif curr > prev * 1.15:
                batch["trend"] = "🔴 减速"
            else:
                batch["trend"] = "🟡 稳定"

    return batches


def summarize_review_pressure(
    graph: dict, config: dict, today: Optional[date] = None
) -> dict:
    """汇总当前复习压力，包括到期和即将到期。"""
    if today is None:
        today = date.today()

    due_reviews = get_due_reviews_with_fire(graph, config, today=today)
    soon_reviews = []
    for sk_id, sk in graph["skills"].items():
        if sk.get("status") not in REVIEWABLE_STATUSES:
            continue
        review = sk.get("review", {})
        next_due = review.get("next_due")
        if not next_due:
            continue
        due_date = date.fromisoformat(next_due)
        days_until = (due_date - today).days
        if 0 < days_until <= 3:
            soon_reviews.append({
                "skill_id": sk_id,
                "name": sk["name"],
                "due_date": next_due,
                "days_until": days_until,
                "review_round": review.get("current_round", 0),
            })

    soon_reviews.sort(key=lambda item: item["days_until"])
    overdue_count = sum(1 for item in due_reviews if item.get("days_overdue", 0) > 0)

    return {
        "due_count": len(due_reviews),
        "overdue_count": overdue_count,
        "due_reviews": due_reviews,
        "soon_count": len(soon_reviews),
        "soon_reviews": soon_reviews,
    }


def _sorted_skill_candidates(
    graph: dict, config: dict, statuses: tuple[str, ...]
) -> list[dict]:
    status_rank = {
        "needs_validation": 0,
        "learning": 1,
        "demo_done": 2,
        "concept_done": 3,
        "unlocked": 4,
    }
    items = []
    for sk_id, sk in graph["skills"].items():
        if sk.get("status") not in statuses:
            continue
        items.append({
            "skill_id": sk_id,
            "name": sk.get("name", sk_id),
            "status": sk.get("status"),
            "mastery_score": get_mastery_score(sk, config),
        })
    items.sort(
        key=lambda item: (
            status_rank.get(item["status"], 99),
            item["mastery_score"],
            item["skill_id"],
        )
    )
    return items


def recommend_next_actions(
    graph: dict,
    config: dict,
    sessions: Optional[list[dict]] = None,
    today: Optional[date] = None,
) -> dict:
    """把统计结果压成下一步动作建议。"""
    if sessions is None:
        sessions = collect_all_sessions(graph)
    if today is None:
        today = date.today()

    alerts = check_alerts(graph, config, sessions)
    high_alerts = [alert for alert in alerts if alert.get("severity") == "high"]
    review_summary = summarize_review_pressure(graph, config, today=today)
    confusion_pairs = calc_confusion_pairs(sessions, graph)
    question_focus = calc_question_focus(sessions)
    active_skills = _sorted_skill_candidates(graph, config, ACTIVE_STATUSES)
    available_skills = _sorted_skill_candidates(graph, config, ("unlocked",))
    needs_validation = [skill for skill in active_skills if skill["status"] == "needs_validation"]

    primary_action = None
    secondary_action = None

    if review_summary["due_count"] > 0:
        due_ids = [item["skill_id"] for item in review_summary["due_reviews"][:3]]
        if review_summary["overdue_count"] > 0:
            message = (
                f"先清复习队列。当前有 {review_summary['due_count']} 个到期复习，"
                f"其中 {review_summary['overdue_count']} 个已经过期。"
            )
        else:
            message = f"先做今日复习。当前有 {review_summary['due_count']} 个技能点到期。"
        primary_action = {
            "type": "review_due",
            "label": "先清复习队列",
            "message": message,
            "skill_ids": due_ids,
            "block_new_skills": True,
        }
        if needs_validation:
            secondary_action = {
                "type": "validate_prerequisites",
                "label": "随后验证前置技能",
                "message": (
                    f"复习后优先处理待验证前置技能："
                    f"{', '.join(skill['skill_id'] for skill in needs_validation[:3])}。"
                ),
                "skill_ids": [skill["skill_id"] for skill in needs_validation[:3]],
            }
        elif active_skills:
            follow_up = active_skills[0]
            secondary_action = {
                "type": "resume_in_progress",
                "label": f"随后继续 {follow_up['skill_id']}",
                "message": (
                    f"清完复习后继续进行中的技能点 {follow_up['skill_id']}，"
                    f"当前状态为 {follow_up['status']}，掌握度 {follow_up['mastery_score']:.0%}。"
                ),
                "skill_ids": [follow_up["skill_id"]],
            }
    elif needs_validation:
        target = needs_validation[0]
        primary_action = {
            "type": "validate_prerequisites",
            "label": f"先验证 {target['skill_id']}",
            "message": (
                f"当前有待验证前置技能 {target['skill_id']}，"
                f"掌握度 {target['mastery_score']:.0%}。先补稳定性，再开新内容。"
            ),
            "skill_ids": [target["skill_id"]],
            "block_new_skills": True,
        }
        other_active = [skill for skill in active_skills if skill["skill_id"] != target["skill_id"]]
        if other_active:
            secondary_action = {
                "type": "resume_in_progress",
                "label": f"随后继续 {other_active[0]['skill_id']}",
                "message": f"验证完成后继续当前挂起技能点 {other_active[0]['skill_id']}。",
                "skill_ids": [other_active[0]["skill_id"]],
            }
    elif active_skills:
        target = active_skills[0]
        prefix = "当前存在高优先级警报。" if high_alerts else "先清挂起技能点。"
        primary_action = {
            "type": "resume_in_progress",
            "label": f"继续 {target['skill_id']}",
            "message": (
                f"{prefix} 优先继续 {target['skill_id']}，"
                f"当前状态为 {target['status']}，掌握度 {target['mastery_score']:.0%}。"
            ),
            "skill_ids": [target["skill_id"]],
            "block_new_skills": True,
        }
        if available_skills:
            secondary_action = {
                "type": "defer_new_skill",
                "label": "暂缓新技能点",
                "message": (
                    f"当前仍有 {len(active_skills)} 个进行中的技能点，"
                    "不建议现在再开新技能点。"
                ),
                "skill_ids": [],
            }
    elif available_skills:
        target = available_skills[0]
        primary_action = {
            "type": "start_new_skill",
            "label": f"开始 {target['skill_id']}",
            "message": (
                f"当前没有到期复习，也没有挂起技能点，可以开始新的可学习技能点 {target['skill_id']}。"
            ),
            "skill_ids": [target["skill_id"]],
            "block_new_skills": False,
        }
        if review_summary["soon_count"] > 0:
            secondary_action = {
                "type": "watch_upcoming_reviews",
                "label": "留意即将到期复习",
                "message": (
                    f"未来 3 天内还有 {review_summary['soon_count']} 个技能点将到期，"
                    "新技能点不宜开得太快。"
                ),
                "skill_ids": [item["skill_id"] for item in review_summary["soon_reviews"][:3]],
            }
    else:
        primary_action = {
            "type": "maintenance",
            "label": "维持当前节奏",
            "message": "当前没有到期复习、没有挂起技能点，也没有新的可学习技能点。",
            "skill_ids": [],
            "block_new_skills": False,
        }

    return {
        "date": today.isoformat(),
        "primary_action": primary_action,
        "secondary_action": secondary_action,
        "question_focus": question_focus,
        "confusion_pairs": confusion_pairs,
        "alerts": alerts,
        "review_summary": review_summary,
    }


def check_alerts(graph: dict, config: dict, sessions: list[dict]) -> list[dict]:
    """检查系统性薄弱警报"""
    alerts = []

    # 1. 错误类型趋势
    error_dist = calc_error_distribution(sessions)
    total_errors = sum(error_dist.values())
    if total_errors > 0:
        for err_type, count in error_dist.items():
            ratio = count / total_errors
            if err_type in ("提取失败", "retrieval") and ratio > 0.3:
                alerts.append({
                    "type": "high_retrieval_failure",
                    "message": f"「提取失败」占比 {ratio:.0%} > 30%，概念课到练习课间隔可能过长",
                    "severity": "high",
                })
            if err_type in ("概念混淆", "conceptual") and ratio > 0.3:
                alerts.append({
                    "type": "high_conceptual_confusion",
                    "message": f"「概念混淆」占比 {ratio:.0%} > 30%，相似概念辨析练习不足",
                    "severity": "high",
                })

    # 2. 学习速度减慢
    speed = calc_speed_trend(graph)
    slow_count = sum(1 for b in speed[-2:] if "🔴" in b.get("trend", ""))
    if slow_count >= 2:
        alerts.append({
            "type": "learning_slowdown",
            "message": "连续 2 个阶段学习速度下降，建议暂停新技能点，集中复习",
            "severity": "high",
        })

    # 3. 第1次复习通过率
    review_stats = calc_review_effectiveness(graph, config)
    r0 = review_stats.get(0, {})
    if r0.get("total", 0) >= 3:
        pass_rate = r0["passed"] / r0["total"]
        if pass_rate < 0.7:
            alerts.append({
                "type": "low_first_review_pass",
                "message": f"第1次复习通过率 {pass_rate:.0%} < 70%，掌握判定可能不够严格",
                "severity": "medium",
            })

    return alerts


def export_analytics_md(graph: dict, config: dict) -> str:
    """生成 analytics.md"""
    sessions = collect_all_sessions(graph)
    error_dist = calc_error_distribution(sessions)
    answer_format_stats = calc_answer_format_stats(sessions)
    review_stats = calc_review_effectiveness(graph, config)
    speed_trend = calc_speed_trend(graph)
    alerts = check_alerts(graph, config, sessions)
    recommendation = recommend_next_actions(graph, config, sessions=sessions)
    confusion_pairs = recommendation["confusion_pairs"]

    total_sessions = len([s for s in sessions if s.get("type", "practice") == "practice"])
    total_reviews = len([s for s in sessions if s.get("type") == "review"])
    total_questions = sum(s.get("total_questions", 1) for s in sessions)
    total_correct = sum(s.get("correct_count", round(s.get("accuracy", 0) * s.get("total_questions", 1)))
                        for s in sessions)
    overall_accuracy = total_correct / total_questions if total_questions > 0 else 0

    lines = [
        "# 学习数据分析\n",
        f"> 最后更新：{date.today().isoformat()}\n",
        "## 总体统计\n",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 累计练习课次数 | {total_sessions} |",
        f"| 累计复习课次数 | {total_reviews} |",
        f"| 总答题数 | {total_questions} |",
        f"| 总体准确率 | {overall_accuracy:.0%} |",
    ]

    lines.append("\n## 今日建议\n")
    primary_action = recommendation["primary_action"]
    lines.append(f"- 主动作：{primary_action['message']}")
    secondary_action = recommendation.get("secondary_action")
    if secondary_action:
        lines.append(f"- 次动作：{secondary_action['message']}")
    question_focus = recommendation["question_focus"]
    lines.append(f"- 题型侧重：{question_focus['message']}")

    # 错误分布
    if error_dist:
        lines.append("\n## 错误类型分布\n")
        lines.append("| 错误类型 | 次数 | 占比 |")
        lines.append("|---------|------|------|")
        total_errors = sum(error_dist.values())
        for err_type, count in error_dist.items():
            pct = f"{count/total_errors*100:.0f}%" if total_errors > 0 else "—"
            lines.append(f"| {err_type} | {count} | {pct} |")

    if answer_format_stats:
        lines.append("\n## 作答形式分布\n")
        lines.append("| 作答形式 | 题量 | 正确数 | 准确率 |")
        lines.append("|----------|------|--------|--------|")
        for answer_format, item in answer_format_stats.items():
            lines.append(
                f"| {answer_format} | {int(item['total'])} | {int(item['correct'])} | {item['accuracy']:.0%} |"
            )

    # 学习速度趋势
    if speed_trend:
        lines.append("\n## 学习速度趋势\n")
        lines.append("| 阶段 | 平均练习次数 | 平均准确率 | 趋势 |")
        lines.append("|------|------------|-----------|------|")
        for batch in speed_trend:
            days = f"{batch['avg_days_to_master']:.0f}天" if batch['avg_days_to_master'] else "—"
            lines.append(
                f"| 第{batch['batch']}批 | "
                f"{batch['avg_practice_count']:.1f}次 | "
                f"{batch['avg_accuracy']:.0%} | "
                f"{batch['trend']} |"
            )

    if confusion_pairs:
        lines.append("\n## 易混淆技能对\n")
        lines.append("| 技能点对 | 次数 | 最近出现 |")
        lines.append("|----------|------|----------|")
        for item in confusion_pairs:
            pair_label = f"{item['skills'][0]} / {item['skills'][1]}"
            lines.append(f"| {pair_label} | {item['count']} | {item['latest_date']} |")

    # 警报
    if alerts:
        lines.append("\n## ⚠️ 系统性薄弱警报\n")
        for alert in alerts:
            severity_icon = "🔴" if alert["severity"] == "high" else "🟡"
            lines.append(f"- {severity_icon} {alert['message']}")

    return "\n".join(lines)


# ─── CLI ────────────────────────────────────────────────────

@click.group()
def cli():
    """学习数据分析"""
    pass


@cli.command()
def report():
    """生成完整分析报告"""
    graph = load_graph()
    config = load_config()

    md = export_analytics_md(graph, config)

    output_path = TEACHER_DIR / "analytics.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)

    console.print(f"[green]✓[/green] 分析报告已生成：{output_path}")

    # 也在终端显示关键指标
    sessions = collect_all_sessions(graph)
    alerts = check_alerts(graph, config, sessions)
    recommendation = recommend_next_actions(graph, config, sessions=sessions)

    console.print(f"\n[bold]📌 今日建议[/bold]")
    console.print(f"   {recommendation['primary_action']['message']}")
    if recommendation.get("secondary_action"):
        console.print(f"   {recommendation['secondary_action']['message']}")
    console.print(f"   题型侧重：{recommendation['question_focus']['message']}")

    if alerts:
        console.print(f"\n[bold red]⚠️ 警报 ({len(alerts)})：[/bold red]")
        for alert in alerts:
            console.print(f"   {alert['message']}")
    console.print()


@cli.command()
def today():
    """输出今天最该做的学习动作"""
    graph = load_graph()
    config = load_config()

    recommendation = recommend_next_actions(graph, config)
    review_summary = recommendation["review_summary"]
    confusion_pairs = recommendation["confusion_pairs"]

    console.print(f"\n[bold]📍 今日建议（{recommendation['date']}）[/bold]\n")
    console.print(f"[bold]主动作：[/bold] {recommendation['primary_action']['label']}")
    console.print(f"   {recommendation['primary_action']['message']}")

    secondary_action = recommendation.get("secondary_action")
    if secondary_action:
        console.print(f"\n[bold]次动作：[/bold] {secondary_action['label']}")
        console.print(f"   {secondary_action['message']}")

    console.print(f"\n[bold]题型侧重：[/bold] {recommendation['question_focus']['label']}")
    console.print(f"   {recommendation['question_focus']['message']}")

    if review_summary["due_count"] > 0 or review_summary["soon_count"] > 0:
        console.print(
            f"\n[bold]复习压力：[/bold] 到期 {review_summary['due_count']} 个，"
            f"未来 3 天内即将到期 {review_summary['soon_count']} 个"
        )

    if confusion_pairs:
        console.print(f"\n[bold]易混淆技能对：[/bold]")
        for item in confusion_pairs[:3]:
            console.print(
                f"   {item['skills'][0]} / {item['skills'][1]}：{item['count']} 次"
            )

    alerts = recommendation.get("alerts", [])
    if alerts:
        console.print(f"\n[bold red]警报：[/bold red]")
        for alert in alerts:
            console.print(f"   {alert['message']}")

    console.print(f"\n[dim]JSON 输出：[/dim]")
    console.print(json.dumps(recommendation, ensure_ascii=False, indent=2))
    console.print()


@cli.command()
def errors():
    """显示错误类型分布"""
    graph = load_graph()
    sessions = collect_all_sessions(graph)
    error_dist = calc_error_distribution(sessions)

    if not error_dist:
        console.print("[dim]暂无错误记录[/dim]")
        return

    total = sum(error_dist.values())
    console.print(f"\n[bold]📊 错误类型分布（共 {total} 次错误）[/bold]\n")

    table = Table(box=box.SIMPLE)
    table.add_column("错误类型")
    table.add_column("次数", justify="right")
    table.add_column("占比", justify="right")
    table.add_column("条形图")

    max_count = max(error_dist.values()) if error_dist else 1
    for err_type, count in error_dist.items():
        pct = count / total * 100
        bar_len = int(count / max_count * 20)
        bar = "█" * bar_len
        table.add_row(err_type, str(count), f"{pct:.0f}%", f"[red]{bar}[/red]")

    console.print(table)
    console.print()


@cli.command()
def speed():
    """显示学习速度趋势"""
    graph = load_graph()
    trend = calc_speed_trend(graph)

    if not trend:
        console.print("[dim]暂无足够数据计算趋势[/dim]")
        return

    console.print(f"\n[bold]📈 学习速度趋势[/bold]\n")

    table = Table(box=box.ROUNDED)
    table.add_column("阶段")
    table.add_column("技能点")
    table.add_column("平均练习次数", justify="right")
    table.add_column("平均准确率", justify="right")
    table.add_column("趋势")

    for batch in trend:
        skills_str = ", ".join(batch["skills"][:3])
        if len(batch["skills"]) > 3:
            skills_str += f" +{len(batch['skills'])-3}"
        table.add_row(
            f"第{batch['batch']}批",
            skills_str,
            f"{batch['avg_practice_count']:.1f}",
            f"{batch['avg_accuracy']:.0%}",
            batch["trend"],
        )

    console.print(table)
    console.print()


@cli.command()
def alerts():
    """检查系统性薄弱警报"""
    graph = load_graph()
    config = load_config()
    sessions = collect_all_sessions(graph)

    alert_list = check_alerts(graph, config, sessions)

    if not alert_list:
        console.print("[green]✨ 当前没有系统性薄弱警报[/green]")
        return

    console.print(f"\n[bold red]⚠️ 系统性薄弱警报（{len(alert_list)} 个）[/bold red]\n")
    for alert in alert_list:
        severity_icon = "🔴" if alert["severity"] == "high" else "🟡"
        console.print(f"   {severity_icon} {alert['message']}")
    console.print()


if __name__ == "__main__":
    cli()
