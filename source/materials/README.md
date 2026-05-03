# Source Materials

把教材、课程笔记、论文、原文、讲义和题源的 markdown 文件放在这个目录。完整系统生成会把这些文件视为资料语料库；没有放入并写进 `source/source_index.yml` 的资料，不能作为核心定义、题目或 rubric 的依据。

## 推荐结构

```text
source/materials/
├── primary-textbook.md
├── course-week-01.md
├── course-week-02.md
├── paper-smith-2021.md
└── original-text.md
```

如果资料很多，可以分子目录，但 `source_index.yml` 里的 `path` 必须指向真实文件。

## 每份资料应包含

推荐在文件开头写简短元信息：

```markdown
# 资料标题

- source_id: TXT-001
- type: textbook
- edition: 第 1 版
- language: zh-CN
- original_locator: 第 1 章 / p. 12-38 / Week 1 transcript
```

正文要求：

- 保留原始章节、小节、页码、讲义页码或视频时间戳。
- 用稳定标题或 HTML anchor 标出核心段落。
- 一处资料只表达一个来源，不把教材、笔记和 AI 摘要混在一起。
- 公式、定义、例题、案例和引用尽量保持原编号。
- OCR 或转写内容需要人工抽查，尤其是数字、公式、术语和引用。

## Anchor 示例

```markdown
## 第 1 章 核心概念

<a id="ch01-sec01-def-core"></a>
### 1.1 核心定义

这里放教材原文、课程笔记或用户整理的可引用内容。

<a id="ch01-sec02-example-1"></a>
### 1.2 例 1

这里放例题或案例。
```

在 `source_index.yml` 中引用：

```yaml
anchors:
  - id: "TXT-001#ch01-sec01-def-core"
    source_path: "source/materials/primary-textbook.md#ch01-sec01-def-core"
```

## 不能作为唯一依据的内容

- 没有原文支撑的 AI 摘要。
- 没有章节、页码、标题或时间戳的零散摘录。
- 用户记忆中的教材观点，除非补成明确笔记并标明来源性质。
- 搜索结果片段或未保存的网页。

这些内容可以帮助发现缺口，但不能单独支撑核心定义、题目或 rubric。
