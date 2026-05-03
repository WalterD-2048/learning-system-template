# Full Generation Release Checklist

完整系统生成后，用这份清单判断是否可以发布给学习者使用。若任一 blocking 项未完成，系统只能标记为 incomplete。

## 1. Resource Intake

- [ ] `source/scope_contract.md` 已填写，不再是示例文件。
- [ ] `source/source_index.yml` 已填写，不再是示例文件。
- [ ] `source/materials/` 中的 markdown 资料都能从 source index 找到。
- [ ] markdown 资料足够支撑完整生成，不只是目录、摘要或不可定位摘录。
- [ ] 每个 in-scope 范围项至少有一个 source anchor。
- [ ] 每个 source anchor 能定位到具体 markdown 标题、段落、页码、例题或时间戳。
- [ ] 每个预期 skill 都有材料支撑 `core`、`misconception`、`boundary`、`transfer`，有前置时也支撑 `bridge`。
- [ ] 资料版本、译本、课程批次或日期明确。
- [ ] 无 blocking `SOURCE_GAP`；若有，系统未被标记为 complete。

## 2. Scope Coverage

- [ ] 每个 include scope item 已映射到 skill、背景资料、或 `SOURCE_GAP`。
- [ ] 每个 exclude scope item 有排除理由。
- [ ] “完整”声明只覆盖资料语料库和范围契约，不扩大到整个学科。
- [ ] 学习者假设已经进入 `teacher/learner_profile.md` 或等价文件。
- [ ] 完成标准能被题库、rubric 和 engine 状态观测到。

## 3. Source Integrity

- [ ] 核心定义都有 source anchor。
- [ ] 核心题目都有 source anchor。
- [ ] rubric `must_hit` 不包含无来源教材观点。
- [ ] 没有虚构引用、虚构教材观点或虚构原文。
- [ ] 多来源冲突已经记录优先级或人工裁决。
- [ ] 资料不足处写了 `SOURCE_GAP`，没有用模型常识补齐。

## 4. Graph And Runtime Assets

- [ ] `scripts/config.json` 已替换为具体系统配置。
- [ ] `scripts/data/skill_graph.json` 中每个 skill 有名称、描述、source、状态、mastery 字段。
- [ ] skill 粒度足够小，可以概念课、示范练习、正式练习和复习。
- [ ] `prerequisite` 用于解锁和诊断。
- [ ] `encompasses` 用于 FIRe v2 隐式复习。
- [ ] `confusable_with`、`remediates`、`source_anchor` 等 typed edges 使用一致。
- [ ] 图谱无循环前置依赖。

## 5. Question Banks

- [ ] 每个 skill 有 `scripts/content/question_banks/SK-XXX.json`。
- [ ] 每个 skill 覆盖 `core`、`misconception`、`boundary`、`transfer`。
- [ ] 有前置依赖的 skill 覆盖 `bridge`。
- [ ] 每道题有 `source_sections`。
- [ ] 每道题有 `skill_vector`、难度、区分度、预计时间和 stage fit。
- [ ] 选择题不是主体；选择题要求解释理由。
- [ ] 题干没有只替换名词的模板化重复。

## 6. Rubrics

- [ ] 每个 skill 有 `scripts/content/rubrics/SK-XXX.json`。
- [ ] 每个题目引用的 `rubric_id` 存在。
- [ ] `must_hit` 是可判定要点。
- [ ] `common_failures` 覆盖常见错误。
- [ ] `partial_credit_rules` 能处理半对半错。
- [ ] `error_type_mapping` 能映射到后续补救训练。

## 7. Teacher Workflow

- [ ] `teacher/system.md` 和 `teacher/system_detail.md` 已按具体学科更新。
- [ ] 主教师、助教、考官角色知道如何使用 source anchor。
- [ ] 概念课有结束条件。
- [ ] 示范练习包含完整示范、部分提示、独立尝试。
- [ ] 正式练习记录正确率、错误类型、题型和作答形式。
- [ ] 复习课使用历史错误和 FIRe v2 结果。

## 8. Validation Commands

在 `scripts/` 目录下运行并记录结果：

```bash
python3 -m engine.state show
python3 -m engine.content coverage --only-missing
python3 -m engine.content audit --only-flagged
python3 -m engine.analytics today
python3 -m engine.validate all
python3 -m engine.validate all --strict
python3 -m engine.graph_audit run --strict
python3 -m engine.diagnostic status
python3 -m engine.task_selection next
```

抽测至少一个可运行 skill：

```bash
python3 -m engine.demo start SK-001
python3 -m engine.session start SK-001
```

结果：

- [ ] `engine.validate all --strict` 无 error。
- [ ] `engine.graph_audit run --strict` 无 error。
- [ ] coverage 无缺失必需覆盖。
- [ ] audit 无 blocking 质量风险。
- [ ] diagnostic 和 task selection 输出可解释。
- [ ] demo/session 能启动。

## 9. Reviewer Gate

每个 reviewer 按以下格式记录结论：

```text
Review role:
Pass / Block:
Findings:
Required changes:
Residual risk:
```

- [ ] Resource Reviewer 通过：资料包足够，source index 可定位，所有缺口已记录。
- [ ] Scope Reviewer 通过：完整声明没有越过范围契约，exclude 项没有被误纳入。
- [ ] Graph Reviewer 通过：skill 粒度、前置关系、typed edges 和 source anchors 合理。
- [ ] Assessment Reviewer 通过：题目真正测目标 skill，且没有无来源题目。
- [ ] Rubric Reviewer 通过：`must_hit`、partial credit 和 error mapping 可判定。
- [ ] Runtime Reviewer 通过：验证命令和抽测运行可解释。
- [ ] 所有 `Block` findings 已修正，并重跑相关验证命令。

## 10. Release Decision

- [ ] 发布状态：complete / incomplete / blocked
- [ ] 残余风险已记录。
- [ ] 人工仍需补充的资料已列出。
- [ ] 下一个迭代目标已记录。

## Done When

所有 checklist 项完成，且没有 blocking `SOURCE_GAP`，才能声明这是一个完整学习系统。否则只能声明为 MVP、partial build、或 source-gapped build。
