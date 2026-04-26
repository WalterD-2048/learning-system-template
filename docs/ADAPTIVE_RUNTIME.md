# Adaptive Runtime

This template now has an end-to-end adaptive loop:

```text
diagnose -> rank task -> plan session -> answer -> log event -> update student model -> apply FIRe/remediation -> rank next task
```

## Runtime Pieces

- `engine.diagnostic` estimates the current knowledge frontier and can write diagnostic evidence back into state.
- `engine.task_selection` ranks candidate tasks by expected gain, retention pressure, frontier value, FIRe value, and risk.
- `engine.session start` uses the adaptive task ranking to build a practice allocation and item blueprint.
- `engine.session result` writes item-level events, updates the richer student model, applies FIRe v2 on success, and applies graph-aware remediation on failure.
- `engine.event_log` keeps append-only answer evidence in `scripts/data/events/*.jsonl`.

## Recommended Flow

From `scripts/`:

```bash
python -m engine.validate all
python -m engine.diagnostic status
python -m engine.diagnostic apply '{"SK-001":"mastered","SK-002":"wrong:prerequisite"}'
python -m engine.task_selection next --target SK-003
python -m engine.session start SK-001
python -m engine.session result SK-001 '{"answers":{"1":"correct","2":"correct","3":"wrong:boundary","4":"correct"},"planned_total":4,"question_id":{"1":"SK-001-Q01","2":"SK-001-Q02","3":"SK-001-Q03","4":"SK-001-Q04"},"response_time_sec":{"1":45,"2":80,"3":120,"4":70}}'
```

Use `mastered`, `known`, or `skip` in diagnostic results only when a diagnostic item is strong enough to skip a skill. Use `correct`, `wrong:<error_type>`, or `partial:<error_type>` for ordinary probes.

## What Gets Updated

`session result` updates:

- `practice_history` for compatibility with existing analytics.
- `student_model` fields: `mastery_p`, `retrievability`, `stability_days`, `automaticity`, `uncertainty`, and error counts.
- Legacy `mastery_score`, derived from the student model for existing UI and reports.
- `review.fire_credits` and implicit component student models through FIRe v2.
- `needs_validation` and uncertainty for prerequisite/dependent skills after failures.

## Template Porting Checklist

When creating a concrete learning system from this template:

- Replace `skill_graph.json`, `graph.nodes.json`, and `graph.edges.json` together.
- Add `encompasses` edges separately from `prerequisite` edges; FIRe v2 follows `encompasses`, not every prerequisite.
- Give each question a `skill_vector`, `difficulty_param`, `discrimination`, `expected_time_sec`, and `misconception_targets`.
- Keep `adaptive_runtime.enabled` on unless debugging the legacy planner.
- Run `python -m engine.validate all` and `python -m engine.graph_audit run --strict` before using the system with real learners.
