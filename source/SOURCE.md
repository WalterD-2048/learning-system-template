# 资料源

把这个文件替换成新学习系统的资料说明。

如果要走完整系统生成路径，还需要：

- 复制 `source/scope_contract.example.md` 为 `source/scope_contract.md`，写清学习范围、排除范围、学习者假设和完成标准。
- 复制 `source/source_index.example.yml` 为 `source/source_index.yml`，登记资料文件、版本、优先级、anchor 和范围映射。
- 把教材、课程笔记、论文、原文等 markdown 文件放入 `source/materials/`。

可以放：

- 教材目录
- 原文摘录
- 课程链接说明
- 章节到技能点的映射
- 重要术语表
- 练习题来源说明

建议每个技能点都能在这里找到可追溯锚点，例如：

```text
SK-001 -> 第 1 章第 1 节，核心定义段落
SK-002 -> 第 1 章第 2 节，例题 1-3
SK-003 -> 第 2 章第 1 节，定理和证明
```

完整系统生成时，核心定义、核心题目和 rubric 判分点都必须有来源锚点。资料不足时生成 `SOURCE_GAP`，不要编造教材观点或引用。
