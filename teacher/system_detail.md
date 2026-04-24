# 系统操作规范

## 概念课

概念课目标是让学习者能用自己的语言说清一个技能点的核心问题、基本定义、适用边界和典型误解。

流程：

1. 读取 `python3 -m engine.analytics today` 的建议
2. 确认是否有到期复习或挂起技能点
3. 选择一个 `unlocked` 或需要继续的技能点
4. 读取该技能点在 `skill_graph.json` 中的描述和资料锚点
5. 用提问推进理解，不直接堆结论
6. 结束时总结学习者已经能稳定说出的内容和仍不稳定的内容
7. 用 `python3 -m engine.state update SK-XXX concept_done` 写回状态

## 示范练习

示范练习用于从讲授过渡到独立练习。

开始前运行：

```bash
python3 -m engine.demo start SK-XXX
```

按输出的 `question_plan` 推进：

- `worked_example`：教师完整示范
- `faded_example`：教师给骨架，学习者补关键步骤
- `independent_try`：学习者独立尝试，教师只给短反馈

结束后运行：

```bash
python3 -m engine.state update SK-XXX demo_done
```

## 正式练习

开始前运行：

```bash
python3 -m engine.session start SK-XXX
```

按输出的题型、作答形式和题库 ID 出题。选择题必须要求解释理由。

结束后写回：

```bash
python3 -m engine.session result SK-XXX '{"1":"correct","2":"wrong:conceptual"}'
```

推荐使用结构化结果：

```bash
python3 -m engine.session result SK-XXX '{"answers":{"1":"correct","2":"wrong:conceptual"},"planned_total":8,"question_types":{"1":"conceptual","2":"scenario"},"answer_format":{"1":"short_answer","2":"short_answer"},"source_skill":{"1":"SK-XXX","2":"SK-XXX"},"used_exercises":["SK-XXX-Q01","SK-XXX-Q02"]}'
```

## 间隔复习

开始前运行：

```bash
python3 -m engine.review due
```

完成后写回：

```bash
python3 -m engine.review complete SK-XXX 0.8
```

准确率传入 `0.0-1.0` 之间的小数。

## 内容检查

每次新增或改动题库后运行：

```bash
python3 -m engine.content coverage --only-missing
python3 -m engine.content audit --only-flagged
```

## 导出

```bash
python3 -m engine.state export
python3 -m engine.analytics report
```

导出的 `progress.md` 和 `analytics.md` 是系统视图，不是手写笔记。
