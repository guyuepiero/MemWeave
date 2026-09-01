---
name: wiki-compile-amazon
description: 公众号文章知识库批量编译（LLM Wiki 模式，面向跨境电商/亚马逊运营内容）。将 06_KNOWLEDGE/RAW/ 下的公众号文章（YAML 头 + Markdown 正文）批量编译为 Obsidian 风格结构化 Wiki 页面（entities/concepts/topics 三类），支持逐篇精编与主题模块化两种策略，强制"全面覆盖 + 忠实原文"质量红线。当用户说"编译 XX 公众号/账号"、"知识库继续编译"、"wiki ingest"、"全量编译"、"把 XX 的文章做成知识库"时应使用本技能。
agent_created: true
---

# Wiki Compile Amazon（公众号知识库批量编译）

## Overview

将 `06_KNOWLEDGE/RAW/<公众号名>/<日期>_<标题>/index.md` 格式的公众号文章（YAML 头含 title/author/source/topic/album/date，正文 Markdown），编译为 `06_KNOWLEDGE/PROCESSED/wiki/` 下的结构化 Wiki 页面。产出可直接在 Obsidian 中打开，双链互引、图谱可视。

## 工作流（4 阶段）

### 阶段 0：侦察与确认（每次执行必做）
1. 扫描目标来源目录：`find . -name "index.md"` 统计篇数，确认目录名准确（中文名可能含空格/特殊字符，先 `ls -d */` 核对）
2. 统计 album/topic 分布（`awk '/^album:/{print $2}'`），确定内容画像
3. 抽验 1-2 篇 YAML 头与正文格式，确认与既有库一致
4. 与用户确认：编译范围（全量/部分）、执行策略（逐篇精编/主题模块化）——除非用户已明确"直接做完不用等确认"

### 阶段 1：编译页面
- 小账号（≤65 篇）→ 逐篇精编概念页（每篇 1 页或系列合并）
- 大账号（≥155 篇）→ **主题模块化**（见 references/compilation-strategy.md）
- 页面模板与命名规范 → references/page-template.md
- 每批 4-8 篇，读完全文再写页，写完即核对

### 阶段 2：质量自检（"全面+准确"双红线）
- 全面：核对编译覆盖篇数 = 总篇数，每页来源清单完整可追溯
- 准确：矛盾标注、原文事实 vs AI 推理区分（详见 references/quality-rules.md）
- 交叉引用：每页 ≥2 个关联链接（互链同类概念/作者/主题，跨来源互链更佳）

### 阶段 3：固化与汇报
1. 更新 `index.md`（总页数/实体/主题/按来源清单）、`log.md`（追加变更记录）、`WIKI-SCHEMA.md`（当前范围）
2. 大任务写入 AI_OS 会话记忆（03_MEMORY/SESSION/SUMMARY/）——按项目记忆规则路由
3. present_files 展示关键产出，汇报进度表（账号/篇数/页数/状态）

## 关键决策规则

| 决策点 | 规则 |
|---|---|
| 逐篇 vs 模块化 | ≤65 篇逐篇；≥155 篇模块化（每页含多篇来源清单）；中间值看内容重合度 |
| 重复文章 | 同文不同日期（diff 校验）→ 合并 1 页，来源清单标注两篇 |
| 图片教程类 | 截图为主文字少的 → 按标题聚合概述，不硬编细节 |
| 系列文章 | QA/技巧/打法系列 → 合并为综合页 + 保留单篇来源清单 |
| 付费/争议内容 | 照常收录，标注来源；高风险操作（翻新/灰产）加风险警示 |

## Resources

### references/page-template.md
页面五段式模板（frontmatter/摘要/详情/关联/引用/变更记录）、命名规范（kebab-case + 类型前缀）、示例页。**编译每页前必读。**

### references/compilation-strategy.md
扫描命令模板、模块划分方法、sed 批量提取要点命令、大账号模块化实践案例（飞翔的波波 155→22 页、Maxdon 320→17 页）、已知坑与应对。

### references/quality-rules.md
"全面+准确"质量红线细则：覆盖核对、忠实原文、矛盾标注、AI 推理区分、引用溯源、防幻觉清单。**编译完成后必读自检。**

## 已知坑（速查，详见 compilation-strategy.md）
- 中文文件名含引号/空格/特殊字符 → 先用 `ls -d` 定位准确路径，勿凭记忆拼接
- 终端输出可能显示乱码（UTF-8 实际正常）→ 不影响 sed 批量提取，可继续
- 卖家精灵等工具商账号含大量福利/推广文 → 单独标注价值低，不硬编
- 上下文累积：长会话中已确认的信息不要重复读取，直接引用
