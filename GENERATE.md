# 从模板生成新学习系统

这份文档是生成入口。详细规则分别放在：

- [docs/RESOURCE_REQUIREMENTS.md](docs/RESOURCE_REQUIREMENTS.md)：资料包和 Resource Intake Gate。
- [docs/FULL_SYSTEM_GENERATION.md](docs/FULL_SYSTEM_GENERATION.md)：完整系统生成流程。
- [source/source_index.example.yml](source/source_index.example.yml)：机器可读资料索引示例。
- [source/scope_contract.example.md](source/scope_contract.example.md)：范围契约示例。
- [source/materials/README.md](source/materials/README.md)：教材和课程 markdown 放置规则。
- [research/full_generation_checklist.md](research/full_generation_checklist.md)：发布检查清单。

模板支持两条路径：

- **完整系统生成路径**：基于用户提供的 markdown 资料语料库和范围契约，一次性生成完整、可追溯、可验证的学习系统。
- **MVP 生成路径**：先做 3-8 个技能点的小范围可运行版本。这是可选路径，适合资料尚未齐备或需要先验证教学风格时使用。

这里的完整只表示**完整覆盖用户提供的资料语料库和 `source/scope_contract.md` 声明的学习范围**，不表示覆盖整个学科。

## 共同硬规则

- 不重写 engine。
- 不引入不必要的重型依赖。
- 保留现有自适应运行时和验证命令。
- 核心定义、核心题目、rubric 判分点必须有来源锚点。
- 禁止无来源锚点的核心定义。
- 禁止无来源锚点的题目。
- 禁止虚构教材观点、虚构原文、虚构引用。
- 资料不足时生成 `SOURCE_GAP`，不要编造内容。

## 路径 A：完整系统生成

默认完整工作流：

```text
收集足够教材/课程 markdown
-> 审计资源是否足够完整
-> 一次性生成完整课程系统
-> 运行验证命令和 reviewer gate
-> 修正到 Done When
```

用户至少准备：

```text
source/
├── SOURCE.md
├── scope_contract.md
├── source_index.yml
└── materials/
    ├── textbook-or-primary-source.md
    ├── course-notes.md
    └── paper-or-original.md
```

执行顺序：

1. 复制并填写 `source/scope_contract.example.md` -> `source/scope_contract.md`。
2. 复制并填写 `source/source_index.example.yml` -> `source/source_index.yml`。
3. 把教材、课程笔记、论文、原文等 markdown 放入 `source/materials/`。
4. 按 [docs/RESOURCE_REQUIREMENTS.md](docs/RESOURCE_REQUIREMENTS.md) 通过 Resource Intake Gate。
5. 按 [docs/FULL_SYSTEM_GENERATION.md](docs/FULL_SYSTEM_GENERATION.md) 一次性生成课程级资产。
6. 运行验证命令，并按 reviewer gate 修正。
7. 完成 [research/full_generation_checklist.md](research/full_generation_checklist.md)。

一次性生成的主要资产包括：

- `scripts/config.json`
- `scripts/data/skill_graph.json`
- `scripts/data/graph.nodes.json`
- `scripts/data/graph.edges.json`
- `scripts/content/question_banks/SK-XXX.json`
- `scripts/content/rubrics/SK-XXX.json`
- `teacher/system.md`
- `teacher/system_detail.md`
- `teacher/learner_profile.md`
- 必要时的 `research/source_gaps.md`

如果 Resource Intake Gate 不通过，只能记录 `SOURCE_GAP` 或生成不依赖缺失资料的外围结构，不能生成被缺口阻塞的核心内容。

### Codex /goal 推荐写法

```text
/goal 先收集并检查 source/materials/ 中的教材、课程和论文 markdown 是否足够支撑完整生成；再基于 source/scope_contract.md、source/source_index.yml 和 source/materials/ 一次性生成完整课程系统；最后运行验证命令和 reviewer gate 修正到 Done When。
完整只指覆盖这些资料和声明范围。所有技能、题目和 rubric 必须有 source anchor。资料不足时生成 SOURCE_GAP，不要编造内容。保留现有 engine 和验证命令。
```

## 路径 B：MVP 生成（可选）

MVP 路径保留原有小范围生成方式：

1. 定义 3-8 个技能点的小范围边界。
2. 修改 `scripts/config.json`。
3. 修改 `scripts/data/skill_graph.json`。
4. 更新 `teacher/system.md` 和 `teacher/system_detail.md`。
5. 为每个技能点补 `scripts/content/question_banks/SK-XXX.json`。
6. 为每个技能点补 `scripts/content/rubrics/SK-XXX.json`。
7. 跑验证命令，再逐步扩展。

即使走 MVP 路径，也应保留 source anchor。无法确认来源时，标记为待验证，不要声称 complete。

如果目标从 MVP 升级为完整系统，回到路径 A，补齐 `scope_contract.md`、`source_index.yml` 和 markdown 资料语料库。

## 验证命令

所有命令都在 `scripts/` 下执行。

基础检查：

```bash
python3 -m engine.state show
python3 -m engine.content coverage --only-missing
python3 -m engine.content audit --only-flagged
python3 -m engine.analytics today
```

完整系统发布前：

```bash
python3 -m engine.validate all
python3 -m engine.validate all --strict
python3 -m engine.graph_audit run --strict
python3 -m engine.diagnostic status
python3 -m engine.task_selection next
```

如果某个技能点已设成 `concept_done` 或 `demo_done`，继续抽测：

```bash
python3 -m engine.demo start SK-001
python3 -m engine.session start SK-001
```

## 完整系统 Done When

- Resource Intake Gate 通过，或所有 blocking `SOURCE_GAP` 已由用户处理。
- 每个 include scope item 已映射到 skill、背景资料、排除理由或 `SOURCE_GAP`。
- 每个 skill 有 source、前置关系、状态、mastery 字段、题库和 rubric。
- 题库覆盖 `core`、`misconception`、`boundary`、`transfer`；有前置时覆盖 `bridge`。
- 核心题目和 rubric `must_hit` 都有 source anchor。
- 无虚构引用、虚构教材观点或无来源核心定义。
- strict validation、graph audit、coverage 和 audit 没有 blocking 缺口。
- Reviewer gate 全部 Pass，或所有 blocking findings 已修正并复审通过。
- [research/full_generation_checklist.md](research/full_generation_checklist.md) 已完成。
