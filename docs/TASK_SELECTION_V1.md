# Task Selection v1

`engine.task_selection` ranks next learning tasks without changing the current
session planner. It turns the graph and student model into explainable task
scores that can later replace the older session-local candidate priority logic.

## Commands

Run from `scripts/`.

```bash
python3 -m engine.task_selection next
python3 -m engine.task_selection next --target SK-002
python3 -m engine.task_selection explain SK-001
python3 -m engine.task_selection next --json-output
```

## Candidate Tasks

The selector can emit these task types:

- `learn`: a skill is unlocked or concept-ready
- `practice`: a skill has passed demo or is already in learning
- `review`: a mastered skill is due or has low retrievability
- `validate`: a skill needs validation, often because a prerequisite was suspect
- `remediate`: recent errors or model error counts suggest targeted repair
- `frontier_probe`: a locked skill is close enough to the knowledge frontier to probe
- `strengthen`: a mastered skill is still uncertain or weak

## Score Shape

Each task exposes a score and the component values that produced it:

```text
score(task) =
  weighted_learning_value
  - weighted_risk
  -------------------------------- * 10
       estimated_minutes
```

Positive components:

- `expected_mastery_gain`
- `forgetting_risk_reduction`
- `implicit_fire_gain`
- `frontier_value`
- `diagnostic_information_gain`
- `prerequisite_stabilization`

Risk components:

- `interference_penalty`
- `frustration_risk`
- `redundancy_penalty`

This is still a heuristic model, but it is more auditable than a flat priority
sum: every recommendation carries the reasons and penalties that created it.

## Integration Path

The safe integration order is:

1. Keep `engine.session start` unchanged.
2. Use `engine.task_selection next --json-output` as a planning preview.
3. Compare its top task with the current `candidate_priorities` output.
4. Once stable, let `session.py` ask this module for ranked source skills.
5. Later, feed item-level evidence from `engine.event_log` back into
   `engine.student_model` before every selection run.

The module is read-only today. It does not mutate `skill_graph.json`, review
state, or event logs.
