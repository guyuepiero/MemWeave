# 页面模板与命名规范

编译每页前必读。产出页面统一五段式结构，保证知识库风格一致、可机器检索。

## 目录结构

```
06_KNOWLEDGE/PROCESSED/wiki/
├── WIKI-SCHEMA.md   ← 规则总纲（命名/模板/质量）
├── index.md         ← 总索引（全部页面导航）
├── log.md           ← 变更日志（追加式）
├── entities/        ← 实体页：人/账号/公司/产品（"谁"）
├── concepts/        ← 概念页：方法论/机制/术语（"怎么想/怎么做"）
└── topics/          ← 主题页：专辑综述/专题（"哪个领域"）
```

## 命名规范（kebab-case，强制）

```
[类型前缀]-[主体描述].md
```

| 前缀 | 目录 | 示例 |
|---|---|---|
| `entity-` | entities/ | `entity-littlec-ac.md`（阿C哥） |
| `concept-` | concepts/ | `concept-cosmo-algorithm.md` |
| `topic-` | topics/ | `topic-maxdon.md`（账号综述） |
| `source-summary-` | concepts/ | `source-summary-destiny.md`（个人随笔类文章摘要页） |

规则：
- 全小写 + 连字符，不用下划线（Markdown 强调语法冲突）、不用中文（引号/问号是文件路径隐患）
- 主体描述用英文意译，聚焦主题词（如 deal-net-price-rule 而非 long-article-about-deals）
- 前缀即"身份证"：grep "concept-" 可秒数概念页

## 页面五段式模板

### 1. 概念页（concept-）

```markdown
---
type: concept
title: <中文标题>
aliases:
  - <别名1>
  - <别名2>
source: <公众号名>（<专辑名>）
status: complete
tags:
  - 亚马逊
  - <主题标签>
---

# <中文标题>

> 来源: [[entities/entity-xxx]] | <日期范围>

## 摘要
<2-4 句话概括核心结论，写"是什么"，不写背景铺垫>

## 详情
<分小节结构化展开，善用表格；公式用代码块/行内代码；关键数字必须与原文一致>

### 一、<小节>
...

## 关联
- 同库互链: [[concepts/concept-xxx]]（一句话说明关系）
- 交叉验证: [[concepts/concept-yyy]]（不同来源同主题）

## 引用来源
- <公众号名>: <日期> <标题> / <日期> <标题>

## 变更记录
- YYYY-MM-DD: 编译
```

### 2. 实体页（entity-，作者/账号）

```markdown
---
type: entity
title: <作者名>
aliases: [...]
status: active
tags: [作者, 亚马逊, ...]
---

# <作者名>

## 摘要
<作者定位 + 内容画像一句话>

## 详情
### 内容画像（表格：板块/篇数/特征）
### 内容特点（分点）

## 关联
- 主题: [[topics/topic-xxx]]
- 相关作者: [[entities/entity-yyy]]（对比关系说明）

## 引用来源
- RAW 原始文章：`06_KNOWLEDGE/RAW/<账号>/`（N 篇）

## 变更记录
```

### 3. 主题页（topic-，账号综述）

```markdown
---
type: topic
title: <账号名>全量综述
status: complete
tags: [主题, ...]
---

# <账号名>综述
> N 篇全量编译 | 日期 | 作者: [[entities/entity-xxx]]

## 主题定位（一句话）
## 知识地图（按板块分组的页面链接清单，每行含一句话说明）
## 关键结论（3-5 条跨页面提炼）
## 变更记录
```

### 4. 来源摘要页（source-summary-，个人随笔/感悟类）

适用于无方法论价值的个人叙事类文章：精炼摘要 + 金句，篇幅控制在概念页 1/3。

## 质量基准

- 摘要 ≤100 字；详情用表格/列表，避免大段散文
- 每页 ≥2 个 `[[关联]]`（与同库页面互链，优先跨来源）
- 数字/公式/政策条款**必须与原文逐字一致**，禁止改写
- 原文观点与 AI 推理混用时必须标注（见 quality-rules.md）
