# Full System Generation Workflow

这份文档定义如何从教材、课程 markdown 资料、论文、原文和课程笔记生成一个完整、可追溯、可验证的学习系统。

完整系统生成不重写 engine，不引入重型依赖。它使用现有自适应运行时、题库/rubric/schema、typed knowledge graph 和验证命令。

## “完整”的定义

完整指：

- 完整覆盖 `source/scope_contract.md` 声明的学习范围。
- 完整覆盖 `source/source_index.yml` 中标为 in scope 的资料锚点。
- 每个 in-scope 学习目标都落到可测 micro-skill。
- 每个核心技能、核心定义、题目、rubric 要点都有 source anchor。
- 已知资料缺口用 `SOURCE_GAP` 记录，而不是由 AI 编造。

完整不指：

- 覆盖整个学科。
- 覆盖用户没有提供的教材、课程或论文。
- 自动生成没有资料来源的教材观点、争议结论、例题或引用。

## 输入和输出

输入：

```text
source/
├── SOURCE.md
├── scope_contract.md
├── source_index.yml
└── materials/
    ├── primary-textbook.md
    ├── course-notes.md
    └── paper-or-original.md
```

主要输出：

```text
scripts/config.json
scripts/data/skill_graph.json
scripts/data/graph.nodes.json
scripts/data/graph.edges.json
scripts/content/question_banks/SK-XXX.json
scripts/content/rubrics/SK-XXX.json
teacher/system.md
teacher/system_detail.md
teacher/learner_profile.md
research/source_gaps.md
```

`research/source_gaps.md` 只在资料不足时必需。若无缺口，发布检查清单中应明确写出“无 blocking SOURCE_GAP”。

## 主线流程

完整课程系统的主线流程是：

```text
1. 收集足够教材/课程 markdown
2. 审计资源是否足够完整
3. 一次性生成完整课程系统
4. 运行验证命令
5. 通过 reviewer gate
6. 修正 blocking findings，直到 Done When
```

这个流程的关键约束是先收集、再审计、再生成。资源不足时不能靠模型常识补内容；资源通过后也不应只停在 MVP 或单章节草稿，而应生成范围契约内的完整课程资产。

## 生成流程

### 0. 收集足够教材/课程 markdown

先把用户能提供的主教材、课程笔记、讲义、论文、原文、题源和人工整理笔记转成 markdown，放入 `source/materials/` 并登记到 `source/source_index.yml`。

“足够”至少表示：

- 每个 in-scope 范围项有正文材料，不只是目录或摘要。
- 核心定义、公式、原文段落、例题、案例或论证有可定位 anchor。
- 能支撑每个技能的 `core`、`misconception`、`boundary`、`transfer` 题。
- 有前置依赖的技能有材料支撑 `bridge` 题。
- 资料版本、译本、课程批次或日期明确。

如果只收集到目录、AI 摘要、零散摘录或不可定位文本，进入审计时应产生 `SOURCE_GAP`。

### 1. Resource Intake Gate

先按 [RESOURCE_REQUIREMENTS.md](RESOURCE_REQUIREMENTS.md) 检查资料包。

通过后才能生成核心内容。未通过时，只能做两件事：

- 记录 `SOURCE_GAP`。
- 生成不依赖缺失资料的外围结构，例如空白配置草案或待填范围表。

不能生成无来源锚点的核心定义、题目、rubric 判分点或教材观点。

### 2. 资料归一化和锚点盘点

目标是把语料库变成可追溯的 anchor inventory。

操作：

- 确认 `source_index.yml` 中每个 `materials[].path` 指向真实 markdown 文件。
- 检查每份资料的章节、页码、时间戳或小节编号。
- 为核心定义、公式、例题、案例、论证和原文段落建立 anchor。
- 把过粗的整章锚点拆到小节、段落或例题层。

产物：

- 完整的 `source_index.yml`。
- 明确的 anchor 命名约定。
- 必要时生成 `SOURCE_GAP`。

### 3. 范围到来源覆盖映射

目标是确认每个 scope item 都有证据。

操作：

- 逐项读取 `scope_contract.md` 的 include 范围。
- 在 `source_index.yml` 中给每个范围项绑定 source anchor。
- 对每个资料章节标记：进入技能图谱、只作背景、排除、或需要人工判断。
- 对冲突来源标明优先级。

产物：

- `scope_items[].source_anchors` 完整。
- 每个材料章节有处理决策。
- unresolved 项生成 `SOURCE_GAP`。

### 4. 一次性生成完整课程资产

通过 Resource Intake Gate 后，生成范围契约内的完整课程资产，而不是只生成 MVP。

一次性生成包括：

- 所有 in-scope scope item 的 skill graph。
- typed knowledge graph nodes / edges。
- 每个 skill 的 question bank。
- 每个 skill 的 rubric。
- 具体系统配置。
- teacher workflow 和 learner profile。
- source gap、残余风险和人工补充清单。

如果生成过程中发现某个范围项无法被资料支撑，该范围项不得被静默跳过；必须写 `SOURCE_GAP`，并在 release checklist 中标为 incomplete 或 blocked。

### 5. 学习目标和 micro-skill 拆解

目标是把资料范围拆成可诊断、可练习、可复习的技能点。

规则：

- 一个 skill 应能在一节概念课中讲清。
- 一个 skill 应能用 6-14 道题覆盖核心、误解、边界和迁移。
- 技能名称和描述必须来自 source anchor 支撑。
- 过大的章节要拆成多个 skill。
- 如果资料只支持“读过/了解”，但不支持可测技能，要记录缺口或降级为背景。

产物：

- `scripts/data/skill_graph.json` 的 skills 草案。
- 每个 skill 的 `source`、`exercise_anchor`、`prerequisites` 和初始 `status`。

### 6. 图谱和自适应边设计

目标是让 learning system 能解释解锁、复习、混淆和补救。

操作：

- 在 `skill_graph.json` 中维护兼容字段和学习状态。
- 在 `graph.nodes.json` / `graph.edges.json` 中建立 typed knowledge graph。
- 用 `prerequisite` 表示学习前置。
- 用 `encompasses` 表示练习高级技能时隐式复习基础技能。
- 用 `confusable_with` 表示易混概念。
- 用 `remediates` 把错误类型指向补救技能。
- 用 `source_anchor` 把技能和资料锚点绑定。

禁止把 `prerequisite` 和 `encompasses` 混成一种边。

### 7. 题库生成

目标是让每个技能都有可测量的题库，而不是题干模板。

每个 skill 至少覆盖：

- `core`：核心定义、机制、公式或论证。
- `misconception`：常见误解、误读或混淆。
- `boundary`：适用范围、反例、边界条件。
- `transfer`：新情境迁移。
- `bridge`：有前置依赖时必需。

每道题必须有：

- `source_sections`，指向具体 source anchor。
- `expected_points`，可回到资料或由资料直接支持。
- `skill_vector`、`difficulty_param`、`discrimination`、`expected_time_sec`。
- `misconception_targets` 或可解释的错误归因。
- `rubric_id`。

如果资料不足以支持某类题，不生成伪题；记录 `SOURCE_GAP`。

### 8. Rubric 生成

目标是让判分规则能稳定识别掌握、部分掌握和错误类型。

每个 rubric 必须包含：

- `must_hit`：可判定、可观察的要点。
- `common_failures`：常见错误信号。
- `partial_credit_rules`：半对半错时如何处理。
- `error_type_mapping`：如何映射到补救路径。

rubric 不应把没有来源支持的定义、观点或标准当作“正确答案”。

### 9. Teacher 工作流更新

目标是让教学角色使用生成后的完整系统。

需要更新：

- `teacher/system.md`：总工作流和文件更新规则。
- `teacher/system_detail.md`：概念课、示范练习、正式练习、复习和补救细节。
- `teacher/main_teacher.md` / `assistant_teacher.md` / `examiner.md`：按学科风格调整。
- `teacher/learner_profile.md`：使用范围契约里的学习者假设。

教师文件可以改变教学风格，但不能绕过来源锚点和 validation gate。

### 10. 验证命令

在 `scripts/` 下执行现有验证命令：

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

如果某个技能已设为 `concept_done` 或 `demo_done`，继续抽测：

```bash
python3 -m engine.demo start SK-001
python3 -m engine.session start SK-001
```

发布前还要完成 [../research/full_generation_checklist.md](../research/full_generation_checklist.md)。

### 11. Reviewer Gate

验证命令通过后，还必须做 reviewer gate。Reviewer gate 用来捕捉命令无法完全判断的来源、范围、教学和评测风险。

最小 reviewer 集合：

| Reviewer | 阻塞检查 |
| --- | --- |
| Resource Reviewer | markdown 资料是否足够、source index 是否能定位、是否存在未记录 `SOURCE_GAP` |
| Scope Reviewer | 完整声明是否越过 `scope_contract.md`，exclude 项是否被误纳入 |
| Graph Reviewer | skill 粒度、前置关系、typed edges 和 source anchors 是否合理 |
| Assessment Reviewer | 题目是否真正测目标 skill，是否有无来源题目 |
| Rubric Reviewer | `must_hit`、partial credit 和 error mapping 是否可判定 |
| Runtime Reviewer | 验证命令、diagnostic、task selection、demo/session 抽测是否可运行 |

Reviewer 输出格式：

```text
Review role:
Pass / Block:
Findings:
Required changes:
Residual risk:
```

任何 reviewer 标记 `Block`，都必须修正后重跑相关验证命令，并重新通过对应 reviewer。不能通过“说明原因”把 blocking finding 当作 complete。

## Codex /goal 使用方式

Codex 入口提示放在 [../GENERATE.md](../GENERATE.md)。本文件只维护完整系统生成的执行细节，避免两处流程文案漂移。

## 失败处理

遇到以下情况时停止对应内容生成：

- 缺少资料正文。
- 资料锚点无法定位。
- 范围契约含糊或互相矛盾。
- 核心定义只有模型常识，没有资料来源。
- 题目需要的案例、公式、边界条件或误解资料不存在。
- 引用、版本或译文冲突需要人工判断。

处理方式：

- 写 `SOURCE_GAP`。
- 标明阻塞的 scope item、skill 或 question coverage。
- 给出最小人工补充要求。
- 不把 blocking gap 的内容发布为 complete。

## Done When

完整系统生成完成标准：

- Resource Intake Gate 通过，或所有 blocking `SOURCE_GAP` 已由用户处理。
- `scope_contract.md` 的每个 include 项在图谱、题库或明确的背景资料中有处理结果。
- 每个 in-scope source anchor 都被使用、排除或记录为 gap。
- 每个 skill 有 source anchor、前置关系、初始状态和 mastery 字段。
- 每个 skill 有题库和 rubric，并覆盖必需 coverage。
- 无核心定义、题目或 rubric 判分点依赖无来源模型常识。
- `python3 -m engine.validate all --strict` 和 `python3 -m engine.graph_audit run --strict` 无 error。
- 内容覆盖和质量审计没有 blocking 缺口。
- Reviewer gate 全部 Pass，或 blocking findings 已修正并复审通过。
- `research/full_generation_checklist.md` 完成并记录残余风险。
