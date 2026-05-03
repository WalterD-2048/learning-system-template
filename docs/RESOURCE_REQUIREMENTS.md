# Resource Requirements for Full System Generation

这份文档定义“基于资料语料库生成完整学习系统”前，用户必须提供的最小资料包。这里的完整只指**完整覆盖用户提供的资料语料库和声明范围**，不指覆盖整个学科宇宙。

如果资料包没有通过 Resource Intake Gate，生成流程必须停止扩展核心内容，并产出 `SOURCE_GAP` 记录。不能用模型常识补齐核心定义、题目、教材观点或引用。

## 最小资料包

完整系统生成至少需要以下文件或等价内容：

| 资料 | 推荐路径 | 必需内容 | 通过标准 |
| --- | --- | --- | --- |
| 范围契约 | `source/scope_contract.md` | 学习范围、排除范围、学习者假设、完成标准 | 每个范围项都可被判断为 in scope 或 out of scope |
| 资料索引 | `source/source_index.yml` | 资料文件、版本、优先级、章节/段落锚点、范围映射 | 每个 in-scope 范围项至少有一个可追溯 source anchor |
| Markdown 资料语料库 | `source/materials/*.md` | 教材、课程笔记、论文、原文、讲义或题源 | 文件可读，锚点稳定，章节/页码/时间戳等定位信息保留 |
| 资料说明 | `source/SOURCE.md` | 给人读的资料总览、版本说明、引用约定 | 与 `source_index.yml` 不冲突 |
| 学习者假设 | `teacher/learner_profile.md` 或范围契约 | 起点、目标水平、语言、已知前置知识 | 能影响图谱粒度、题目难度和反馈风格 |

`source/source_index.example.yml` 和 `source/scope_contract.example.md` 是模板。生成真实系统前，复制成不带 `.example` 的文件并填写。

## “足够教材 markdown”的判定

收集资料时，不要求覆盖整个学科，但必须足够覆盖声明范围。一个资料包可以进入完整生成，至少要满足：

- 每个 in-scope 范围项有一份 primary 或 accepted secondary markdown 正文。
- 每个核心定义、公式、原文段落、例题、案例或论证可以定位到稳定 anchor。
- 每个预期 skill 至少有材料支撑概念讲解和一个练习锚点。
- 每个预期 skill 能支撑 `core`、`misconception`、`boundary`、`transfer` 四类题；有前置依赖时能支撑 `bridge` 题。
- 资料中能看到教材或课程的真实表述，不能只有 AI 摘要、目录或关键词表。
- 用户能说明资料版本、译本、课程批次或日期。

不满足这些条件时，先补 markdown 资料或缩小 `scope_contract.md`。若仍要继续，只能生成 `SOURCE_GAP` 和外围结构，不能生成被资料缺口阻塞的核心内容。

## Markdown 资料要求

资料文件必须能支持精确锚点。推荐规则：

- 每份资料一个独立 `.md` 文件，放在 `source/materials/`。
- 文件名保持稳定，例如 `primary-textbook.md`、`course-week-01.md`、`paper-smith-2021.md`。
- 保留原书章节、页码、讲义页码、视频时间戳或论文小节编号。
- 使用清晰标题层级；需要段落级引用时，显式加入 HTML anchor，例如 `<a id="ch01-sec02-def-cost"></a>`。
- 不把多个来源混成一个没有来源边界的文件。
- 不把 AI 摘要当作原始资料；摘要可以存在，但必须标明它是二手整理。
- 如果从 PDF/OCR 转换，必须人工抽查核心定义、公式、例题和引用是否无误。

## Source Anchor 约定

每个核心技能、核心定义、题目和 rubric 都应能回到一个或多个 source anchor。

推荐 anchor 格式：

```text
MATERIAL-ID#local-anchor
```

示例：

```text
TXT-001#ch01-sec02-def-demand
TXT-001#p034-example-2
COURSE-003#week04-00h18m12s
PAPER-002#sec3-theorem-1
```

题库中的 `source_sections`、技能图谱中的 `source.section` / `source.anchor`、typed graph 的 `source_anchor` 边，都应使用同一套 anchor 命名。

## Resource Intake Gate

完整系统生成必须先通过 Resource Intake Gate。

### 1. 文件存在性

检查：

- `source/scope_contract.md` 存在。
- `source/source_index.yml` 存在。
- `source/materials/` 下有至少一份 `.md` 资料。
- 资料索引里的 `path` 都能在仓库中找到。

失败处理：生成 `SOURCE_GAP`，说明缺哪个文件、阻塞哪些范围项。

### 2. 范围可判定

检查：

- 范围契约明确写出 include / exclude。
- 每个 include 项有完成标准。
- 排除范围不会和 include 项互相冲突。
- 学习者起点足以决定技能粒度和题目难度。

失败处理：生成 `SOURCE_GAP`，要求用户补范围边界或完成标准。

### 3. 来源可追溯

检查：

- 每个 include 项至少有一个 primary 或 accepted secondary source anchor。
- 每个核心定义、公式、例题、案例或论证节点可以定位到资料。
- 资料索引中标明优先级：`primary`、`secondary`、`reference` 或 `background`。
- 同一概念存在多个来源冲突时，索引标出优先级或需要人工裁决。

失败处理：不能自行调和或虚构教材观点；必须生成 `SOURCE_GAP`。

### 4. 覆盖可生成

检查：

- 每个 include 项可以拆成可测 micro-skill。
- 每个 micro-skill 有足够材料生成 `core`、`misconception`、`boundary`、`transfer` 题。
- 有前置关系的技能有材料支持 `bridge` 题。
- 资料含有或允许推导常见误解、边界案例、迁移情境。

失败处理：若只能生成概念说明但不能生成可测题目，记录 `SOURCE_GAP`，不要编造题源。

### 5. 权限和版本

检查：

- 用户确认资料可以用于本地学习系统生成。
- 版本、译本、课程批次或日期明确。
- 引用时不会把不同版本混为一谈。

失败处理：记录版本或权限缺口，要求用户补充。

## SOURCE_GAP 记录格式

推荐把缺口记录写入具体项目的 `research/source_gaps.md`。也可以在生成报告中用同样格式列出。

```markdown
### SOURCE_GAP SG-001

- status: open
- blocking: true
- gap_type: missing_source | ambiguous_scope | weak_anchor | insufficient_exercises | source_conflict | conversion_quality
- scope_item: SC-001
- needed_for: skill_graph | question_bank | rubric | teacher_workflow | validation
- attempted_sources:
  - TXT-001#ch01-sec02
- problem: 现有资料没有给出该概念的边界条件，不能生成 boundary 题。
- required_human_action: 请补充原教材对应段落、教师讲义说明，或明确该范围项移出 scope。
- downstream_rule: 该范围项对应技能保持 `needs_validation`，不生成无锚点核心题。
```

`SOURCE_GAP` 不是待办便签，而是防止伪造内容的审计记录。只要 gap 仍 blocking，完整系统不能发布为 complete。

## 常见失败模式

- 只有目录，没有正文：可以生成粗略范围，但不能生成完整题库。
- 只有 AI 摘要，没有原文：可以作为辅助资料，不能作为核心定义和题目的唯一来源。
- 资料锚点只到整章：技能和题目会过粗，应补到小节、段落、公式、例题或时间戳。
- 范围过大：必须缩小 scope 或拆成多个阶段。
- 资料互相冲突：必须记录冲突和优先级，不能自动拼接成一个虚构观点。
- 题源不足：可以生成学习说明和 gap，不能生成无来源锚点的题目。

## Done When

Resource Intake Gate 完成的标准：

- 所有必需文件存在并互相一致。
- 每个 in-scope 范围项有 source anchor。
- 每个 source anchor 能定位到具体 markdown 内容。
- 所有 blocking `SOURCE_GAP` 已解决，或范围契约明确把相关内容移出 scope。
- 生成者可以说明哪些内容会进入完整系统，哪些内容不会进入，以及原因。
