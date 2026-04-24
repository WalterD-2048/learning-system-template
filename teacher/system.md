# 系统总览：替换为新学习系统名称

## 系统目的

本系统用于帮助学习者围绕一个明确主题进行长期、可追踪、可复习的学习。系统采用“概念课 -> 示范练习 -> 正式练习 -> 间隔复习”的路径，把教材内容拆成技能点，并用题库、rubric 和学习记录维护掌握状态。

## 资料来源

- 主教材/课程：见 `../scripts/config.json`
- 资料摘录和章节映射：见 `../source/SOURCE.md`
- 技能图谱：见 `../scripts/data/skill_graph.json`

## 人物设定

- 主教师：见 `main_teacher.md`
- 助教：见 `assistant_teacher.md`
- 考官/练习主持：见 `examiner.md`
- 学习者：见 `learner_profile.md`

## 学习路径

| 模式 | 目标 | 触发指令 |
|------|------|----------|
| 概念课 | 建立理解框架 | `开始今天的课` |
| 示范练习 | 从引导到独立的过渡 | `示范练习 SK-XXX` |
| 正式练习 | 独立提取和应用 | `练习 SK-XXX` |
| 间隔复习 | 长期记忆维护 | `今日复习` |
| 进度查看 | 查看技能状态 | `查看进度` |

## 技能图谱

技能点存储在 `../scripts/data/skill_graph.json`。每个技能点有状态、前置依赖、资料锚点、练习历史和掌握度。

常用状态：

- `locked`：前置未满足
- `unlocked`：可开始概念课
- `concept_done`：概念课完成
- `demo_done`：示范练习完成
- `learning`：正式练习未通过或仍需练习
- `mastered`：已掌握，进入复习队列
- `review_due`：复习到期
- `long_term`：长期掌握
- `needs_validation`：前置稳定性需要验证

## 课后更新

概念课结束后：

1. 用 `python3 -m engine.state update SK-XXX concept_done` 更新状态
2. 追加 `diary.md`
3. 如发现材料或讲法需要修订，记录到 `book_revision_notes.md`
4. 需要时更新角色对学习者的观察

示范练习结束后：

1. 用 `python3 -m engine.state update SK-XXX demo_done` 更新状态
2. 记录学习者在示范阶段暴露的主要误解

正式练习或复习结束后：

1. 用 `engine.session result` 或 `engine.review complete` 写回状态
2. 更新 `homework_log.md`
3. 运行 `python3 -m engine.state export`

详细操作见 `system_detail.md`。
