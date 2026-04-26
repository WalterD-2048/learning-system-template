# Template Operating Notes

这份文档记录模板当前状态、GitHub 使用方式，以及以后基于模板设计具体科目学习系统时需要遵守的实践。

## 当前完整度

这个仓库现在是一个**模板层面的完整自适应学习系统 MVP**。

它已经具备端到端自适应闭环：

```text
diagnostic -> task_selection -> session plan -> answer event log
-> student_model update -> FIRe v2 -> remediation -> next task ranking
```

这意味着模板已经不只是“规则练习系统”，而是可以：

- 用诊断估计 knowledge frontier。
- 用 task selection 解释下一步为什么该学、练、复习或补救某个技能。
- 用 item-level event log 记录逐题证据。
- 用 student model 更新 `mastery_p`、`retrievability`、`stability_days`、`automaticity` 和 `uncertainty`。
- 用 FIRe v2 通过 `encompasses` 边给基础技能发放隐式复习学分。
- 在失败后基于图谱标记前置验证、提高依赖技能不确定性，并生成补救建议。

但它还不是“产品级 Math Academy”。具体科目落地时，还需要补真实知识图谱、真实题库、rubric、诊断题、参数校准和长期数据评估。

## GitHub 使用方式

日常使用直接看 `main`。

`main` 是当前最新、已合并、已通过 GitHub Actions 校验的版本。历史 PR 只是阶段性开发记录：

- PR #1：自适应基础模块。
- PR #2：自适应运行闭环。

后续做具体学习系统时，建议从 `main` 复制或 fork，而不是从旧功能分支开始。

## 本地访问注意事项

当前工作目录是：

```text
/Users/eda/Documents/learning-system-template-adaptive-run
```

如果换机器或重新开始，直接从 GitHub clone `main`：

```bash
git clone https://github.com/WalterD-2048/learning-system-template.git
cd learning-system-template
```

所有运行命令默认在 `scripts/` 目录下执行。

## 具体科目落地流程

创建一个真实科目学习系统时，建议按这个顺序做：

1. 复制模板到新目录或新仓库。
2. 修改 `scripts/config.json`，替换 subject、textbook、强度、复习参数和自适应参数。
3. 替换 `source/SOURCE.md`，写清教材、原文、章节、页码、视频时间戳或资料锚点。
4. 重建 `scripts/data/skill_graph.json`，只放学习状态和兼容字段。
5. 重建 `scripts/data/graph.nodes.json` 和 `scripts/data/graph.edges.json`，放 typed knowledge graph。
6. 给每个技能补 `scripts/content/question_banks/SK-XXX.json`。
7. 给每个技能补 `scripts/content/rubrics/SK-XXX.json`。
8. 跑校验命令，直到没有 error。
9. 先用 3-8 个技能点跑通一个小章节，再扩展全课程。

## 图谱设计原则

不要把 `prerequisite` 和 `encompasses` 混在一起。

- `prerequisite`：用于解锁、诊断、frontier 判断。表示学 B 前需要 A。
- `encompasses`：用于 FIRe v2。表示练 B 时会隐式复习 A。
- `confusable_with`：用于降低干扰和生成对比练习。
- `remediates`：用于把错误类型指向补救技能。
- `assessed_by`：用于把技能和题目绑定起来。
- `source_anchor`：用于把技能绑定回原始资料。

一个技能点应该尽量是 micro-skill。太大的技能会让诊断、题库覆盖和学生模型都变粗。

## 题库设计原则

每道题不只是内容，还应该是测量工具。

优先补这些字段：

```json
{
  "skill_vector": {
    "SK-001": 0.8,
    "SK-002": 0.2
  },
  "misconception_targets": ["boundary"],
  "difficulty_param": 0.6,
  "discrimination": 1.1,
  "expected_time_sec": 120,
  "target_edges": ["SK-001->SK-003:prerequisite"]
}
```

题库至少覆盖：

- `core`
- `misconception`
- `boundary`
- `transfer`
- 有前置关系时补 `bridge`

不要只堆同类题。自适应系统依赖的是可解释的证据质量，不是题目数量本身。

## 运行数据注意事项

`session result` 和 `diagnostic apply` 会修改状态，也会写事件日志。

事件日志位于：

```text
scripts/data/events/*.jsonl
```

这些是具体学习者的运行数据，默认已经被 `.gitignore` 忽略。模板仓库不应该提交个人学习事件日志。

如果要保留某个真实学习系统的长期数据，可以在该具体项目仓库里决定是否提交事件日志；模板仓库保持干净。

## 常用检查命令

在 `scripts/` 目录下执行：

```bash
python3 -m engine.validate all
python3 -m engine.graph_audit run --strict
python3 -m engine.diagnostic status
python3 -m engine.task_selection next
python3 -m engine.session start SK-001
```

会修改状态的命令建议先在复制出来的具体项目里运行：

```bash
python3 -m engine.diagnostic apply '{"SK-001":"mastered"}'
python3 -m engine.session result SK-001 '{"answers":{"1":"correct"}}'
```

## 是否应该直接改模板

模板仓库只改通用能力、schema、文档和示例。

具体科目的知识点、题库、rubric、学习状态和事件日志，应该放在复制出来的具体学习系统里。这样模板可以持续进化，具体项目也不会被模板更新打乱。

## AI 自主探索与科研流程

如果让 AI 自主探索具体科目的学习系统设计方案，不要让它直接一路生成到最终版本。应按 [AI_RESEARCH_WORKFLOW.md](AI_RESEARCH_WORKFLOW.md) 执行：

- 先定义最终目标和成功/失败指标。
- 再做 source audit、hypothesis、design、implementation、validation、pilot、analysis、revision 和 replication。
- 每个阶段都要保留实验记录。
- 每个阶段至少需要一个非执行 agent 审查，高风险阶段需要多个 agent 审查。
- reviewer agent 标记 `Block` 时，不能进入下一阶段。

这个流程的目的，是让 AI 有探索空间，但不能绕开证据、复现和独立检查。

## 下一阶段改进方向

模板已经能自适应运行。下一阶段更适合围绕真实科目做校准：

- 用真实题目校准 `difficulty_param` 和 `discrimination`。
- 给诊断题建立更明确的 skip/placement 规则。
- 增加课程级 `unit`、`lesson`、`objective` 节点。
- 增加事件回放与模型重算命令。
- 增加更细的 analytics，把错误归因到 skill、edge、misconception 和 item family。
- 根据真实学习记录调整 task selection 权重。
