"""
Append-only item-level event logging for learning sessions.

This module keeps raw answer evidence separate from derived skill state so
future student models can replay, audit, and recalibrate learning updates.
"""

import json
import sys
import uuid
from datetime import datetime
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
CONTENT_DIR = Path(__file__).parent.parent / "content"
EVENT_DIR = DATA_DIR / "events"
QUESTION_BANK_DIR = CONTENT_DIR / "question_banks"

ANSWER_EVENT_TYPE = "answer_submitted"
ITEM_EVIDENCE_FIELDS = {
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
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def event_path_for(timestamp: str) -> Path:
    return EVENT_DIR / f"{timestamp[:10]}.jsonl"


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _normalize_map(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items()}


def _normalize_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    return [raw]


def _evidence_maps(raw_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    maps: dict[str, dict[str, Any]] = {}
    for field in ITEM_EVIDENCE_FIELDS:
        maps[field] = _normalize_map(raw_payload.get(field))
    return maps


def _normalize_used_exercises(raw: Any) -> list[str]:
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


def load_question_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not QUESTION_BANK_DIR.exists():
        return index
    for path in sorted(QUESTION_BANK_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for entry in payload.get("entries", []):
            if isinstance(entry, dict) and entry.get("id"):
                index[str(entry["id"])] = entry
    return index


def item_evidence(entry: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    evidence = {
        field: entry[field]
        for field in ITEM_EVIDENCE_FIELDS
        if entry.get(field) is not None
    }
    if "target_edge" in evidence and "target_edges" not in evidence:
        evidence["target_edges"] = [evidence.pop("target_edge")]
    return evidence


def enrich_answer_event(
    event: dict[str, Any],
    question_index: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    question_index = question_index if question_index is not None else load_question_index()
    enriched = dict(event)
    enriched.update({
        key: value
        for key, value in item_evidence(question_index.get(str(event.get("question_id", "")))).items()
        if key not in enriched
    })
    if "target_edge" in enriched and "target_edges" not in enriched:
        enriched["target_edges"] = [enriched.pop("target_edge")]
    return enriched


def parse_answer_result(raw_result: str) -> tuple[str, Optional[str]]:
    value = str(raw_result).strip()
    if value == "correct":
        return "correct", None
    if value == "wrong":
        return "wrong", "unspecified"
    if value.startswith("wrong:"):
        error_type = value.split(":", 1)[1].strip() or "unspecified"
        return "wrong", error_type
    if value.startswith("partial:"):
        error_type = value.split(":", 1)[1].strip() or None
        return "partial", error_type
    return value, None


def parse_result_payload(raw_payload: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    """
    Parse the same answer payload shapes accepted by engine.session.result.
    """
    if not isinstance(raw_payload, dict):
        raise ValueError("answer payload must be an object")

    question_types: dict[str, Any] = {}
    answer_formats: dict[str, Any] = {}
    source_skills: dict[str, Any] = {}
    used_exercise_map: dict[str, Any] = {}
    response_times: dict[str, Any] = {}
    hint_used: dict[str, Any] = {}
    rubric_hits: dict[str, Any] = {}
    evidence_maps: dict[str, dict[str, Any]] = {}
    used_exercises: list[str] = []

    if "questions" in raw_payload:
        questions = raw_payload.get("questions")
        if not isinstance(questions, dict):
            raise ValueError("questions must be an object")
        answers: dict[str, str] = {}
        for question_num, question_data in questions.items():
            q_key = str(question_num)
            if isinstance(question_data, str):
                answers[q_key] = question_data
                continue
            if not isinstance(question_data, dict):
                raise ValueError("each questions item must be a string or object")
            result = question_data.get("result")
            if not isinstance(result, str):
                raise ValueError(f"questions[{q_key}].result is required")
            answers[q_key] = result
            if question_data.get("question_type") is not None:
                question_types[q_key] = question_data["question_type"]
            if question_data.get("answer_format") is not None:
                answer_formats[q_key] = question_data["answer_format"]
            if question_data.get("source_skill") is not None:
                source_skills[q_key] = question_data["source_skill"]
            if question_data.get("used_exercise") is not None:
                used_exercise_map[q_key] = question_data["used_exercise"]
            if question_data.get("question_id") is not None:
                used_exercise_map[q_key] = question_data["question_id"]
            if question_data.get("response_time_sec") is not None:
                response_times[q_key] = question_data["response_time_sec"]
            if question_data.get("hint_used") is not None:
                hint_used[q_key] = question_data["hint_used"]
            if question_data.get("rubric_hits") is not None:
                rubric_hits[q_key] = question_data["rubric_hits"]
            for field in ITEM_EVIDENCE_FIELDS:
                if question_data.get(field) is not None:
                    evidence_maps.setdefault(field, {})[q_key] = question_data[field]
            used_exercises.extend(
                _normalize_used_exercises(
                    question_data.get("used_exercises", question_data.get("used_exercise"))
                )
            )
    elif "answers" in raw_payload:
        answers = {str(key): str(value) for key, value in _normalize_map(raw_payload["answers"]).items()}
        question_types = _normalize_map(raw_payload.get("question_types"))
        answer_formats = _normalize_map(raw_payload.get("answer_format"))
        source_skills = _normalize_map(raw_payload.get("source_skill"))
        used_exercise_map = _normalize_map(
            raw_payload.get("used_exercise_map", raw_payload.get("question_id"))
        )
        response_times = _normalize_map(raw_payload.get("response_time_sec"))
        hint_used = _normalize_map(raw_payload.get("hint_used"))
        rubric_hits = _normalize_map(raw_payload.get("rubric_hits"))
        evidence_maps = _evidence_maps(raw_payload)
        used_exercises = _normalize_used_exercises(raw_payload.get("used_exercises"))
    else:
        answers = {str(key): str(value) for key, value in raw_payload.items()}

    if not answers:
        raise ValueError("answers cannot be empty")

    metadata = {
        "question_types": question_types,
        "answer_format": answer_formats,
        "source_skill": source_skills,
        "used_exercise_map": used_exercise_map,
        "used_exercises": _dedupe_keep_order(used_exercises),
        "response_time_sec": response_times,
        "hint_used": hint_used,
        "rubric_hits": rubric_hits,
        "evidence_maps": evidence_maps,
        "session_id": raw_payload.get("session_id"),
    }
    return answers, metadata


def append_event(event_type: str, payload: dict[str, Any], timestamp: Optional[str] = None) -> dict[str, Any]:
    timestamp = timestamp or now_iso()
    event = {
        "event_id": str(uuid.uuid4()),
        "timestamp": timestamp,
        "event_type": event_type,
        **payload,
    }
    EVENT_DIR.mkdir(parents=True, exist_ok=True)
    with open(event_path_for(timestamp), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def build_answer_events(
    session_skill_id: str,
    answers: dict[str, str],
    metadata: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    metadata = metadata or {}
    question_types = _normalize_map(metadata.get("question_types"))
    answer_formats = _normalize_map(metadata.get("answer_format"))
    source_skills = _normalize_map(metadata.get("source_skill"))
    used_exercise_map = _normalize_map(metadata.get("used_exercise_map"))
    response_times = _normalize_map(metadata.get("response_time_sec"))
    hint_used = _normalize_map(metadata.get("hint_used"))
    rubric_hits = _normalize_map(metadata.get("rubric_hits"))
    evidence_maps = {
        field: _normalize_map(values)
        for field, values in _normalize_map(metadata.get("evidence_maps")).items()
    }
    used_exercises = _normalize_used_exercises(metadata.get("used_exercises"))
    session_id = metadata.get("session_id")

    ordered_question_nums = sorted(answers.keys(), key=lambda item: (not str(item).isdigit(), str(item)))
    events = []
    for index, question_num in enumerate(ordered_question_nums):
        raw_result = str(answers[question_num])
        result, error_type = parse_answer_result(raw_result)
        question_id = used_exercise_map.get(question_num)
        if question_id is None and index < len(used_exercises):
            question_id = used_exercises[index]
        if question_id is None:
            question_id = question_num

        event = {
            "session_id": session_id,
            "session_skill_id": session_skill_id,
            "skill_id": str(source_skills.get(question_num, session_skill_id)),
            "question_index": str(question_num),
            "question_id": str(question_id),
            "result": result,
            "raw_result": raw_result,
            "error_type": error_type,
            "question_type": question_types.get(question_num),
            "answer_format": answer_formats.get(question_num),
            "response_time_sec": response_times.get(question_num),
            "hint_used": hint_used.get(question_num),
            "rubric_hits": _normalize_list(rubric_hits.get(question_num)),
        }
        for field, values in evidence_maps.items():
            if values.get(question_num) is not None:
                event[field] = values[question_num]
        events.append({key: value for key, value in event.items() if value is not None})
    return events


def append_answer_events(
    session_skill_id: str,
    answers: dict[str, str],
    metadata: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    question_index = load_question_index()
    return [
        append_event(ANSWER_EVENT_TYPE, enrich_answer_event(event, question_index))
        for event in build_answer_events(session_skill_id, answers, metadata)
    ]


def read_events(limit: int = 20) -> list[dict[str, Any]]:
    if not EVENT_DIR.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(EVENT_DIR.glob("*.jsonl")):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
    return rows[-limit:]


@click.group()
def cli():
    """Item-level event log utilities."""


@cli.command("record-answer")
@click.argument("skill_id")
@click.argument("question_id")
@click.argument("result")
@click.option("--session-id", default=None)
@click.option("--session-skill-id", default=None)
@click.option("--error-type", default=None)
@click.option("--question-type", default=None)
@click.option("--answer-format", default=None)
@click.option("--response-time-sec", type=float, default=None)
@click.option("--hint-used", type=bool, default=None)
@click.option("--rubric-hit", multiple=True)
def record_answer(
    skill_id: str,
    question_id: str,
    result: str,
    session_id: Optional[str],
    session_skill_id: Optional[str],
    error_type: Optional[str],
    question_type: Optional[str],
    answer_format: Optional[str],
    response_time_sec: Optional[float],
    hint_used: Optional[bool],
    rubric_hit: tuple[str, ...],
):
    """Append one answer_submitted event."""
    normalized_result, parsed_error_type = parse_answer_result(result)
    payload = enrich_answer_event(
        {
            "session_id": session_id,
            "session_skill_id": session_skill_id or skill_id,
            "skill_id": skill_id,
            "question_id": question_id,
            "result": normalized_result,
            "raw_result": result,
            "error_type": error_type or parsed_error_type,
            "question_type": question_type,
            "answer_format": answer_format,
            "response_time_sec": response_time_sec,
            "hint_used": hint_used,
            "rubric_hits": list(rubric_hit),
        }
    )
    event = append_event(
        ANSWER_EVENT_TYPE,
        payload,
    )
    console.print(json.dumps(event, ensure_ascii=False, indent=2))


@cli.command("from-session")
@click.argument("skill_id")
@click.argument("answers_json")
def from_session(skill_id: str, answers_json: str):
    """Append answer events from a session-style answers JSON payload."""
    try:
        raw_payload = json.loads(answers_json)
        answers, metadata = parse_result_payload(raw_payload)
    except (json.JSONDecodeError, ValueError) as exc:
        console.print(f"[red]Invalid answer payload:[/red] {exc}")
        sys.exit(1)

    events = append_answer_events(skill_id, answers, metadata)
    console.print(f"[green]Recorded {len(events)} answer events[/green]")
    console.print(json.dumps(events, ensure_ascii=False, indent=2))


@cli.command("tail")
@click.option("--limit", type=int, default=20)
def tail(limit: int):
    """Show recent events."""
    events = read_events(limit)
    if not events:
        console.print("[dim]No events recorded yet[/dim]")
        return

    table = Table(box=box.SIMPLE)
    table.add_column("timestamp")
    table.add_column("event")
    table.add_column("skill")
    table.add_column("question")
    table.add_column("result")
    for event in events:
        table.add_row(
            str(event.get("timestamp", "")),
            str(event.get("event_type", "")),
            str(event.get("skill_id", "")),
            str(event.get("question_id", "")),
            str(event.get("result", "")),
        )
    console.print(table)


if __name__ == "__main__":
    cli()
