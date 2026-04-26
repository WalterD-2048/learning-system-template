# Knowledge Graph v2

The template now supports a typed knowledge graph layer beside the legacy
`skill_graph.json`. Existing tools can still read `skills` and
`prerequisites`; newer adaptive modules can read richer typed nodes and edges.

## Files

```text
scripts/data/skill_graph.json     # legacy state and compatibility source
scripts/data/graph.nodes.json     # typed graph nodes
scripts/data/graph.edges.json     # typed graph edges
```

`skill_graph.json` remains the current state file. The v2 files are intended
for graph design, audit, FIRe v2, diagnostics, task selection, and analytics.

## Node Types

- `skill`: a learnable unit, ideally micro-sized
- `concept`: a conceptual object that may span multiple skills
- `misconception`: an error pattern or misconception node
- `question`: an assessable item
- `source_anchor`: a precise textbook, video, formula, example, or document span
- `learning_objective`: a higher-level objective that can group skills

## Edge Types

- `prerequisite`: controls unlock readiness
- `encompasses`: practicing the source implicitly reviews the target
- `component_of`: inverse form of `encompasses`
- `confusable_with`: skills likely to interfere
- `remediates`: an error or misconception points to the repair skill
- `transfers_to`: a skill supports transfer into another context
- `source_anchor`: a node is grounded in source material
- `assessed_by`: a skill is measured by a question
- `variant_of`: a question is a variant of another item or family

The most important distinction is:

```text
prerequisite controls readiness
encompasses controls implicit review
```

Do not use prerequisite edges as a proxy for FIRe credit.

## Edge Metadata

Every important edge should eventually carry:

```json
{
  "from": "SK-002",
  "to": "SK-001",
  "type": "encompasses",
  "weight": 0.35,
  "confidence": 0.75,
  "used_by": ["fire", "task_selection"]
}
```

`weight` means different things by edge type:

- `prerequisite`: strength or necessity of the prerequisite
- `encompasses`: fractional implicit review credit
- `assessed_by`: how strongly a question measures the skill
- `confusable_with`: likely interference strength
- `remediates`: repair strength from error node to skill

## Template Rule

A copied course should pass this command before serious use:

```bash
python3 -m engine.graph_audit run --strict
```

Warnings are acceptable during early authoring. Before release, each skill
should have source grounding, assessment coverage, and clear graph edges.
