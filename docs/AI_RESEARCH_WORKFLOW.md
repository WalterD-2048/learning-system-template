# AI Research Workflow

这份文档定义基于本模板开发具体科目学习系统时的最终目标、AI 自主探索边界、科研实验流程，以及每个环节的独立 agent 检查制度。

## Final Goal

最终目标不是“生成一套题库”或“把教材拆成技能点”，而是构建一个**可验证、可迭代、可复现实验过程下形成的自适应学习系统**。

一个具体科目项目完成时，应同时满足：

- `knowledge graph` 能解释技能、前置、隐式复习、混淆、补救和来源锚点。
- `student model` 能基于逐题证据更新掌握概率、可回忆度、稳定度、自动化程度和不确定性。
- `diagnostic` 能定位学习者的 knowledge frontier 和 foundation gaps。
- `task selection` 能解释为什么下一步应该学、练、复习、验证或补救某个技能。
- `question bank` 能作为测量工具，而不只是题目列表。
- `rubrics` 能把错误映射到 misconception、edge 或 prerequisite。
- `event log` 能支持回放、审计和模型重算。
- `analytics` 能给出可行动的教学和系统改进建议。

因此，项目交付物至少包括：

- 课程目标与范围说明。
- typed knowledge graph。
- 题库、rubric、诊断题和来源锚点。
- 自适应运行配置。
- 试运行事件日志或模拟日志。
- 校验报告、实验记录和改进记录。

## AI Autonomy Rule

AI 可以自主探索解决方案，但必须在研究协议内行动。

AI 可以自主做：

- 拆解课程目标和候选技能点。
- 比较多种图谱结构。
- 设计诊断题、练习题和 rubric 草案。
- 提出 task selection 参数和 FIRe 边权重。
- 运行校验、模拟练习和分析。
- 根据证据迭代图谱、题库和配置。

AI 不可以跳过：

- 明确假设。
- 记录实验设计。
- 保留失败结果。
- 标注证据来源。
- 独立 agent 审查。
- 可复现实验命令。

如果一个方案只是“看起来合理”，但没有 evidence、review 和 reproduction path，不能进入下一阶段。

## Research Loop

每个具体科目项目按以下循环推进：

```text
goal -> source audit -> hypothesis -> design -> implementation
-> validation -> pilot -> analysis -> revision -> replication
```

每一轮都要产出可审计记录。推荐放在具体项目仓库的：

```text
research/
  goals.md
  experiment_log.md
  agent_reviews/
  validation_reports/
  pilot_runs/
```

模板仓库不强制创建这些目录，因为不同项目可能有不同记录粒度；但具体科目项目应保留等价记录。

## Stage Gates

### 1. Goal Definition

目标定义必须回答：

- 学什么，不学什么。
- 学习者起点假设是什么。
- 期望能诊断到什么粒度。
- 最小可运行章节是什么。
- 哪些成果算完成。

必需产物：

- `research/goals.md`
- 范围内 source list
- 初始 learner profile
- 成功指标和失败指标

独立检查：

- `Scope Reviewer` 检查目标是否过宽、过模糊。
- `Pedagogy Reviewer` 检查目标是否能转化为可测技能。

通过标准：

- 目标可以被拆成 micro-skills。
- 每个目标都有可观察证据。
- 范围足够小，可以先跑通一个 MVP。

### 2. Source Audit

来源审计必须确认教材、原文、视频、论文或课程资料的锚点。

必需产物：

- source index
- anchor list
- unclear / missing source notes

独立检查：

- `Evidence Reviewer` 检查每个技能是否能回到来源。
- `Citation Reviewer` 检查锚点是否足够精确。

通过标准：

- 每个核心技能至少有一个 source anchor。
- 题目和 rubric 不凭空生成关键定义。
- 模糊来源被显式标记。

### 3. Hypothesis Formation

这里的 hypothesis 不是学术论文假设，而是系统设计假设。

例子：

```text
H1: SK-004 必须依赖 SK-002，否则学习者会在边界题中出现 overextension。
H2: 练 SK-007 会隐式复习 SK-003，但不会充分复习 SK-001。
H3: 错误类型 boundary 应优先补救 SK-005，而不是重复当前技能。
```

必需产物：

- graph hypotheses
- measurement hypotheses
- remediation hypotheses
- task selection assumptions

独立检查：

- `Method Reviewer` 检查假设是否可测试。
- `Counterexample Reviewer` 尝试构造反例。

通过标准：

- 每个关键图谱边都有理由。
- 每个关键题型都有测量目的。
- 每个补救路径能通过错误证据触发。

### 4. Design

设计阶段把假设转成结构化资产。

必需产物：

- `skill_graph.json`
- `graph.nodes.json`
- `graph.edges.json`
- question bank draft
- rubric draft
- diagnostic plan

独立检查：

- `Graph Reviewer` 检查 edge type、循环、过大技能、缺失 anchor。
- `Assessment Reviewer` 检查题目是否真正测目标技能。
- `Rubric Reviewer` 检查 rubric 是否能区分常见错误。

通过标准：

- `prerequisite` 和 `encompasses` 分开。
- 每个技能有 core、misconception、boundary、transfer 覆盖。
- 有前置的技能有 bridge 题。
- 每道题有 `skill_vector`、难度、区分度、预计时间和误解标签。

### 5. Implementation

实现阶段可以由 AI 自主修改文件，但必须保持小步提交和可回滚。

必需产物：

- 结构化数据文件。
- 配置更新。
- 必要文档。
- 若修改引擎代码，必须有对应校验或测试。

独立检查：

- `Implementation Reviewer` 检查文件结构和兼容性。
- `Code Reviewer` 检查引擎改动风险。
- `Data Reviewer` 检查 JSON/schema 一致性。

通过标准：

```bash
python3 -m engine.validate all
python3 -m engine.graph_audit run --strict
python3 -m engine.diagnostic status
python3 -m engine.task_selection next
```

所有命令无 error。

### 6. Validation

验证阶段不是看程序能不能跑一次，而是看系统输出是否符合设计假设。

必需产物：

- validation report
- failing cases
- known limitations
- exact commands

独立检查：

- `Reproduction Reviewer` 按命令重跑验证。
- `Method Reviewer` 检查验证是否覆盖目标假设。

通过标准：

- 诊断能给出合理 frontier。
- task selection 的 top recommendations 可解释。
- session plan 题型分配符合设计。
- result 能写 event log 并更新 student model。
- FIRe 只沿 `encompasses` 发放学分。

### 7. Pilot

试运行阶段使用真实或模拟学习者记录。

必需产物：

- diagnostic result
- session result
- event log summary
- learner-visible feedback notes

独立检查：

- `Learner Simulation Reviewer` 检查是否存在明显不合理路径。
- `Analytics Reviewer` 检查事件是否足以支持结论。

通过标准：

- 错误能归因到 skill、edge、misconception 或 item family。
- 补救建议和错误类型一致。
- 复习推荐不会压过当前最重要 frontier，除非遗忘风险足够高。

### 8. Analysis

分析阶段必须把结果和假设对照。

必需产物：

- accepted hypotheses
- rejected hypotheses
- changed graph edges
- changed question/rubric items
- next experiment

独立检查：

- `Evidence Reviewer` 检查结论是否由数据支持。
- `Bias Reviewer` 检查是否过度相信 AI 生成内容。

通过标准：

- 每个改动都有 evidence。
- 没有把单次失败误判为稳定规律。
- 没有只保留成功案例。

### 9. Revision

修订阶段允许 AI 重新设计方案，但必须保留实验历史。

必需产物：

- revision log
- changed files summary
- reason for each major change

独立检查：

- `Regression Reviewer` 检查新改动是否破坏已有通过案例。
- `Scope Reviewer` 检查是否发生范围膨胀。

通过标准：

- 原有核心校验仍通过。
- 新问题被记录，而不是隐藏。
- 修订没有把具体项目内容提交回模板仓库。

### 10. Replication

复制验证是进入稳定版本前的最后门槛。

必需产物：

- clean clone or fresh copy run
- exact commands
- final validation report

独立检查：

- `Replication Reviewer` 在干净副本中重跑关键命令。
- `Release Reviewer` 检查文档是否足以让下一个 AI 或人类接手。

通过标准：

- 干净副本可以完成诊断、任务选择、session start 和至少一次 session result。
- 文档说明当前限制。
- 所有 runtime data 的提交策略明确。

## Agent Review Matrix

每个阶段至少需要一个非执行 agent 检查。高风险阶段需要两个。

| Stage | Required reviewer agents |
| --- | --- |
| Goal Definition | Scope Reviewer, Pedagogy Reviewer |
| Source Audit | Evidence Reviewer, Citation Reviewer |
| Hypothesis Formation | Method Reviewer, Counterexample Reviewer |
| Design | Graph Reviewer, Assessment Reviewer, Rubric Reviewer |
| Implementation | Implementation Reviewer, Code Reviewer, Data Reviewer |
| Validation | Reproduction Reviewer, Method Reviewer |
| Pilot | Learner Simulation Reviewer, Analytics Reviewer |
| Analysis | Evidence Reviewer, Bias Reviewer |
| Revision | Regression Reviewer, Scope Reviewer |
| Replication | Replication Reviewer, Release Reviewer |

Reviewer agents should answer in this format:

```text
Review role:
Stage:
Pass / Block:
Findings:
Required changes:
Residual risk:
```

If any reviewer marks `Block`, the project cannot advance until the issue is fixed or explicitly waived with rationale.

## Experiment Log Format

每轮实验建议记录：

```markdown
## Experiment YYYY-MM-DD-N

Goal:
Hypothesis:
Changed files:
Commands:
Observed results:
Reviewer agents:
Decision:
Next action:
```

失败实验也必须记录。失败记录是后续校准图谱和算法权重的核心证据。

## Autonomy Boundaries

AI 自主探索时，优先级如下：

1. 保持最终学习目标可测。
2. 保持来源证据可追踪。
3. 保持图谱和题库结构可校验。
4. 保持每个实验可复现。
5. 保持每个阶段有独立审查。

出现以下情况时，AI 必须停下来生成 review request，而不是继续推进：

- 目标范围变大但没有更新成功标准。
- source anchor 不足以支撑技能或题目。
- 图谱出现多个同样合理但互相冲突的结构。
- task selection 推荐和教学直觉明显冲突。
- validation 通过，但 pilot 行为异常。
- reviewer agent 提出 blocking finding。

## Practical Minimum

如果项目规模很小，最小流程也不能少于：

1. `Goal Definition`
2. `Source Audit`
3. `Design`
4. `Implementation`
5. `Validation`
6. `Independent Review`
7. `Revision`

最小 reviewer 配置：

- 一个检查图谱和来源。
- 一个检查题库和 rubric。
- 一个检查运行结果和复现命令。

这能避免 AI 只靠流畅叙述推进项目，而没有实验证据支撑。
