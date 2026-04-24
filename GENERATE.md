# 从模板生成新学习系统

这份清单用于把 `temple` 复制成一个具体学科的学习系统。

## 1. 定义系统边界

先写清楚四件事：

- 学什么：书、课程、技能、考试或项目
- 学到什么程度算掌握
- 学习材料来自哪里
- 一次学习课/练习课大约多长

建议先做一个小范围版本，不要一开始覆盖整本书。

## 2. 配置系统

修改 `scripts/config.json`：

- `subject`：学科或系统名称
- `classification`：内容类型，可用 `A/B/C/D` 自定义解释
- `textbook`：主教材、课程或资料来源
- `intensity`：`low`、`medium` 或 `high`
- `questions_per_session`：一次正式练习题量
- `mastery_threshold`：掌握阈值
- `review_schedule`：间隔复习节奏

## 3. 设计技能图谱

修改 `scripts/data/skill_graph.json`。

每个技能点至少需要：

```json
{
  "name": "技能点名称",
  "description": "这个技能点要求学习者会什么",
  "prerequisites": [],
  "source": {
    "textbook": "资料来源",
    "chapter": "章节",
    "section": "小节"
  },
  "complexity": "medium",
  "status": "unlocked",
  "dates": {},
  "practice_history": [],
  "consecutive_failures": 0,
  "bound_exercises": [],
  "exercise_anchor": "原文或材料锚点",
  "mastery_score": 0.05
}
```

初始状态建议：

- 第一个技能点：`unlocked`
- 有前置依赖的技能点：`locked`
- 已经讲完概念课的技能点：`concept_done`
- 已经完成示范练习的技能点：`demo_done`

## 4. 写 teacher 工作流

修改 `teacher/system.md` 和 `teacher/system_detail.md`：

- 主教师如何讲课
- 助教什么时候补充
- 考官如何出题和判分
- 概念课结束后要更新哪些文件
- 练习课结束后要记录哪些结果

角色文件可以按系统需要改名，也可以继续使用：

- `main_teacher.md`
- `assistant_teacher.md`
- `examiner.md`
- `learner_profile.md`

## 5. 建题库和 rubric

每个技能点对应两类文件：

```text
scripts/content/question_banks/SK-001.json
scripts/content/rubrics/SK-001.json
```

题库至少覆盖：

- `core`：核心概念
- `misconception`：常见误解
- `boundary`：边界判断
- `transfer`：迁移应用

有前置依赖时建议增加：

- `bridge`：连接当前技能和前置技能
- `cross_skill`：跨技能综合

## 6. 跑检查

在 `scripts/` 下执行：

```bash
python3 -m engine.state show
python3 -m engine.content coverage --only-missing
python3 -m engine.content audit --only-flagged
python3 -m engine.analytics today
```

如果已经把某个技能点设成 `concept_done` 或 `demo_done`，可以继续测试：

```bash
python3 -m engine.demo start SK-001
python3 -m engine.session start SK-001
```

## 7. 再扩展

等小范围版本能稳定运行后，再批量扩展技能点和题库。每扩一批，先跑覆盖检查，再开始真实学习。
