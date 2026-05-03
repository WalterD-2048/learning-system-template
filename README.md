# 学习系统模板

这是从当前学习系统抽出来的通用模板，用来快速搭建新的个人学习系统。模板保留了通用的 CLI 引擎、typed 知识图谱、诊断、任务选择、学生模型、FIRe v2、间隔复习、示范练习、正式练习、题库覆盖检查和学习分析；具体学科内容需要在复制后替换。

> 目录名按你的要求保留为 `temple`。如果以后想改成 `template`，可以直接重命名文件夹。

## 适用场景

- 原典/教材研读
- 概念密集型学科
- 需要长期复习和练习记录的学习计划
- 想把课程内容、状态和学习日志放在本地仓库里维护

## 目录结构

```text
temple/
├── README.md
├── GENERATE.md
├── CONTENT_QUALITY_CHECKLIST.md
├── requirements.txt
├── source/
│   ├── SOURCE.md
│   ├── source_index.example.yml
│   ├── scope_contract.example.md
│   └── materials/
│       └── README.md
├── scripts/
│   ├── config.json
│   ├── content/
│   │   ├── question_banks/
│   │   │   └── SK-001.json
│   │   ├── rubrics/
│   │   │   └── SK-001.json
│   │   └── schema/
│   ├── data/
│   │   ├── skill_graph.json
│   │   ├── graph.nodes.json
│   │   ├── graph.edges.json
│   │   └── events/
│   └── engine/
└── teacher/
    ├── system.md
    ├── system_detail.md
    ├── main_teacher.md
    ├── assistant_teacher.md
    ├── examiner.md
    ├── learner_profile.md
    ├── progress.md
    ├── analytics.md
    ├── homework_log.md
    ├── diary.md
    ├── book_revision_notes.md
    ├── wechat_unread.md
    └── session_archive.md
```

## 快速开始

1. 复制模板目录：

```bash
cp -R temple my-new-study
cd my-new-study
```

2. 安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

3. 替换主题配置：

- 改 `scripts/config.json` 里的 `subject`、`textbook`、学习强度和复习策略
- 改 `source/SOURCE.md`，放教材、原文摘录、章节索引或资料说明
- 如果要生成完整学习系统，复制 `source/scope_contract.example.md` 为 `source/scope_contract.md`，复制 `source/source_index.example.yml` 为 `source/source_index.yml`，并把教材、课程笔记、论文或原文 markdown 放入 `source/materials/`
- 改 `scripts/data/skill_graph.json`，把示例技能点替换成你的真实技能图谱
- 改 `teacher/system.md` 和 `teacher/system_detail.md`，确定教学角色和工作流
- 给每个技能点补 `scripts/content/question_banks/SK-XXX.json`
- 给每个技能点补 `scripts/content/rubrics/SK-XXX.json`

4. 在 `scripts/` 目录运行检查：

```bash
cd scripts
python3 -m engine.state show
python3 -m engine.content coverage
python3 -m engine.content audit --only-flagged
python3 -m engine.validate all
python3 -m engine.graph_audit run --strict
```

## 用例和风格

如果要基于模板设计新的学习系统，先看 [USE_CASES_AND_STYLES.md](USE_CASES_AND_STYLES.md)。里面给了哲学、经济、交易、政治、历史、数学、写作等方向的用例草案，也给了苏格拉底式、研究生研讨式、严格考官式、案例教练式、复盘审计式、历史叙事式和写作工作坊式等风格预设。

## 生成路径

模板支持两条路径：

- **完整系统生成**：先准备 `source/scope_contract.md`、`source/source_index.yml` 和 `source/materials/*.md`，通过 Resource Intake Gate 后，基于资料语料库生成完整、可追溯、可验证的学习系统。见 [GENERATE.md](GENERATE.md)、[docs/RESOURCE_REQUIREMENTS.md](docs/RESOURCE_REQUIREMENTS.md) 和 [docs/FULL_SYSTEM_GENERATION.md](docs/FULL_SYSTEM_GENERATION.md)。
- **MVP 生成**：先做 3-8 个技能点的小范围版本，跑通概念课、示范练习、正式练习和复习，再逐步扩展。这个路径仍然保留，但属于可选路径。

完整系统发布前使用 [research/full_generation_checklist.md](research/full_generation_checklist.md) 做检查。这里的“完整”只表示覆盖用户提供的资料语料库和声明范围，不表示覆盖整个学科。

## 常用命令

所有命令都在 `scripts/` 目录下执行。

```bash
python3 -m engine.state show
python3 -m engine.state skill SK-001
python3 -m engine.state update SK-001 concept_done
python3 -m engine.diagnostic status
python3 -m engine.task_selection next --target SK-001
python3 -m engine.demo start SK-001
python3 -m engine.session start SK-001
python3 -m engine.session result SK-001 '{"1":"correct","2":"wrong:conceptual","3":"correct","4":"correct","5":"correct","6":"correct","7":"correct","8":"correct"}'
python3 -m engine.event_log tail
python3 -m engine.review due
python3 -m engine.analytics today
python3 -m engine.state export
```

## 核心约定

- `scripts/data/skill_graph.json` 是学习状态的权威数据源。
- `scripts/data/graph.nodes.json` 和 `scripts/data/graph.edges.json` 是 typed knowledge graph 扩展层。
- `scripts/data/events/*.jsonl` 是 item-level 事件日志，用来回放和校准学生模型。
- `teacher/progress.md` 由 `python3 -m engine.state export` 生成，不建议手动维护。
- `teacher/analytics.md` 由 `python3 -m engine.analytics report` 生成。
- `scripts/content/question_banks/*.json` 存题目。
- `scripts/content/rubrics/*.json` 存判分规则。
- 每个技能点建议至少覆盖 `core`、`misconception`、`boundary`、`transfer` 四类题。
- 有前置关系的技能点建议额外设计 `bridge` 或 `cross_skill` 题。
- `prerequisite` 用于解锁和诊断，`encompasses` 用于 FIRe v2 隐式复习；不要把两者混成一种边。

自适应运行细节见 [docs/ADAPTIVE_RUNTIME.md](docs/ADAPTIVE_RUNTIME.md)。模板当前完整度、GitHub 使用方式和具体科目落地注意事项见 [docs/TEMPLATE_OPERATING_NOTES.md](docs/TEMPLATE_OPERATING_NOTES.md)。如果要让 AI 自主探索具体科目的设计方案，按 [docs/AI_RESEARCH_WORKFLOW.md](docs/AI_RESEARCH_WORKFLOW.md) 执行科研式实验流程和多 agent 审查。

## 新系统最小可用线

一个新学习系统至少需要：

- 3-8 个技能点，能跑通一个小章节
- 每个技能点 6-10 道题
- 每个技能点 2-4 个 rubric
- 清晰的概念课、示范练习、正式练习、复习流程
- 一份教材/资料锚点
- 一份学习者画像

做到这一步后，再逐步扩展全书、全课程或全主题。
