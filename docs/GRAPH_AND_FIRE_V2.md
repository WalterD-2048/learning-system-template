# Typed Graph And FIRe v2

This is the next layer after the adaptive foundation PR. It adds typed graph
helpers and a FIRe v2 implementation that can run beside the existing review
logic without changing current behavior.

## Edge Semantics

Legacy skill prerequisites still work:

```json
{
  "skills": {
    "SK-002": {
      "prerequisites": ["SK-001"]
    }
  }
}
```

Typed graph edges can now be added at the top level:

```json
{
  "edges": [
    {
      "from": "SK-001",
      "to": "SK-002",
      "type": "prerequisite",
      "weight": 1.0
    },
    {
      "from": "SK-002",
      "to": "SK-001",
      "type": "encompasses",
      "weight": 0.35
    },
    {
      "from": "SK-007",
      "to": "SK-008",
      "type": "confusable_with",
      "weight": 0.6
    }
  ]
}
```

`prerequisite` controls unlock readiness. `encompasses` controls implicit
review flow. These should not be treated as the same relationship.

## Commands

Run from `scripts/`.

```bash
python3 -m engine.graph edges
python3 -m engine.graph edges --type prerequisite
python3 -m engine.graph components SK-002
python3 -m engine.fire preview SK-002 --quality 0.9
python3 -m engine.fire failure SK-002 --error boundary
```

`engine.fire apply SK-002` mutates `review.fire_credits` on component skills.
Use it only when you deliberately want to write FIRe v2 credits into the graph.

## FIRe v2 Flow

When a learner succeeds on a skill, FIRe v2 traverses typed component edges:

```text
SK-Advanced --encompasses:0.35--> SK-Component
```

Credit is fractional:

```text
credit = quality * edge_weight * depth_decay^depth
```

This allows multi-hop implicit review while avoiding the old problem of giving
every direct prerequisite a fixed credit.

## Failure Flow

Failures do not award FIRe credit. Instead, `engine.fire failure` previews:

- prerequisites that may need validation
- dependent skills whose certainty should be reduced later
- confusable skills that may need contrast practice
- remediation targets if error nodes are present in the graph

The current module only previews these actions. Future integration can connect
them to `student_model.uncertainty`, `needs_validation`, and task selection.
