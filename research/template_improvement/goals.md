# Template Improvement Goal Definition

Experiment ID: `template-improvement-2026-04-27-001`

Stage: `Goal Definition`

## Final Goal

把 `learning-system-template` 发展成一个**可自我改进的自适应学习系统模板**。

这里的“自我改进”不是让 AI 任意重构仓库，而是建立一个科研式、可审查、可复现的模板改进流程，使 AI 能持续发现模板短板、提出假设、实现小步改进、运行验证、接受独立 agent 审查，并把通过审查的通用能力合并到 `main`。

最终状态应满足：

- 每个模板改进都有明确目标、假设、实验记录、验证命令和 reviewer 结论。
- AI 可以自主探索解决方案，但不能跳过 source/evidence、validation、review 和 replication。
- 模板仓库只吸收通用能力、schema、validator、runtime、文档和示例改进。
- 具体科目内容、个人学习状态和运行日志不会污染模板仓库。
- 新 agent 或人类可以从 `main` 接手，并理解当前目标、实验状态和下一步。

## First MVP Goal

本轮只完成元系统的第一个最小闭环：

```text
define meta-goal -> create research records -> run template validation
-> independent reviewer agents inspect goal -> revise if blocked
```

本轮不实现新的算法功能，不修改 session/task_selection/student_model 代码。

## In Scope

- 为模板自身建立 `research/template_improvement/` 记录区。
- 定义模板持续改进的最终目标、范围、成功指标和失败指标。
- 定义首轮 MVP 的最小实验路径。
- 让 `Scope Reviewer` 和 `Pedagogy Reviewer` 检查目标是否过宽、是否可测。
- 运行现有模板校验，确认新增研究记录不破坏仓库。

## Out of Scope

- 不为具体科目生成技能图谱、题库或 rubric。
- 不提交个人学习事件日志。
- 不重写当前算法模块。
- 不引入新的外部服务或数据库。
- 不把所有未来改进一次性设计完。

## Starting Assumptions

- 当前模板已经具备 adaptive runtime MVP。
- 当前主要风险不是“缺功能”，而是未来 AI 改进模板时目标漂移、证据不足、审查缺失、具体项目内容污染模板。
- 因此首轮元实验应优先建立目标和实验记录，而不是直接继续加算法。

## Success Metrics

本轮通过标准：

- `research/template_improvement/goals.md` 存在，并清楚说明 final goal、MVP goal、scope、non-goals、success/failure metrics。
- `research/template_improvement/experiment_log.md` 存在，并记录本轮实验。
- 至少两个 reviewer agent 完成 Goal Definition 审查。
- 没有 reviewer 标记 `Block`；如果有，必须先修订目标。
- 以下命令通过：

```bash
cd scripts
python3 -m engine.validate all
```

## Failure Metrics

出现以下任一情况，本轮不能进入下一阶段：

- 目标表述无法转成可执行实验。
- 范围同时包含模板改进和具体科目内容。
- 成功标准无法被命令、文件或 reviewer 结论验证。
- reviewer agent 标记 `Block` 且未修复。
- 校验命令失败。

## Learner / User Profile

这里的“学习者”是未来使用模板的 AI agent 或人类维护者。

他们需要：

- 快速知道模板当前能做什么。
- 知道如何提出一个小步模板改进实验。
- 知道哪些内容应该进模板仓库，哪些应该留在具体科目项目。
- 能根据 reviewer 结论判断是否继续推进。

## Initial Research Question

如何把模板改进从“临时想到什么就改什么”变成一个可审查、可复现、可持续的科研式流程？

## Next Stage If This Passes

进入 `Source Audit` 阶段，审计当前模板文档、engine 模块、schema、CI 和示例资产，找出下一轮最值得改进的通用能力候选。
