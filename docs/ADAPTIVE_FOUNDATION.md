# Adaptive Foundation

This document records the first engineering step toward a stronger adaptive
learning engine. The goal is not to replace the current workflow yet; it is to
make the data layer auditable enough for typed knowledge graphs, diagnostics,
student modeling, and FIRe v2.

## New Commands

Run these from `scripts/`.

```bash
python3 -m engine.validate all
python3 -m engine.validate all --strict
python3 -m engine.event_log from-session SK-001 '{"answers":{"1":"correct","2":"wrong:boundary"}}'
python3 -m engine.event_log tail
python3 -m engine.student_model init --mastery-score 0.45
```

`engine.validate all` reports structural errors and content-readiness warnings.
Use `--strict` when a real course should fail on missing question banks,
rubrics, coverage types, or bridge items.

## Item-Level Evidence

Answer evidence should be written as JSONL under:

```text
scripts/data/events/YYYY-MM-DD.jsonl
```

Each answer event uses this shape:

```json
{
  "event_id": "uuid",
  "timestamp": "2026-04-26T10:31:00+08:00",
  "event_type": "answer_submitted",
  "session_skill_id": "SK-001",
  "skill_id": "SK-001",
  "question_id": "SK-001-Q01",
  "result": "wrong",
  "raw_result": "wrong:boundary",
  "error_type": "boundary",
  "response_time_sec": 84,
  "hint_used": false,
  "rubric_hits": ["missed_boundary"]
}
```

The existing `practice_history` remains the compact derived summary. Event logs
are the raw replayable evidence layer.

## Question Measurement Fields

Question bank entries can now include optional measurement fields:

```json
{
  "skill_vector": {
    "SK-001": 0.8,
    "SK-003": 0.2
  },
  "misconception_targets": ["boundary"],
  "difficulty_param": 0.57,
  "discrimination": 0.82,
  "expected_time_sec": 90,
  "requires_automaticity": false,
  "allowed_hints": 1,
  "variant_family": "linear-equation-isolation-v2",
  "surface_similarity_group": "avoid-near-duplicate-04"
}
```

These fields let future updates distinguish simple recognition, transfer,
automaticity, and prerequisite evidence instead of treating every item as equal.

## Student Model Compatibility

`engine.student_model` keeps `mastery_score` as a derived compatibility field
while adding:

```text
mastery_p
retrievability
stability_days
automaticity
uncertainty
evidence_count
last_evidence_at
last_success_at
error_counts
```

The current state files do not need to be migrated immediately. New model
fields can be adopted skill by skill.
