# Scope Contract Example

复制本文件为 `source/scope_contract.md`，再按真实资料填写。范围契约是完整系统生成的边界；Codex 和人类都只能在这个边界内声称“完整”。

## 系统名称

- 名称：示例学习系统
- 学科/主题：示例主题
- 生成目标：基于用户提供的资料语料库，生成完整、可追溯、可验证的学习系统。

## 学习范围

### SC-001：掌握核心概念和关键边界

- in_scope: true
- source_anchors:
  - `TXT-001#ch01-sec01-def-core`
  - `TXT-001#ch01-sec02-example-1`
  - `COURSE-001#week01-key-distinction`
- 学习者应能：
  - 用自己的话给出核心定义。
  - 区分相邻但错误的说法。
  - 判断一个案例是否落入适用范围。
  - 构造或解释一个反例。
- 完成标准：正式练习中 core、misconception、boundary 题都达到 mastery threshold，且能解释错误选项。

### SC-002：迁移到新案例

- in_scope: true
- source_anchors:
  - `TXT-001#ch02-sec03-transfer-case`
- 学习者应能：
  - 在新情境中识别相关结构。
  - 说明适用条件。
  - 说明迁移限制。
- 完成标准：transfer 题达到 mastery threshold，且回答包含限制条件。

## 排除范围

当前不生成以下内容：

- 学科史、作者传记和背景阅读，除非它们直接影响核心概念判断。
- 用户没有提供原文或课程资料的章节。
- 资料中没有明确出现、也没有被范围契约要求的进阶主题。
- 没有 source anchor 的争议观点、教材观点、例题和引用。

排除范围可以在后续阶段重新纳入，但必须同时补充 source anchor 和完成标准。

## 学习者假设

- 起点：具备示例前置知识，但没有系统学过本主题。
- 语言：中文学习，必要术语可保留英文。
- 目标水平：能独立完成概念解释、边界判断和基础迁移题。
- 单次学习时长：30-45 分钟。
- 题目偏好：短答、解释型选择题、反例题和案例分析题优先。

## 完成标准

完整系统生成完成时必须满足：

- 每个 in-scope 项都有对应 skill、题库、rubric 和 source anchor。
- 每个 skill 都能说明来源、前置关系、练习题覆盖和完成标准。
- 每道核心题和每个 rubric `must_hit` 都能追溯到资料或范围契约。
- `SOURCE_GAP` 没有 blocking 项；如果有，系统只能标为 incomplete。
- 现有验证命令通过，发布检查清单完成。

## SOURCE_GAP 规则

当资料不足时，按以下格式记录，不得用模型常识补齐：

```markdown
### SOURCE_GAP SG-001

- status: open
- blocking: true
- gap_type: weak_anchor
- scope_item: SC-001
- needed_for: question_bank
- attempted_sources:
  - TXT-001#ch01-sec01-def-core
- problem: 锚点只包含术语名，没有定义和边界条件。
- required_human_action: 补充教材定义段落，或移除该题目覆盖要求。
```
