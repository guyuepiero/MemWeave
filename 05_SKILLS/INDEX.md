# 技能索引

Agent 加载技能文件前，应先读取本索引。

**同步机制（P2，见 `01_SYSTEM_RULES/SKILL_SYNC_RULE.md`）：** 通用技能在 `05_SKILLS/COMMON/` 存工作区副本，供框架内所有 Agent 使用；技能有更新时，须同步复制副本并更新本索引，保证框架版本最新。仅 WorkBuddy 独占、无副本的技能，在下表登记指针。

## 名称对照表（中文市场名 ↔ 技能真名 ↔ 目录名）

WorkBuddy UI 技能管理页显示 `_skillhub_meta.json` 的 `name`；AI 侧 `@` 调用与技能加载读 `SKILL.md` 的 `name`。2026-09-03 起**两者已统一为真名**。三者对应关系如下（**一律以真名为准**）：

| 技能真名（权威） | 市场中文名（旧显示） | 安装目录 | 框架副本 |
|---|---|---|---|
| `amazon-scraper-pro` | —（自建，本无中文名） | `~/.workbuddy/skills/amazon-scraper-pro/` | `05_SKILLS/COMMON/amazon-scraper-pro/` |
| `amazon-selection-agent` | 亚马逊选品引擎 | `~/.workbuddy/skills/amz-selection-engine__skillhub/` | `05_SKILLS/COMMON/amz-selection-engine/` |
| `douyin-video-fetch` | 抖音文案提取 | `~/.workbuddy/skills/douyin-extract-copywriter__skillhub/` | `05_SKILLS/COMMON/douyin-video-fetch/` |
| `wiki-compile-amazon` | —（自建） | `~/.workbuddy/skills/wiki-compile-amazon/` | `05_SKILLS/COMMON/wiki-compile-amazon/` |
| `resume-optimization-workflow` | —（自建） | `~/.workbuddy/skills/resume-optimization-workflow/` | `05_SKILLS/COMMON/resume-optimization-workflow/` |

> 改名只动 `_skillhub_meta.json` 的 `name` 字段，**`slug`（安装标识）一律不动**——改 slug 会断掉技能市场的更新检测与卸载识别。原文件已备份在 `05_SKILLS/_BACKUP_2026-09-03/rename/`。
> ⚠️ 若技能市场后续重新安装/更新该技能，`name` 可能被回写为中文，届时按上表重新改回即可。

## 通用技能（工作区副本，供跨 Agent 复用）

| 技能真名 | 用途 | 副本路径 |
|---|---|---|
| `amazon-scraper-pro` | 亚马逊批量采集：BSR 榜单/ASIN 详情 27 字段（v2.2：monthly_sales 千位制+New on Amazon+<50 兜底 / haul 低价商城识别与专属解析 / first_available 上架日）。输出 xlsx+json | `05_SKILLS/COMMON/amazon-scraper-pro/` |
| `amazon-selection-agent` | 亚马逊全链路选品：市场扫描→竞品拆解→FBA 利润测算→关键词挖掘；本地采集数据扩展维度（销量/品牌销量占比/卖家类型/上架时间） | `05_SKILLS/COMMON/amz-selection-engine/` |
| `douyin-video-fetch` | 抖音视频下载为 mp4 + 口播文案提取（API 字幕优先、SenseVoice ASR 兜底；支持按互动数据筛选高价值视频）。v2.0.0 | `05_SKILLS/COMMON/douyin-video-fetch/` |
| `wiki-compile-amazon` | 公众号知识库批量编译：06_KNOWLEDGE/RAW 文章 → Obsidian Wiki 页面（entities/concepts/topics，逐篇精编/主题模块化） | `05_SKILLS/COMMON/wiki-compile-amazon/` |
| `resume-optimization-workflow` | 简历优化全流程：PDF 提取→百分制评分→40 项清单润色→打印友好 HTML 导出→头像提取 | `05_SKILLS/COMMON/resume-optimization-workflow/` |
| `github-push-windows` | GitHub 推送三件套：Windows/PortableGit 下 push 排障（坑 23/25/26：exec-path 缺 helper、沙箱代理拦截、refs 引用缺失） | `05_SKILLS/COMMON/github-push-windows/`（**已同步用户级** `~/.workbuddy/skills/github-push-windows/`，2026-09-11） |

## 变更记录

- **2026-09-03 抖音新版覆盖**：旧副本 `douyin-video-transcribe/` 备份至 `05_SKILLS/_BACKUP_2026-09-03/douyin-video-transcribe/`，框架副本改用真名 `douyin-video-fetch/`（与权威源 `~/.workbuddy/skills/douyin-extract-copywriter__skillhub/` diff 一致）。
- **2026-09-03 统一显示名为真名**：`amazon-selection-agent`（原"亚马逊选品引擎"）、`douyin-video-fetch`（原"抖音文案提取"）的 `_skillhub_meta.json` 中 `name` 已改为真名，`slug` 未动；原文件备份于 `05_SKILLS/_BACKUP_2026-09-03/rename/`。索引条目统一以真名为标题，并新增上方「名称对照表」。
- **2026-09-03 索引去重**：删除已失效的 `douyin-video-transcribe/` 旧条目（目录已删），消除与新版重复登记。
- **2026-09-11 `github-push-windows` 同步用户级**：此前**仅存在项目侧**，导致技能列表搜不到（主公反馈"找不到上传更新的技能"）。已复制到 `~/.workbuddy/skills/github-push-windows/`，MD5 校验一致（`1F6CA640B11EE4CB702CCFA2C5CC6488`）；安全审计 P2（单文件纯 markdown，无脚本/无凭据/无破坏性命令）。同步前该技能已按当日实测补三条：坑 25 非必现（先直推再切 Clash）、坑 23 push 后必复发须手写 40 位哈希 refs、强制直连必失败。

## Agent 专属技能

| Agent | 用途 | 路径 |
|---|---|---|
| Codex | 编程、调试、本地仓库工作 | `05_SKILLS/AGENT_SPECIFIC/CODEX/` |
| Trae | IDE 工作流、应用构建 | `05_SKILLS/AGENT_SPECIFIC/TRAE/` |
| Qoder | 编程工作流 | `05_SKILLS/AGENT_SPECIFIC/QODER/` |
| WorkBuddy | 工作协调与流程管理 | `05_SKILLS/AGENT_SPECIFIC/WORKBUDDY/` |
| Hermes | 研究与分析 | `05_SKILLS/AGENT_SPECIFIC/HERMES/` |
