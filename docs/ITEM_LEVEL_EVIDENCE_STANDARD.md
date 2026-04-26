# Item-Level Evidence Standard

Adaptive algorithms should update from item-level evidence, not session-level
summaries alone. Each answer event should say what was measured, how strong the
evidence was, and how the learner responded.

## Event Shape

Events are JSONL rows under:

```text
scripts/data/events/YYYY-MM-DD.jsonl
```

Recommended answer event:

```json
{
  "event_id": "uuid",
  "timestamp": "2026-04-26T10:31:00+08:00",
  "event_type": "answer_submitted",
  "session_skill_id": "SK-001",
  "skill_id": "SK-001",
  "question_id": "SK-001-Q03",
  "result": "wrong",
  "raw_result": "wrong:boundary",
  "error_type": "boundary",
  "skill_vector": {
    "SK-001": 1.0
  },
  "misconception_targets": ["boundary"],
  "difficulty_param": 0.65,
  "discrimination": 1.1,
  "expected_time_sec": 120,
  "response_time_sec": 95,
  "hint_used": true,
  "rubric_hits": ["missed_boundary_reason"]
}
```

## Evidence Fields

- `skill_vector`: which skills the item measures and with what weight
- `target_edges`: graph relationships the item probes
- `misconception_targets`: error patterns the item can reveal
- `difficulty_param`: item difficulty in `[0, 1]`
- `discrimination`: how much the item separates mastery from non-mastery
- `expected_time_sec`: expected unaided response time
- `response_time_sec`: learner response time
- `hint_used`: whether the answer required a hint
- `rubric_hits`: rubric signals observed by a grader or model

## Template Rule

Question banks should hold stable item metadata. Events should copy that
metadata into the answer row at submission time. This makes old evidence
replayable even if the question bank changes later.

The event schema lives at:

```text
scripts/content/schema/event_log.schema.json
```
