# 内容质量检查清单

## 技能图谱

- 每个技能点都有明确名称和描述
- 每个技能点都有资料来源锚点
- 前置关系不会形成循环
- 初始状态符合学习路径
- `mastery_score` 与 `status` 大致一致
- 不把过大的章节塞进一个技能点

## 题库

- 每个技能点至少有核心题、误解题、边界题和迁移题
- 选择题不超过正式练习题量的少数部分
- 每个选择题都要求解释理由
- 题目不是只改几个名词的重复模板
- 题目锚点能指向具体段落、公式、案例或操作步骤
- 有前置依赖的技能点包含桥接题

## Rubric

- 每个题目引用的 `rubric_id` 都存在
- `must_hit` 写的是可判定要点，不是泛泛评价
- `common_failures` 覆盖常见错误信号
- `partial_credit_rules` 能处理半对半错的答案
- `error_type_mapping` 能把错误映射到后续补救训练

## Teacher 工作流

- 概念课有清晰结束条件
- 示范练习有完整示范、部分提示、独立尝试三个阶段
- 正式练习能记录正确率、错误类型、题型和作答形式
- 复习课能用到历史错误
- 课后更新文件有明确分工

## 运行检查

在 `scripts/` 下执行：

```bash
python3 -m engine.state show
python3 -m engine.content coverage --only-missing
python3 -m engine.content audit --only-flagged
python3 -m engine.analytics today
```
