"""
session.py — 练习课管理

核心职责：
- 生成练习课配置（题目分配、总量）
- 记录练习结果并执行掌握判定
- 检查并触发自动降级
- 对 A/D 类学科从绑定题库选题

用法：
    python -m engine.session start SK-001          # 生成练习课配置
    python -m engine.session result SK-001 '{"1":"correct","2":"wrong:conceptual",...}'
    python -m engine.session remediation            # 检查自动降级
"""

import json
import sys
from datetime import date
from typing import Any, Optional

try:
    import click
    from rich.console import Console
    from rich.table import Table
    from rich import box
except ImportError:
    print("请安装依赖: pip install click rich")
    sys.exit(1)

from engine.state import (
    load_config, load_graph, save_graph, get_skill,
    check_unlockable, get_mastery_score, set_mastery_score,
    set_mastery_score_from_status, get_status_mastery_floor,
)
from engine.content import load_question_bank, load_skill_rubrics
from engine.event_log import (
    append_answer_events,
    load_question_index,
    parse_result_payload as parse_event_result_payload,
)
from engine.fire import apply_fire_awards, calculate_fire_awards, failure_suggestions
from engine.graph import merge_graph_v2_assets
from engine.review import get_due_reviews_with_fire
from engine.student_model import (
    clamp,
    derive_mastery_score,
    get_skill_student_model,
    model_from_mastery_score,
    update_models_from_event,
)
from engine.task_selection import rank_tasks

console = Console()

ITEM_EVIDENCE_FIELDS = (
    "skill_vector",
    "target_edge",
    "target_edges",
    "misconception_targets",
    "difficulty_param",
    "discrimination",
    "expected_time_sec",
    "requires_automaticity",
    "allowed_hints",
    "variant_family",
    "surface_similarity_group",
)

DEFAULT_PRACTICE_BLUEPRINT = [
    {"question_type": "conceptual", "answer_format": "short_answer"},
    {"question_type": "scenario", "answer_format": "short_answer"},
    {"question_type": "conceptual", "answer_format": "multiple_choice_explained"},
    {"question_type": "argument_analysis", "answer_format": "short_argument"},
    {"question_type": "counterexample", "answer_format": "counterexample"},
    {"question_type": "scenario", "answer_format": "short_answer"},
    {"question_type": "cross_skill", "answer_format": "short_argument"},
    {"question_type": "boundary", "answer_format": "multiple_choice_explained"},
]

DEFAULT_PRACTICE_BLUEPRINT_EXTENSION = [
    {"question_type": "scenario", "answer_format": "short_answer"},
    {"question_type": "argument_analysis", "answer_format": "short_argument"},
    {"question_type": "counterexample", "answer_format": "counterexample"},
    {"question_type": "boundary", "answer_format": "short_argument"},
]


# ─── 练习课配置生成 ─────────────────────────────────────────

def _question_sort_key(question_num: str) -> tuple[int, str]:
    """优先按数字题号排序，无法转数字时按字符串排序。"""
    try:
        return (0, f"{int(question_num):08d}")
    except (TypeError, ValueError):
        return (1, str(question_num))


def _normalize_string_map(raw: Any, field_name: str) -> dict[str, str]:
    """将可选映射字段标准化为 str -> str。"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{field_name} 必须是对象")
    normalized = {}
    for key, value in raw.items():
        if value is None:
            continue
        normalized[str(key)] = str(value)
    return normalized


def _normalize_used_exercises(raw: Any) -> list[str]:
    """兼容列表、映射和值三种输入形式。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if item is not None]
    if isinstance(raw, dict):
        exercises: list[str] = []
        for value in raw.values():
            if value is None:
                continue
            if isinstance(value, list):
                exercises.extend(str(item) for item in value if item is not None)
            else:
                exercises.append(str(value))
        return exercises
    return [str(raw)]


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _count_map_values(values: dict[str, str]) -> dict[str, int]:
    counter: dict[str, int] = {}
    for value in values.values():
        counter[value] = counter.get(value, 0) + 1
    return counter


def _get_practice_design_config(config: dict) -> dict[str, Any]:
    practice_design = config.get("practice_question_design", {})
    if not isinstance(practice_design, dict):
        practice_design = {}
    return practice_design


def parse_result_payload(raw_payload: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    """
    兼容两种格式：

    1. 旧格式：{"1":"correct","2":"wrong:conceptual"}
    2. 新格式：
       {
         "answers": {...},
         "planned_total": 8,
         "termination_reason": "early_termination",
         "question_types": {"1":"conceptual"},
         "source_skill": {"1":"SK-001"},
         "answer_format": {"1":"short_answer"},
         "used_exercises": [...]
       }

       或：
       {
         "questions": {
           "1": {
             "result": "correct",
             "question_type": "conceptual",
             "answer_format": "short_answer",
             "source_skill": "SK-001",
             "used_exercise": "Q-1"
           }
         },
         "planned_total": 8
       }
    """
    if not isinstance(raw_payload, dict):
        raise ValueError("答案 JSON 顶层必须是对象")

    question_types: dict[str, str] = {}
    answer_format_map: dict[str, str] = {}
    source_skill_map: dict[str, str] = {}
    used_exercises: list[str] = []

    if "questions" in raw_payload:
        questions = raw_payload.get("questions")
        if not isinstance(questions, dict):
            raise ValueError("questions 必须是对象")
        answers = {}
        for question_num, question_data in questions.items():
            q_key = str(question_num)
            if isinstance(question_data, str):
                answers[q_key] = question_data
                continue
            if not isinstance(question_data, dict):
                raise ValueError("questions 中的每题必须是字符串或对象")
            result = question_data.get("result")
            if not isinstance(result, str):
                raise ValueError(f"questions[{q_key}].result 缺失或不是字符串")
            answers[q_key] = result
            if question_data.get("question_type") is not None:
                question_types[q_key] = str(question_data["question_type"])
            if question_data.get("answer_format") is not None:
                answer_format_map[q_key] = str(question_data["answer_format"])
            if question_data.get("source_skill") is not None:
                source_skill_map[q_key] = str(question_data["source_skill"])
            used_exercises.extend(
                _normalize_used_exercises(
                    question_data.get("used_exercises", question_data.get("used_exercise"))
                )
            )
    elif "answers" in raw_payload:
        answers = _normalize_string_map(raw_payload.get("answers"), "answers")
        question_types = _normalize_string_map(raw_payload.get("question_types"), "question_types")
        answer_format_map = _normalize_string_map(raw_payload.get("answer_format"), "answer_format")
        source_skill_map = _normalize_string_map(raw_payload.get("source_skill"), "source_skill")
        used_exercises = _normalize_used_exercises(raw_payload.get("used_exercises"))
    else:
        answers = _normalize_string_map(raw_payload, "answers")

    if not answers:
        raise ValueError("答案不能为空")

    planned_total_raw = raw_payload.get("planned_total", len(answers))
    try:
        planned_total = int(planned_total_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("planned_total 必须是整数") from exc
    planned_total = max(planned_total, len(answers))

    metadata = {
        "planned_total": planned_total,
        "termination_reason": raw_payload.get("termination_reason"),
        "question_types": question_types,
        "answer_format": answer_format_map,
        "source_skill": source_skill_map,
        "used_exercises": _dedupe_keep_order(used_exercises),
    }
    return answers, metadata


def enrich_metadata_from_question_ids(metadata: dict[str, Any]) -> dict[str, Any]:
    question_index = load_question_index()
    used_map = metadata.get("used_exercise_map", {})
    if not isinstance(used_map, dict) or not used_map:
        return metadata

    question_types = dict(metadata.get("question_types", {}))
    answer_formats = dict(metadata.get("answer_format", {}))
    evidence_maps = dict(metadata.get("evidence_maps", {}))
    for question_num, question_id in used_map.items():
        entry = question_index.get(str(question_id))
        if not entry:
            continue
        q_key = str(question_num)
        question_types.setdefault(q_key, entry.get("question_type"))
        answer_formats.setdefault(q_key, entry.get("recommended_format"))
        for field in ITEM_EVIDENCE_FIELDS:
            if entry.get(field) is None:
                continue
            values = dict(evidence_maps.get(field, {}))
            values.setdefault(q_key, entry[field])
            evidence_maps[field] = values

    metadata["question_types"] = {key: value for key, value in question_types.items() if value is not None}
    metadata["answer_format"] = {key: value for key, value in answer_formats.items() if value is not None}
    metadata["evidence_maps"] = evidence_maps
    return metadata


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _get_last_practice_record(skill: dict) -> dict[str, Any]:
    history = skill.get("practice_history", [])
    if not history:
        return {}
    return history[-1]


def _get_recent_skill_candidates(graph: dict, skill_id: str, limit: int) -> list[str]:
    recent_skills: list[tuple[str, str]] = []
    for sid, skill in graph["skills"].items():
        if sid == skill_id:
            continue
        if skill.get("status") not in ("demo_done", "mastered", "review_due", "long_term", "learning"):
            continue
        activity_date = (
            skill.get("dates", {}).get("last_practiced")
            or skill.get("dates", {}).get("first_mastered")
            or skill.get("dates", {}).get("demo_completed")
        )
        if activity_date:
            recent_skills.append((sid, activity_date))
    recent_skills.sort(key=lambda item: item[1], reverse=True)
    return [sid for sid, _ in recent_skills[:limit]]


def _build_candidate_priorities(
    graph: dict,
    config: dict,
    skill_id: str,
    due_reviews: list[dict],
) -> dict[str, dict[str, Any]]:
    """为候选技能点计算优先级分数和解释。"""
    skill = get_skill(graph, skill_id)
    interleaving = config.get("interleaving", {})
    weights = interleaving.get("score_weights", {})
    today = date.today()
    threshold_cfg = config.get("mastery_threshold", {})
    intensity = config.get("intensity", "medium")
    threshold = threshold_cfg.get(intensity, 0.8) if isinstance(threshold_cfg, dict) else threshold_cfg

    default_weights = {
        "current_skill": 8.0,
        "due_review": 3.0,
        "due_review_per_overdue_day": 0.35,
        "prerequisite": 2.5,
        "needs_validation": 3.5,
        "learning": 2.0,
        "recent_skill": 1.0,
        "recent_error": 0.75,
        "low_accuracy": 8.0,
        "recent_practice_penalty": 1.25,
    }
    merged_weights = {**default_weights, **weights}
    recent_limit = int(interleaving.get("max_recent_candidates", 5) or 5)

    due_review_lookup = {item["skill_id"]: item for item in due_reviews}
    recent_skill_ids = _get_recent_skill_candidates(graph, skill_id, recent_limit)
    prerequisite_ids = set(skill.get("prerequisites", []))

    candidate_ids = {skill_id, *due_review_lookup.keys(), *recent_skill_ids, *prerequisite_ids}
    priorities: dict[str, dict[str, Any]] = {}

    for candidate_id in candidate_ids:
        candidate = graph["skills"].get(candidate_id)
        if not candidate:
            continue

        score = 0.0
        reasons: list[str] = []
        tags: list[str] = []

        if candidate_id == skill_id:
            score += merged_weights["current_skill"]
            tags.append("current")
            reasons.append(f"当前技能点 +{merged_weights['current_skill']:.2f}")

        due_review = due_review_lookup.get(candidate_id)
        if due_review:
            due_bonus = merged_weights["due_review"] + (
                due_review["days_overdue"] * merged_weights["due_review_per_overdue_day"]
            )
            score += due_bonus
            tags.append("due_review")
            reasons.append(
                f"复习到期 +{due_bonus:.2f}（过期 {due_review['days_overdue']} 天）"
            )

        if candidate_id in prerequisite_ids:
            score += merged_weights["prerequisite"]
            tags.append("prerequisite")
            reasons.append(f"当前技能点前置 +{merged_weights['prerequisite']:.2f}")

        status = candidate.get("status")
        if status == "needs_validation":
            score += merged_weights["needs_validation"]
            tags.append("needs_validation")
            reasons.append(f"待验证状态 +{merged_weights['needs_validation']:.2f}")
        elif status == "learning":
            score += merged_weights["learning"]
            tags.append("learning")
            reasons.append(f"学习中状态 +{merged_weights['learning']:.2f}")

        if candidate_id in recent_skill_ids:
            score += merged_weights["recent_skill"]
            tags.append("recent")
            reasons.append(f"近期活跃技能 +{merged_weights['recent_skill']:.2f}")

        mastery_score = get_mastery_score(candidate, config)
        mastery_gap_weight = merged_weights.get("mastery_gap", 0.0)
        if mastery_gap_weight > 0:
            mastery_gap_bonus = (1.0 - mastery_score) * mastery_gap_weight
            score += mastery_gap_bonus
            reasons.append(f"掌握度缺口 +{mastery_gap_bonus:.2f}（当前 {mastery_score:.0%}）")

        last_record = _get_last_practice_record(candidate)
        error_counts = last_record.get("error_counts", {})
        error_pressure = sum(error_counts.values()) if error_counts else len(last_record.get("errors", []))
        if error_pressure > 0:
            error_bonus = min(error_pressure, 4) * merged_weights["recent_error"]
            score += error_bonus
            reasons.append(f"近期错误压力 +{error_bonus:.2f}（{error_pressure} 次）")

        last_accuracy = last_record.get("accuracy")
        if isinstance(last_accuracy, (int, float)) and last_accuracy < threshold:
            accuracy_gap = threshold - last_accuracy
            low_accuracy_bonus = accuracy_gap * merged_weights["low_accuracy"]
            score += low_accuracy_bonus
            reasons.append(
                f"近期准确率偏低 +{low_accuracy_bonus:.2f}（{last_accuracy:.0%}）"
            )

        if not due_review:
            last_practiced = _parse_iso_date(candidate.get("dates", {}).get("last_practiced"))
            if last_practiced is not None:
                days_since = (today - last_practiced).days
                if days_since <= 2:
                    penalty_factor = (3 - max(days_since, 0)) / 3
                    penalty = merged_weights["recent_practice_penalty"] * penalty_factor
                    score -= penalty
                    reasons.append(f"近期刚练过 -{penalty:.2f}（{days_since} 天前）")

        priorities[candidate_id] = {
            "skill_id": candidate_id,
            "name": candidate.get("name", candidate_id),
            "status": status,
            "mastery_score": mastery_score,
            "score": round(max(score, 0.0), 4),
            "tags": _dedupe_keep_order(tags),
            "reasons": reasons or ["默认候选"],
        }

    return priorities


def _build_adaptive_candidate_priorities(
    graph: dict,
    config: dict,
    skill_id: str,
    total_questions: int,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Use the expected-gain task selector as the source of session candidates."""
    adaptive_cfg = config.get("adaptive_runtime", {})
    limit = int(adaptive_cfg.get("task_ranking_limit", max(8, total_questions * 2)) or 8)
    tasks = rank_tasks(
        merge_graph_v2_assets(graph),
        limit=max(limit, total_questions),
        target_skill_id=skill_id,
    )
    priorities: dict[str, dict[str, Any]] = {}
    for task in tasks:
        candidate_id = task["skill_id"]
        if candidate_id not in graph.get("skills", {}):
            continue
        if task["task_type"] == "frontier_probe" and candidate_id != skill_id:
            continue
        existing = priorities.get(candidate_id)
        score = float(task.get("score", 0.0) or 0.0)
        tags = [str(task.get("task_type", "adaptive"))]
        if candidate_id == skill_id:
            tags.append("current")
        if task.get("task_type") == "review":
            tags.append("due_review")
        if task.get("task_type") == "validate":
            tags.append("needs_validation")
        if task.get("task_type") == "remediate":
            tags.append("remediation")
        if "target_prerequisite" in str(task.get("trigger", "")):
            tags.append("prerequisite")

        item = {
            "skill_id": candidate_id,
            "name": task.get("name", candidate_id),
            "status": task.get("status"),
            "mastery_score": task.get("model", {}).get(
                "mastery_score",
                get_mastery_score(graph["skills"][candidate_id], config),
            ),
            "score": round(max(score, 0.05), 4),
            "tags": _dedupe_keep_order(tags),
            "reasons": task.get("reasons", []) or [f"adaptive task {task.get('task_type')}"],
            "adaptive_task": {
                "task_id": task.get("task_id"),
                "task_type": task.get("task_type"),
                "estimated_minutes": task.get("estimated_minutes"),
                "components": task.get("components", {}),
            },
        }
        if existing is None or item["score"] > existing["score"]:
            priorities[candidate_id] = item

    if skill_id not in priorities:
        skill = get_skill(graph, skill_id)
        priorities[skill_id] = {
            "skill_id": skill_id,
            "name": skill.get("name", skill_id),
            "status": skill.get("status"),
            "mastery_score": get_mastery_score(skill, config),
            "score": 8.0,
            "tags": ["current", "adaptive_fallback"],
            "reasons": ["当前技能点保底"],
        }

    return priorities, tasks


def _allocate_questions_by_priority(
    total_questions: int,
    skill_id: str,
    candidate_priorities: dict[str, dict[str, Any]],
    current_minimum: int,
    spread_penalty: float,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """按优先级逐题分配，带简单分散惩罚。"""
    allocation = {candidate_id: 0 for candidate_id in candidate_priorities}
    selection_trace: list[dict[str, Any]] = []

    current_minimum = min(total_questions, max(1, current_minimum))
    allocation[skill_id] = current_minimum
    for idx in range(current_minimum):
        selection_trace.append({
            "question_index": idx + 1,
            "skill_id": skill_id,
            "effective_score": candidate_priorities[skill_id]["score"],
            "reason": "保底当前技能点",
        })

    for question_index in range(current_minimum + 1, total_questions + 1):
        best_skill_id = None
        best_effective_score = float("-inf")
        for candidate_id, priority in candidate_priorities.items():
            base_score = priority["score"]
            effective_score = base_score / (1 + allocation[candidate_id] * spread_penalty)
            if effective_score > best_effective_score:
                best_effective_score = effective_score
                best_skill_id = candidate_id

        if best_skill_id is None:
            break

        allocation[best_skill_id] += 1
        selection_trace.append({
            "question_index": question_index,
            "skill_id": best_skill_id,
            "effective_score": round(best_effective_score, 4),
            "reason": candidate_priorities[best_skill_id]["reasons"][0],
        })

    return (
        {skill_id_: count for skill_id_, count in allocation.items() if count > 0},
        selection_trace,
    )


def _normalize_blueprint_entries(raw_entries: Any) -> list[dict[str, str]]:
    if not isinstance(raw_entries, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        question_type = item.get("question_type")
        answer_format = item.get("answer_format")
        if question_type is None or answer_format is None:
            continue
        normalized.append({
            "question_type": str(question_type),
            "answer_format": str(answer_format),
        })
    return normalized


def _select_practice_question_asset(
    question_banks: dict[str, dict],
    used_entry_ids: set[str],
    used_families: set[str],
    primary_skill_id: str,
    source_skills: list[str],
    question_type: str,
    answer_format: str,
) -> Optional[dict[str, Any]]:
    candidate_skill_ids = _dedupe_keep_order([primary_skill_id, *source_skills])

    def matches(
        entry: dict[str, Any],
        *,
        strict_type: bool,
        strict_format: bool,
        require_related: bool,
    ) -> bool:
        entry_id = entry.get("id")
        if not entry_id or str(entry_id) in used_entry_ids:
            return False
        stage_fit = entry.get("stage_fit", [])
        if "practice" not in stage_fit:
            return False
        if strict_type and entry.get("question_type") != question_type:
            return False
        if strict_format and entry.get("recommended_format") != answer_format:
            return False
        if require_related:
            related_skills = set(str(skill_id) for skill_id in entry.get("related_skills", []))
            expected_related = {skill_id for skill_id in source_skills if skill_id != primary_skill_id}
            if not expected_related.issubset(related_skills):
                return False
        return True

    for strict_type, strict_format, require_related, prefer_new_family in (
        (True, True, True, True),
        (True, True, False, True),
        (True, False, False, True),
        (False, False, False, True),
        (True, True, True, False),
        (True, True, False, False),
        (True, False, False, False),
        (False, False, False, False),
    ):
        best_match: Optional[dict[str, Any]] = None
        best_key: Optional[tuple[int, int, str]] = None
        for skill_order, candidate_skill_id in enumerate(candidate_skill_ids):
            question_bank = question_banks.get(candidate_skill_id)
            if not question_bank:
                continue
            for entry in question_bank.get("entries", []):
                if not isinstance(entry, dict):
                    continue
                if not matches(
                    entry,
                    strict_type=strict_type,
                    strict_format=strict_format,
                    require_related=require_related,
                ):
                    continue
                family = str(entry.get("family", ""))
                family_penalty = 1 if prefer_new_family and family and family in used_families else 0
                entry_id = str(entry.get("id", ""))
                sort_key = (family_penalty, skill_order, entry_id)
                if best_key is None or sort_key < best_key:
                    best_key = sort_key
                    best_match = entry
        if best_match is not None:
            return best_match
    return None


def _build_question_plan(
    graph: dict,
    config: dict,
    skill_id: str,
    allocation: dict[str, int],
    selection_trace: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int], dict[str, Any], dict[str, Any]]:
    """为每道练习题生成题型/作答形式蓝图。"""
    practice_design = _get_practice_design_config(config)
    total_questions = sum(allocation.values())
    max_multiple_choice = int(practice_design.get("max_multiple_choice", 2) or 2)
    require_explanation = bool(
        practice_design.get("require_explanation_for_multiple_choice", True)
    )

    base_blueprint = (
        _normalize_blueprint_entries(practice_design.get("blueprint"))
        or DEFAULT_PRACTICE_BLUEPRINT
    )
    extension_blueprint = (
        _normalize_blueprint_entries(practice_design.get("extension_blueprint"))
        or DEFAULT_PRACTICE_BLUEPRINT_EXTENSION
    )

    skill = get_skill(graph, skill_id)
    has_cross_skill_material = len(allocation) > 1 or bool(skill.get("prerequisites", []))
    multiple_choice_count = 0
    question_plan: list[dict[str, Any]] = []
    question_banks: dict[str, dict] = {}
    rubric_maps: dict[str, dict[str, dict]] = {}
    for candidate_skill_id in _dedupe_keep_order([skill_id, *allocation.keys()]):
        question_bank = load_question_bank(candidate_skill_id)
        if not question_bank:
            continue
        question_banks[candidate_skill_id] = question_bank
        rubric_maps[candidate_skill_id] = load_skill_rubrics(candidate_skill_id)
    used_entry_ids: set[str] = set()
    used_families: set[str] = set()
    selected_asset_count = 0

    for question_index in range(1, total_questions + 1):
        if question_index <= len(base_blueprint):
            template = base_blueprint[question_index - 1]
        else:
            template = extension_blueprint[(question_index - len(base_blueprint) - 1) % len(extension_blueprint)]

        question_type = template["question_type"]
        answer_format = template["answer_format"]

        if question_type == "cross_skill" and not has_cross_skill_material:
            question_type = "argument_analysis"

        if answer_format == "multiple_choice_explained" and multiple_choice_count >= max_multiple_choice:
            answer_format = "short_answer"
            if question_type == "conceptual":
                question_type = "boundary"

        if answer_format == "multiple_choice_explained":
            multiple_choice_count += 1

        trace = selection_trace[question_index - 1]
        primary_skill_id = trace["skill_id"]
        secondary_skill_ids = [sid for sid in allocation if sid != primary_skill_id]
        source_skills = [primary_skill_id]
        if question_type == "cross_skill" and secondary_skill_ids:
            if primary_skill_id != skill_id:
                source_skills = [primary_skill_id, skill_id]
            else:
                source_skills = [primary_skill_id, secondary_skill_ids[0]]

        item = {
            "question_index": question_index,
            "skill_id": primary_skill_id,
            "source_skills": source_skills,
            "question_type": question_type,
            "answer_format": answer_format,
            "requires_explanation": (
                answer_format == "multiple_choice_explained" and require_explanation
            ),
            "selection_reason": trace["reason"],
        }

        bank_entry = _select_practice_question_asset(
            question_banks=question_banks,
            used_entry_ids=used_entry_ids,
            used_families=used_families,
            primary_skill_id=primary_skill_id,
            source_skills=source_skills,
            question_type=question_type,
            answer_format=answer_format,
        )
        if bank_entry:
            entry_id = str(bank_entry["id"])
            family = str(bank_entry.get("family", ""))
            used_entry_ids.add(entry_id)
            if family:
                used_families.add(family)
            selected_asset_count += 1

            rubric_id = str(bank_entry.get("rubric_id", ""))
            rubric = {}
            for candidate_skill_id in _dedupe_keep_order([primary_skill_id, *source_skills]):
                skill_rubrics = rubric_maps.get(candidate_skill_id, {})
                if rubric_id in skill_rubrics:
                    rubric = skill_rubrics[rubric_id]
                    break

            item.update({
                "content_source": "question_bank",
                "bank_entry_id": entry_id,
                "family": family,
                "prompt": bank_entry.get("prompt"),
                "source_sections": bank_entry.get("source_sections", []),
                "expected_points": bank_entry.get("expected_points", []),
                "difficulty": bank_entry.get("difficulty"),
                "stage_fit": bank_entry.get("stage_fit", []),
                "recommended_format": bank_entry.get("recommended_format"),
                "rubric_id": rubric_id or None,
            })
            for field in ITEM_EVIDENCE_FIELDS:
                if bank_entry.get(field) is not None:
                    item[field] = bank_entry[field]
            if rubric:
                item["rubric"] = {
                    "must_hit": rubric.get("must_hit", []),
                    "common_failures": rubric.get("common_failures", []),
                    "partial_credit_rules": rubric.get("partial_credit_rules", []),
                }
        else:
            item["content_source"] = "blueprint_only"

        question_plan.append(item)

    answer_format_targets = _count_map_values(
        {str(item["question_index"]): item["answer_format"] for item in question_plan}
    )
    question_type_targets = _count_map_values(
        {str(item["question_index"]): item["question_type"] for item in question_plan}
    )
    practice_rules = {
        "max_multiple_choice": max_multiple_choice,
        "require_explanation_for_multiple_choice": require_explanation,
    }
    content_assets = {
        "content_source": (
            "question_bank"
            if selected_asset_count == total_questions and total_questions > 0
            else "mixed" if selected_asset_count > 0 else "blueprint_only"
        ),
        "question_bank_loaded": bool(question_banks),
        "rubrics_loaded": any(bool(rubric_map) for rubric_map in rubric_maps.values()),
        "question_bank_selected_count": selected_asset_count,
    }
    return question_plan, answer_format_targets, question_type_targets, practice_rules, content_assets


def _store_student_model(skill: dict[str, Any], model: dict[str, Any]) -> None:
    model["mastery_score"] = derive_mastery_score(model)
    skill["student_model"] = model
    skill["mastery_score"] = model["mastery_score"]


def _apply_status_floor_to_model(model: dict[str, Any], floor: float) -> dict[str, Any]:
    if float(model.get("mastery_score", 0.0) or 0.0) >= floor:
        return model
    baseline = model_from_mastery_score(floor)
    merged = dict(model)
    for field in ("mastery_p", "retrievability", "stability_days", "automaticity"):
        merged[field] = max(float(model.get(field, 0.0) or 0.0), float(baseline.get(field, 0.0) or 0.0))
    merged["uncertainty"] = min(
        float(model.get("uncertainty", baseline["uncertainty"]) or baseline["uncertainty"]),
        float(baseline.get("uncertainty", 0.45) or 0.45),
    )
    merged["mastery_score"] = derive_mastery_score(merged)
    guard = 0
    while merged["mastery_score"] < floor and guard < 20:
        merged["mastery_p"] = round(clamp(float(merged.get("mastery_p", 0.0)) + 0.04), 4)
        merged["retrievability"] = round(clamp(float(merged.get("retrievability", 0.0)) + 0.04), 4)
        merged["automaticity"] = round(clamp(float(merged.get("automaticity", 0.0)) + 0.03), 4)
        merged["uncertainty"] = round(clamp(float(merged.get("uncertainty", 0.45)) - 0.03), 4)
        merged["mastery_score"] = derive_mastery_score(merged)
        guard += 1
    return merged


def _nudge_student_model(
    skill: dict[str, Any],
    uncertainty_delta: float = 0.0,
    retrievability_delta: float = 0.0,
) -> dict[str, Any]:
    model = get_skill_student_model(skill)
    model["uncertainty"] = round(clamp(float(model.get("uncertainty", 0.45)) + uncertainty_delta), 4)
    model["retrievability"] = round(
        clamp(float(model.get("retrievability", 0.0)) + retrievability_delta),
        4,
    )
    _store_student_model(skill, model)
    return model


def _apply_graph_failure_updates(
    graph: dict[str, Any],
    config: dict[str, Any],
    skill_id: str,
    errors_by_type: dict[str, int],
) -> dict[str, Any]:
    """Apply graph-aware failure side effects and return an auditable summary."""
    suggestions = failure_suggestions(
        merge_graph_v2_assets(graph),
        skill_id,
        sorted(errors_by_type.keys()),
    )
    applied = {
        "failed_skill_uncertainty": False,
        "prerequisites_flagged": [],
        "dependents_uncertainty_increased": [],
    }

    failed_skill = graph.get("skills", {}).get(skill_id)
    if failed_skill:
        _nudge_student_model(failed_skill, uncertainty_delta=0.08, retrievability_delta=-0.10)
        applied["failed_skill_uncertainty"] = True

    for prereq_id in suggestions.get("prerequisites_to_validate", []):
        prereq = graph.get("skills", {}).get(prereq_id)
        if not prereq:
            continue
        _nudge_student_model(prereq, uncertainty_delta=0.04)
        if prereq.get("status") in ("mastered", "review_due", "long_term"):
            prereq["status"] = "needs_validation"
            set_mastery_score_from_status(
                prereq,
                config,
                "needs_validation",
                preserve_higher=False,
            )
            applied["prerequisites_flagged"].append(prereq_id)

    for dependent_id in suggestions.get("dependents_to_increase_uncertainty", []):
        dependent = graph.get("skills", {}).get(dependent_id)
        if not dependent:
            continue
        _nudge_student_model(dependent, uncertainty_delta=0.06)
        applied["dependents_uncertainty_increased"].append(dependent_id)

    return {"suggestions": suggestions, "applied": applied}


def _apply_adaptive_runtime_updates(
    graph: dict[str, Any],
    config: dict[str, Any],
    skill_id: str,
    answers: dict[str, str],
    metadata: dict[str, Any],
    passed: bool,
    accuracy: float,
    errors_by_type: dict[str, int],
) -> dict[str, Any]:
    """
    Persist item-level evidence, update the student model, and run FIRe v2.
    """
    runtime_cfg = config.get("adaptive_runtime", {})
    enabled = bool(runtime_cfg.get("enabled", True))
    summary: dict[str, Any] = {
        "enabled": enabled,
        "events_recorded": 0,
        "updated_student_models": [],
        "fire_v2_awards": [],
        "fire_v2_applied": [],
        "failure": None,
    }
    if not enabled:
        return summary

    events = append_answer_events(skill_id, answers, metadata)
    summary["events_recorded"] = len(events)

    states = {
        sid: get_skill_student_model(skill)
        for sid, skill in graph.get("skills", {}).items()
        if isinstance(skill, dict)
    }
    touched: set[str] = set()
    for event in events:
        states = update_models_from_event(states, event)
        skill_vector = event.get("skill_vector")
        if isinstance(skill_vector, dict) and skill_vector:
            touched.update(str(sid) for sid in skill_vector)
        else:
            touched.add(str(event.get("skill_id", skill_id)))

    for sid in sorted(touched):
        skill = graph.get("skills", {}).get(sid)
        model = states.get(sid)
        if not skill or not model:
            continue
        if passed and sid == skill_id:
            model = _apply_status_floor_to_model(
                model,
                get_status_mastery_floor(config, "mastered"),
            )
        _store_student_model(skill, model)
        summary["updated_student_models"].append({
            "skill_id": sid,
            "mastery_score": model.get("mastery_score"),
            "mastery_p": model.get("mastery_p"),
            "retrievability": model.get("retrievability"),
            "uncertainty": model.get("uncertainty"),
        })

    adaptive_graph = merge_graph_v2_assets(graph)
    if passed:
        awards = calculate_fire_awards(
            adaptive_graph,
            skill_id,
            passed=True,
            quality=accuracy,
            config=config,
        )
        applied = apply_fire_awards(
            adaptive_graph,
            awards,
            update_student_model=True,
        )
        summary["fire_v2_awards"] = awards
        summary["fire_v2_applied"] = applied
    else:
        summary["failure"] = _apply_graph_failure_updates(
            graph=graph,
            config=config,
            skill_id=skill_id,
            errors_by_type=errors_by_type,
        )

    return summary


def generate_session_plan(graph: dict, config: dict, skill_id: str) -> dict:
    """
    生成练习课的题目分配方案。
    
    返回：
    {
      "skill_id": "SK-007",
      "total_questions": 10,
      "allocation": {"SK-007": 7, "SK-005": 2, "SK-003": 1},
      "review_skills": ["SK-003"],
      "recent_skills": ["SK-005"],
      "bound_exercises": {...},
      "classification": "C",
      "error": null
    }
    """
    sk = get_skill(graph, skill_id)
    classification = config.get("classification", "C")
    intensity = config.get("intensity", "medium")

    # 题目总量
    q_config = config.get("questions_per_session", {})
    if isinstance(q_config, dict):
        total = q_config.get(intensity, 10)
    else:
        total = q_config

    # 前置检查
    errors = []
    if sk["status"] not in ("demo_done", "learning", "mastered", "review_due", "long_term"):
        if sk["status"] == "concept_done":
            errors.append(f"{skill_id} 概念课已完成但示范练习未完成，请先做示范练习")
        elif sk["status"] in ("locked", "unlocked"):
            errors.append(f"{skill_id} 尚未开始概念课")
        else:
            errors.append(f"{skill_id} 状态为 {sk['status']}，无法开始练习课")

    # 检查前置技能
    for prereq_id in sk.get("prerequisites", []):
        prereq = graph["skills"].get(prereq_id, {})
        if prereq.get("status") not in ("mastered", "long_term", "review_due"):
            errors.append(f"前置技能 {prereq_id} 未掌握（状态：{prereq.get('status', '?')}）")

    if errors:
        return {"error": errors, "skill_id": skill_id}

    # 候选技能优先级
    interleaving = config.get("interleaving", {})
    due_reviews = get_due_reviews_with_fire(graph, config)
    adaptive_cfg = config.get("adaptive_runtime", {})
    adaptive_enabled = bool(adaptive_cfg.get("enabled", True))
    adaptive_task_ranking: list[dict[str, Any]] = []
    if adaptive_enabled:
        candidate_priorities, adaptive_task_ranking = _build_adaptive_candidate_priorities(
            graph=graph,
            config=config,
            skill_id=skill_id,
            total_questions=total,
        )
    else:
        candidate_priorities = _build_candidate_priorities(graph, config, skill_id, due_reviews)
    if not candidate_priorities:
        candidate_priorities = _build_candidate_priorities(graph, config, skill_id, due_reviews)
    current_minimum = int(
        adaptive_cfg.get(
            "current_skill_min_questions",
            interleaving.get("current_skill_min_questions", max(1, total // 2)),
        )
    )
    spread_penalty = float(adaptive_cfg.get("spread_penalty", interleaving.get("spread_penalty", 0.85)))
    allocation, selection_trace = _allocate_questions_by_priority(
        total_questions=total,
        skill_id=skill_id,
        candidate_priorities=candidate_priorities,
        current_minimum=current_minimum,
        spread_penalty=spread_penalty,
    )

    review_skill_ids = [sid for sid, item in candidate_priorities.items() if "due_review" in item["tags"]]
    recent_skills = [sid for sid, item in candidate_priorities.items() if "recent" in item["tags"]]
    prerequisite_skills = [
        sid for sid, item in candidate_priorities.items() if "prerequisite" in item["tags"]
    ]

    # 绑定习题（A/D 类学科）
    bound = {}
    if classification in ("A", "D"):
        for alloc_skill_id, count in allocation.items():
            s = graph["skills"].get(alloc_skill_id, {})
            exercises = s.get("bound_exercises", [])
            # 选取尚未使用过的题目
            used = set()
            for h in s.get("practice_history", []):
                used.update(h.get("used_exercises", []))
            available = [e for e in exercises if e not in used]
            if len(available) < count:
                bound[alloc_skill_id] = {
                    "exercises": available,
                    "shortage": count - len(available),
                    "warning": f"可用习题不足（需要{count}道，只有{len(available)}道）"
                }
            else:
                bound[alloc_skill_id] = {
                    "exercises": available[:count],
                    "shortage": 0,
                }

    question_plan, answer_format_targets, question_type_targets, practice_rules, content_assets = _build_question_plan(
        graph=graph,
        config=config,
        skill_id=skill_id,
        allocation=allocation,
        selection_trace=selection_trace,
    )

    return {
        "skill_id": skill_id,
        "total_questions": total,
        "allocation": allocation,
        "review_skills": [sid for sid in review_skill_ids if sid in allocation],
        "recent_skills": [sid for sid in recent_skills if sid in allocation and sid != skill_id],
        "prerequisite_skills": [sid for sid in prerequisite_skills if sid in allocation],
        "candidate_priorities": sorted(
            candidate_priorities.values(),
            key=lambda item: item["score"],
            reverse=True,
        ),
        "selection_trace": selection_trace,
        "adaptive_runtime_enabled": adaptive_enabled,
        "adaptive_task_ranking": adaptive_task_ranking,
        "recommended_task": adaptive_task_ranking[0] if adaptive_task_ranking else None,
        "question_plan": question_plan,
        "question_type_targets": question_type_targets,
        "answer_format_targets": answer_format_targets,
        "practice_rules": practice_rules,
        "content_source": content_assets["content_source"],
        "question_bank_loaded": content_assets["question_bank_loaded"],
        "rubrics_loaded": content_assets["rubrics_loaded"],
        "question_bank_selected_count": content_assets["question_bank_selected_count"],
        "bound_exercises": bound if bound else None,
        "classification": classification,
        "early_termination": config.get("early_termination", {}),
        "error": None,
    }


def process_results(
    graph: dict,
    config: dict,
    skill_id: str,
    answers: dict[str, str],
    metadata: Optional[dict[str, Any]] = None,
) -> dict:
    """
    处理练习课结果。
    
    answers 格式: {"1": "correct", "2": "wrong:conceptual", "3": "correct", ...}
    
    返回结果字典。
    """
    sk = get_skill(graph, skill_id)
    metadata = metadata or {}
    intensity = config.get("intensity", "medium")
    threshold = config.get("mastery_threshold", {})
    if isinstance(threshold, dict):
        threshold = threshold.get(intensity, 0.8)

    total = len(answers)
    planned_total = max(int(metadata.get("planned_total", total)), total)
    correct = 0
    errors_by_type = {}
    consecutive_wrong = 0
    max_consecutive_wrong = 0
    question_types = metadata.get("question_types", {})
    answer_format_map = metadata.get("answer_format", {})
    source_skill_map = metadata.get("source_skill", {})
    used_exercises = _dedupe_keep_order(metadata.get("used_exercises", []))
    used_exercise_map = metadata.get("used_exercise_map", {})
    response_time_map = metadata.get("response_time_sec", {})
    hint_used_map = metadata.get("hint_used", {})
    rubric_hits_map = metadata.get("rubric_hits", {})
    mastery_score_before = get_mastery_score(sk, config)
    answer_format_counts: dict[str, int] = {}
    answer_format_correct_counts: dict[str, int] = {}

    for q_num in sorted(answers.keys(), key=_question_sort_key):
        ans = answers[q_num]
        answer_format = answer_format_map.get(q_num)
        if answer_format:
            answer_format_counts[answer_format] = answer_format_counts.get(answer_format, 0) + 1
        if ans == "correct":
            correct += 1
            consecutive_wrong = 0
            if answer_format:
                answer_format_correct_counts[answer_format] = (
                    answer_format_correct_counts.get(answer_format, 0) + 1
                )
        else:
            consecutive_wrong += 1
            max_consecutive_wrong = max(max_consecutive_wrong, consecutive_wrong)
            # 解析错误类型
            parts = ans.split(":")
            error_type = parts[1] if len(parts) > 1 else "unspecified"
            errors_by_type[error_type] = errors_by_type.get(error_type, 0) + 1

    accuracy = correct / total if total > 0 else 0
    wrong_count = total - correct

    early_cfg = config.get("early_termination", {})
    min_questions = int(early_cfg.get("min_questions", 0) or 0)
    max_error_ratio = float(early_cfg.get("max_error_ratio", 1.0) or 1.0)
    early_terminated = (
        planned_total > total
        and total >= min_questions
        and total > 0
        and (wrong_count / total) >= max_error_ratio
    )

    termination_reason = metadata.get("termination_reason")
    if termination_reason is None:
        if early_terminated:
            termination_reason = "early_termination"
        elif total < planned_total:
            termination_reason = "partial"
        else:
            termination_reason = "completed"
    elif termination_reason == "completed" and total < planned_total:
        termination_reason = "partial"

    passed = accuracy >= threshold and termination_reason == "completed" and total >= planned_total
    source_skills = _dedupe_keep_order(list(source_skill_map.values())) or [skill_id]
    unique_question_types = _dedupe_keep_order(list(question_types.values()))
    unique_answer_formats = _dedupe_keep_order(list(answer_format_map.values()))

    prerequisites_flagged = []
    prereq_threshold = config.get("remediation", {}).get("prerequisite_check_threshold", 0.5)
    if accuracy < prereq_threshold:
        for prereq_id in sk.get("prerequisites", []):
            prereq = graph["skills"].get(prereq_id)
            if not prereq:
                continue
            if prereq.get("status") in ("mastered", "review_due", "long_term"):
                prereq["status"] = "needs_validation"
                set_mastery_score_from_status(
                    prereq, config, "needs_validation", preserve_higher=False
                )
                prerequisites_flagged.append(prereq_id)

    # 记录练习历史
    if "practice_history" not in sk:
        sk["practice_history"] = []
    history_entry = {
        "date": date.today().isoformat(),
        "accuracy": accuracy,
        "passed": passed,
        "type": "practice",
        "errors": list(errors_by_type.keys()),
        "error_counts": errors_by_type,
        "total_questions": total,
        "correct_count": correct,
        "planned_questions": planned_total,
        "completed_questions": total,
        "question_types": unique_question_types,
        "question_type_map": question_types,
        "answer_formats": unique_answer_formats,
        "answer_format_map": answer_format_map,
        "answer_format_counts": answer_format_counts,
        "answer_format_correct_counts": answer_format_correct_counts,
        "source_skills": source_skills,
        "source_skill_map": source_skill_map,
        "used_exercises": used_exercises,
        "used_exercise_map": used_exercise_map,
        "response_time_sec": response_time_map,
        "hint_used": hint_used_map,
        "rubric_hits": rubric_hits_map,
        "termination_reason": termination_reason,
        "early_terminated": early_terminated,
        "mastery_score_before": mastery_score_before,
    }
    sk["practice_history"].append(history_entry)

    # 更新连续失败
    if passed:
        sk["consecutive_failures"] = 0
        old_status = sk["status"]
        sk["status"] = "mastered"
        sk["dates"] = sk.get("dates", {})
        if "first_mastered" not in sk["dates"]:
            sk["dates"]["first_mastered"] = date.today().isoformat()
        sk["dates"]["last_practiced"] = date.today().isoformat()

        # 设置首次复习
        if "review" not in sk:
            sk["review"] = {}
        schedule = config.get("review_schedule", [1, 3, 7, 21, 60, 90])
        from datetime import timedelta
        sk["review"]["current_round"] = 0
        next_due = date.today() + timedelta(days=schedule[0])
        sk["review"]["next_due"] = next_due.isoformat()
        sk["review"]["fire_credits"] = 0.0
        session_cfg = config.get("mastery_score", {}).get("session", {})
        mastery_gain = (
            float(session_cfg.get("pass_base_gain", 0.16))
            + accuracy * float(session_cfg.get("pass_accuracy_weight", 0.12))
        )
        mastery_score_after = set_mastery_score(
            sk,
            config,
            max(
                mastery_score_before + mastery_gain,
                get_status_mastery_floor(config, "mastered"),
            ),
        )

        fire_awarded = []

        # 检查解锁
        newly_unlocked = check_unlockable(graph)
        for unlocked_id in newly_unlocked:
            set_mastery_score_from_status(
                graph["skills"][unlocked_id], config, "unlocked", preserve_higher=True
            )

    else:
        sk["consecutive_failures"] = sk.get("consecutive_failures", 0) + 1
        sk["status"] = "learning"
        sk["dates"] = sk.get("dates", {})
        sk["dates"]["last_practiced"] = date.today().isoformat()
        session_cfg = config.get("mastery_score", {}).get("session", {})
        mastery_penalty = (
            float(session_cfg.get("fail_base_penalty", 0.12))
            + (wrong_count / total if total > 0 else 0.0)
            * float(session_cfg.get("fail_wrong_ratio_weight", 0.2))
        )
        if early_terminated:
            mastery_penalty += float(session_cfg.get("early_termination_penalty", 0.06))
        mastery_score_after = set_mastery_score(
            sk,
            config,
            min(
                mastery_score_before - mastery_penalty,
                get_status_mastery_floor(config, "mastered") - 0.01,
            ),
        )
        fire_awarded = []
        newly_unlocked = []

    # 系统性薄弱判定
    systematic_weakness = [
        err_type for err_type, count in errors_by_type.items()
        if count >= 3
    ]

    adaptive_updates = _apply_adaptive_runtime_updates(
        graph=graph,
        config=config,
        skill_id=skill_id,
        answers=answers,
        metadata=metadata,
        passed=passed,
        accuracy=accuracy,
        errors_by_type=errors_by_type,
    )
    fire_awarded = adaptive_updates.get("fire_v2_applied", fire_awarded)
    mastery_score_after = get_mastery_score(sk, config)
    adaptive_prereq_flags = (
        adaptive_updates.get("failure", {})
        .get("applied", {})
        .get("prerequisites_flagged", [])
        if adaptive_updates.get("failure")
        else []
    )
    prerequisites_flagged = _dedupe_keep_order([*prerequisites_flagged, *adaptive_prereq_flags])

    result = {
        "skill_id": skill_id,
        "accuracy": accuracy,
        "correct": correct,
        "total": total,
        "planned_total": planned_total,
        "passed": passed,
        "mastery_status": "mastered" if passed else "learning",
        "errors": errors_by_type,
        "systematic_weakness": systematic_weakness,
        "consecutive_failures": sk.get("consecutive_failures", 0),
        "fire_awarded": fire_awarded,
        "newly_unlocked": newly_unlocked,
        "termination_reason": termination_reason,
        "early_terminated": early_terminated,
        "question_types": unique_question_types,
        "answer_formats": unique_answer_formats,
        "answer_format_counts": answer_format_counts,
        "source_skills": source_skills,
        "used_exercises": used_exercises,
        "mastery_score_before": mastery_score_before,
        "mastery_score_after": mastery_score_after,
        "events_recorded": adaptive_updates.get("events_recorded", 0),
        "adaptive_updates": adaptive_updates,
    }

    if passed:
        result["next_review"] = sk["review"]["next_due"]
    if prerequisites_flagged:
        result["prerequisites_flagged"] = prerequisites_flagged

    history_entry["mastery_score_after"] = mastery_score_after

    return result


def check_remediation(graph: dict, config: dict) -> list[dict]:
    """
    检查需要自动降级的技能点。
    
    规则一：连续2次未掌握 → 强制回示范
    规则二：连续3次未掌握 → 强制回概念课
    规则三：准确率 < 50% → 前置技能待验证（在 process_results 中已处理）
    """
    remediation_config = config.get("remediation", {})
    force_demo = remediation_config.get("force_demo_after_failures", 2)
    force_concept = remediation_config.get("force_concept_after_failures", 3)

    actions = []
    for sk_id, sk in graph["skills"].items():
        failures = sk.get("consecutive_failures", 0)
        if failures >= force_concept:
            actions.append({
                "skill_id": sk_id,
                "name": sk["name"],
                "failures": failures,
                "action": "force_concept",
                "message": f"连续 {failures} 次未掌握，强制回概念课",
            })
            sk["status"] = "unlocked"  # 重置到起点
            sk.get("dates", {}).pop("concept_completed", None)
            sk.get("dates", {}).pop("demo_completed", None)
            set_mastery_score_from_status(sk, config, "unlocked", preserve_higher=False)
        elif failures >= force_demo:
            actions.append({
                "skill_id": sk_id,
                "name": sk["name"],
                "failures": failures,
                "action": "force_demo",
                "message": f"连续 {failures} 次未掌握，强制回示范练习",
            })
            sk["status"] = "concept_done"
            sk.get("dates", {}).pop("demo_completed", None)
            set_mastery_score_from_status(sk, config, "concept_done", preserve_higher=False)

    return actions


# ─── CLI ────────────────────────────────────────────────────

@click.group()
def cli():
    """练习课管理"""
    pass


@cli.command()
@click.argument("skill_id")
def start(skill_id: str):
    """生成练习课配置"""
    graph = load_graph()
    config = load_config()

    plan = generate_session_plan(graph, config, skill_id)

    if plan.get("error"):
        console.print("[red]练习课无法开始：[/red]")
        for err in plan["error"]:
            console.print(f"   ❌ {err}")
        sys.exit(1)

    console.print(f"\n[bold]📝 练习课配置：{skill_id}[/bold]\n")
    console.print(f"   总题量：{plan['total_questions']}")
    console.print(f"   学科分级：{plan['classification']}类")
    console.print(f"   内容来源：{plan.get('content_source', 'blueprint_only')}")
    if plan.get("adaptive_runtime_enabled") and plan.get("recommended_task"):
        task = plan["recommended_task"]
        console.print(
            f"   自适应推荐：{task.get('task_type')}:{task.get('skill_id')} "
            f"（score {task.get('score', 0):.2f}）"
        )
    if plan.get("question_bank_loaded"):
        console.print(f"   题库命中：{plan.get('question_bank_selected_count', 0)}/{plan['total_questions']}\n")
    else:
        console.print()

    table = Table(box=box.SIMPLE, title="题目分配")
    table.add_column("技能点")
    table.add_column("题数", justify="right")
    table.add_column("类型")

    for alloc_skill, count in plan["allocation"].items():
        if alloc_skill == skill_id:
            type_str = "当前技能点"
        elif alloc_skill in plan.get("review_skills", []):
            type_str = "🔄 复习"
        else:
            type_str = "📘 近期"
        table.add_row(alloc_skill, str(count), type_str)

    console.print(table)

    format_targets = plan.get("answer_format_targets", {})
    if format_targets:
        format_table = Table(box=box.SIMPLE, title="作答形式配额")
        format_table.add_column("形式")
        format_table.add_column("题数", justify="right")
        for answer_format, count in format_targets.items():
            format_table.add_row(answer_format, str(count))
        console.print(format_table)

    question_plan = plan.get("question_plan", [])
    if question_plan:
        blueprint_table = Table(box=box.SIMPLE, title="逐题蓝图")
        blueprint_table.add_column("#", justify="right")
        blueprint_table.add_column("技能点")
        blueprint_table.add_column("题型")
        blueprint_table.add_column("形式")
        blueprint_table.add_column("题库ID")
        blueprint_table.add_column("家族")
        for item in question_plan:
            blueprint_table.add_row(
                str(item["question_index"]),
                ",".join(item.get("source_skills", [item["skill_id"]])),
                item["question_type"],
                item["answer_format"],
                item.get("bank_entry_id", "—"),
                item.get("family", "—"),
            )
        console.print(blueprint_table)

    priority_items = plan.get("candidate_priorities", [])
    if priority_items:
        priority_table = Table(box=box.SIMPLE, title="候选技能优先级")
        priority_table.add_column("技能点")
        priority_table.add_column("分数", justify="right")
        priority_table.add_column("掌握度", justify="right")
        priority_table.add_column("标签")
        priority_table.add_column("首要原因")
        for item in priority_items:
            priority_table.add_row(
                item["skill_id"],
                f"{item['score']:.2f}",
                f"{item.get('mastery_score', 0):.0%}",
                ", ".join(item.get("tags", [])) or "—",
                item.get("reasons", ["—"])[0],
            )
        console.print(priority_table)

    # 绑定习题信息（A/D 类）
    bound = plan.get("bound_exercises")
    if bound:
        console.print("\n[bold]📖 绑定习题：[/bold]")
        for bsk_id, binfo in bound.items():
            if binfo.get("shortage", 0) > 0:
                console.print(f"   [yellow]⚠️ {bsk_id}：{binfo['warning']}[/yellow]")
            exercises = binfo.get("exercises", [])
            if exercises:
                console.print(f"   {bsk_id}：{', '.join(exercises[:5])}")

    # 输出 JSON 供 Claude Code 解析
    console.print(f"\n[dim]JSON 输出（供系统解析）：[/dim]")
    console.print(json.dumps(plan, ensure_ascii=False, indent=2))
    console.print()


@cli.command()
@click.argument("skill_id")
@click.argument("answers_json")
def result(skill_id: str, answers_json: str):
    """记录练习课结果

    ANSWERS_JSON 兼容：
    1. 旧格式：'{"1":"correct","2":"wrong:conceptual"}'
    2. 新格式：'{"answers": {...}, "planned_total": 8, "answer_format": {"1":"short_answer"}, ...}'
    """
    graph = load_graph()
    config = load_config()

    try:
        raw_payload = json.loads(answers_json)
        answers, metadata = parse_result_payload(raw_payload)
        _, event_metadata = parse_event_result_payload(raw_payload)
        for key in (
            "question_types",
            "answer_format",
            "source_skill",
            "used_exercise_map",
            "response_time_sec",
            "hint_used",
            "rubric_hits",
            "evidence_maps",
            "session_id",
        ):
            value = event_metadata.get(key)
            if value:
                metadata[key] = value
        metadata["used_exercises"] = _dedupe_keep_order(
            [
                *metadata.get("used_exercises", []),
                *event_metadata.get("used_exercises", []),
            ]
        )
        metadata = enrich_metadata_from_question_ids(metadata)
    except (json.JSONDecodeError, ValueError) as exc:
        console.print("[red]错误：答案 JSON 格式无效[/red]")
        console.print(f"   {exc}")
        sys.exit(1)

    result = process_results(graph, config, skill_id, answers, metadata)

    # 检查自动降级
    remediation_actions = check_remediation(graph, config)

    save_graph(graph)

    # 输出结果
    if result["passed"]:
        console.print(f"\n[green]✅ {skill_id} 练习课完成——掌握！[/green]")
    else:
        console.print(f"\n[red]❌ {skill_id} 练习课完成——未掌握[/red]")

    console.print(f"   准确率：{result['correct']}/{result['total']}（{result['accuracy']:.0%}）")
    console.print(
        f"   掌握度：{result['mastery_score_before']:.0%} → {result['mastery_score_after']:.0%}"
    )
    if result["planned_total"] != result["total"]:
        console.print(f"   已完成题数：{result['total']}/{result['planned_total']}")

    if result["errors"]:
        console.print(f"   错误分布：")
        for err_type, count in result["errors"].items():
            console.print(f"     {err_type}：{count} 次")

    if result.get("termination_reason") != "completed":
        console.print(f"   结束原因：{result['termination_reason']}")

    if result.get("systematic_weakness"):
        console.print(f"   [yellow]⚠️ 系统性薄弱：{', '.join(result['systematic_weakness'])}[/yellow]")

    if result.get("next_review"):
        console.print(f"   下次复习：{result['next_review']}")

    if result.get("prerequisites_flagged"):
        console.print(
            f"   [yellow]⚠️ 前置技能待验证：{', '.join(result['prerequisites_flagged'])}[/yellow]"
        )

    fire = result.get("fire_awarded", [])
    if fire:
        console.print(f"   FIRe 学分：")
        for f in fire:
            total_credit = f.get("total", f.get("after", 0.0))
            console.print(f"     {f['skill_id']}：+{f['credit']:.2f}（累计 {total_credit:.2f}）")

    if result.get("events_recorded"):
        console.print(f"   事件日志：写入 {result['events_recorded']} 条 item-level evidence")

    unlocked = result.get("newly_unlocked", [])
    if unlocked:
        console.print(f"   [cyan]🔓 新解锁：{', '.join(unlocked)}[/cyan]")

    if remediation_actions:
        console.print(f"\n[bold red]⚠️ 自动降级触发：[/bold red]")
        for action in remediation_actions:
            console.print(f"   {action['skill_id']}：{action['message']}")

    # JSON 输出
    console.print(f"\n[dim]JSON 输出：[/dim]")
    output = {**result, "remediation": remediation_actions}
    console.print(json.dumps(output, ensure_ascii=False, indent=2))
    console.print()


@cli.command()
def remediation():
    """检查需要自动降级的技能点"""
    graph = load_graph()
    config = load_config()

    actions = check_remediation(graph, config)

    if not actions:
        console.print("[green]✨ 没有需要自动降级的技能点[/green]")
        return

    save_graph(graph)

    console.print(f"\n[bold red]⚠️ 自动降级：{len(actions)} 个技能点[/bold red]\n")
    for action in actions:
        icon = "📕" if action["action"] == "force_concept" else "📘"
        console.print(f"   {icon} {action['skill_id']}：{action['message']}")
    console.print()


if __name__ == "__main__":
    cli()
