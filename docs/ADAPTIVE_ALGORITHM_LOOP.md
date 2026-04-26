# Adaptive Algorithm Loop

This template now separates the adaptive learning loop into four auditable
layers:

```text
item evidence -> student model -> FIRe / failure propagation -> task selection
```

Each layer is intentionally small and replaceable. Course-specific projects can
start with these heuristics, then recalibrate weights after enough event data
exists.

## 1. Item Evidence

Question banks should describe what each item measures:

- `skill_vector`: skill attribution weights
- `target_edges`: graph relationships probed by the item
- `misconception_targets`: errors the item can expose
- `difficulty_param`: difficulty in `[0, 1]`
- `discrimination`: evidence strength
- `expected_time_sec`: expected unaided response time

`engine.event_log` copies stable item metadata into every answer event. This
keeps historical evidence replayable even if the question bank changes later.

## 2. Student Model

`engine.student_model` keeps the legacy `mastery_score` compatible while
maintaining richer fields:

- `mastery_p`
- `retrievability`
- `stability_days`
- `automaticity`
- `uncertainty`
- `error_counts`

The model update now handles:

- correct, partial, and wrong answers
- hint usage
- response speed against expected time
- item difficulty and discrimination
- multi-skill updates from `skill_vector`
- fractional implicit review from FIRe

Useful commands:

```bash
python3 -m engine.student_model init --mastery-score 0.45
python3 -m engine.student_model update '{"mastery_p":0.45}' '{"skill_weight":1,"difficulty_param":0.7,"discrimination":1.2}' '{"result":"correct","response_time_sec":60,"expected_time_sec":90}'
python3 -m engine.student_model update-event '{}' '{"event_type":"answer_submitted","skill_id":"SK-003","result":"partial","skill_vector":{"SK-003":0.8,"SK-002":0.2}}'
```

## 3. FIRe And Failure Propagation

`engine.fire` uses typed graph edges:

- `encompasses` / `component_of` determine implicit review flow
- `remediates` maps error nodes to repair skills
- `confusable_with` supports contrast-practice suggestions
- `prerequisite` identifies skills to validate after failure

Successful work awards fractional implicit review. The award is discounted when
the component was reviewed too recently, and it can update both
`review.fire_credits` and the richer `student_model`.

Failure does not award credit. It produces a structured preview:

- prerequisites to validate
- dependents whose uncertainty should increase
- confusable skills to contrast
- ranked remediation targets

Useful commands:

```bash
python3 -m engine.fire preview SK-003 --quality 0.9
python3 -m engine.fire apply SK-003 --quality 0.9
python3 -m engine.fire failure SK-003 --error prerequisite --error transfer
```

## 4. Task Selection

`engine.task_selection` ranks candidate tasks by expected value per minute.
It now considers:

- expected mastery gain
- forgetting risk reduction
- implicit FIRe gain
- frontier value
- diagnostic information gain
- prerequisite stabilization
- graph-derived remediation value
- interference, frustration, and redundancy risk

The selector also aggregates recent error counts through `ERR-* -> skill`
`remediates` edges, so a failure on one skill can promote a different repair
skill.

Useful commands:

```bash
python3 -m engine.task_selection next
python3 -m engine.task_selection next --target SK-003 --json-output
python3 -m engine.task_selection explain SK-002
```

## Template Release Rule

Before copying this template into a concrete course, run:

```bash
python3 -m py_compile engine/graph.py engine/graph_audit.py engine/event_log.py engine/student_model.py engine/fire.py engine/task_selection.py engine/validate.py
python3 -m engine.graph_audit run --strict
python3 -m engine.validate all
python3 -m engine.task_selection next --json-output
```

Before shipping a course to learners, inspect task-selection output manually.
The algorithm should be explainable enough that a course author can tell why
the next task was selected.
