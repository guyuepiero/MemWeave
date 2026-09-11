---
name: amazon-scraper-pro
description: |
  自建亚马逊批量采集技能（Playwright + Chromium，免费不限条数）。三种模式：
  - BSR 类目榜单批量：Tools & Home Improvement / Kitchen 等类目 Best Sellers 排行榜 -> 自动提取 ASIN -> 详情页采集 27 字段
  - 新品榜批量：同一脚本 --chart new 走 /gp/new-releases/ 采集新品榜（默认 bsr）
  - ASIN 详情采集：按 ASIN/URL 列表批量抓详情页 27 字段
  - btg-node 工作台模式：从 AmazonOpsMonitor 队列 bsr_queue.json 读类目节点批量采集（含进度上报 --progress-file）
  输出 Excel（.xlsx）+ JSON。带随机延迟/限流冷却/重试/验证码检测/截图比对/自适应滚动。
  特殊能力：monthly_sales 千位制解析(500+/10K+保留原文、New on Amazon 新品标识、常规页无组件记 <50)；Amazon Haul 低价商城页自动识别(s=bazaar)与专属容器解析(price/Haul Typical Price/rating/review)；first_available 初次上架日(前台仅部分 listing 展示)。
  触发场景：抓类目 BSR 榜单、抓新品榜、批量采集商品详情、竞品 ASIN 数据、"跑一下 BSR"、"抓这批 ASIN"、"爬 amazon 数据"。
  NOT for: 评论批量抓取、关键词搜索量（不在本技能范围）。
version: 3.0.0
---

# amazon-scraper-pro —— 自建 Amazon 批量采集

免费、本地、不限条数。替代付费采集工具（Pangolinfo/八爪鱼/Linkfox 已弃用）。

## 环境（已就绪）

- Python venv：`C:\Users\guyuepiero\.workbuddy\binaries\python\envs\default\Scripts\python.exe`
- playwright + chromium + openpyxl 均已安装
- 脚本：本目录 `amazon_batch_v21.py`（v21，自适应滚动版）
- 字段映射：本目录 `field_mapping_v2.json`（v2.2，27 字段）

## 三种模式

| 模式 | 用途 | 说明 |
|---|---|---|
| `bsr` | 类目 BSR 榜单批量 | 走 `/gp/bestsellers/` 排行榜，抓类目前 N 名 |
| `asin` | ASIN 详情 | 按 ASIN/URL 列表批量抓详情 |
| `btg-node` | 工作台队列采集 | 从 AmazonOpsMonitor 队列文件读节点，配合 `--chart bsr\|new` 决定走 BSR 榜还是新品榜 `/gp/new-releases/` |

## 快速开始

```bash
PY="C:/Users/guyuepiero/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

# 模式1：BSR 榜单批量（默认 Kitchen，前3个，有头+截图便于比对验证）
"$PY" ".../amazon_batch_v21.py" --mode bsr --category kitchen --limit 3 --headful --screenshot --out "..."

# 模式1b：新品榜（同 BSR 结构，换 --chart new）
"$PY" ".../amazon_batch_v21.py" --mode bsr --category tools_home_improvement --chart new --pages 2 --limit 100

# 模式2：ASIN 详情
"$PY" ".../amazon_batch_v21.py" --mode asin --asins B0FN5NY3TB,B0C1ABC123 --limit 2

# 模式3：工作台 btg-node（队列文件驱动，工作台进度条轮询用）
"$PY" ".../amazon_batch_v21.py" --mode btg-node --queue "server/data/bsr_queue.json" --out "07_OUTPUTS/xxx" --progress-file "out/_progress.json"
```

## 参数速查

| 参数 | 说明 | 默认 |
|---|---|---|
| `--mode` | `bsr`（榜单批量）/ `asin`（详情）/ `btg-node`（工作台队列） | 必填 |
| `--category` | 类目 key（见 field_mapping 的 categories），仅 bsr 模式 | kitchen |
| `--chart` | `bsr`（Best Sellers 榜）/ `new`（New Releases 新品榜） | bsr |
| `--pages N` | 榜单翻页数 | 1 |
| `--queue` | btg-node 模式：bsr_queue.json 路径（工作台产出） | — |
| `--node` | btg-node 模式：单节点 id（与 --queue 二选一） | — |
| `--slug` | btg-node 模式：节点类目 slug（如 hi / home-improvement，与 --node 配套） | — |
| `--asins` | 逗号分隔 ASIN（asin 模式） | — |
| `--input` | ASIN 列表文件（asin 模式） | — |
| `--limit N` | 小样本限制条数（0=不限） | 0 |
| `--progress-file` | 进度上报文件：每抓完一条 append 一行 JSON `{done,total,cur,ok}`（工作台进度条用，不传跳过） | — |
| `--headful` | 有头模式（建议首次验证用） | 无头 |
| `--screenshot` | 保存详情页截图到 out/screenshots/ | 关 |
| `--delay 3-8` | 随机延迟区间（秒） | 3-8 |
| `--zipcode 90010` | 美区邮编锁定（glow 接口切美区视图，规避港区出口价/卖家失真） | 90010 |
| `--out <dir>` | 输出目录 | out/ |
| `--mapping` | 字段映射文件路径 | 本目录 field_mapping_v2.json |

## 工作流（小样本验证后规模化）

1. **先跑 3 个 ASIN 小样本**：`--limit 3 --headful --screenshot`
2. **截图比对**：打开 `out/screenshots/<ASIN>.png`，与 Excel 字段逐项核对（价格/BSR/卖家等动态字段）
3. **发现差异**：反馈给我，调整 field_mapping_v2.json 的选择器或提取逻辑
4. **规模化**：验证无误后去掉 `--limit`，扩大 `--pages`/ASIN 数量

## 反爬策略（内置）

- 随机 UA（Chrome/Edge/Firefox 轮换）
- 每请求随机延迟 3-8 秒 + 失败指数退避（2s/4s/8s）
- 验证码/机器人页检测 -> 停止并提示人工处理（不硬闯）
- 每 ASIN 最多重试 3 次
- 遇限流：优先等待冷却，不强制突破（主公原则）
- 榜单页**自适应滚动**：每滚 700px 停 0.5-0.75s 数商品链接，连续 4 轮不增长判定到底（兜底 60 轮）——数量锁 100 条时两榜均约 102 ASIN

## 输出字段（27 个，field_mapping_v2.json v2.2）

asin / title / brand / price / list_price / rating / review_count / monthly_sales / haul / first_available / bsr_main / bsr_main_category / bsr_sub / bsr_sub_category / bestseller_badge / amazon_choice / bullets / dimensions / weight / color / availability / seller / shipped_by / coupon / image_url / url / scraped_at

- 抓不到的字段输出 `—`（不编造）
- seller 字段自动标注 `(自营)` / `(第三方)`
- bullets 为列表，Excel 中以换行展示
- 文件名规范（工作台口径）：`amazon_{bsr|new}_<key>_<YYYYMMDD>_FINAL.json/.xlsx`，归档 07_OUTPUTS/bsr_<key>_<n>/ 或 new_<key>_<n>/

### 特殊字段语义（v2.2）

| 字段 | 取值规则 |
|---|---|
| `monthly_sales` | 千位制保留原文：<1000 纯数字如 `500+`，≥1000 用 K 如 `10K+`；无数字但有「New on Amazon」组件记 `New on Amazon`；常规页面两组件皆无记 `<50`（前台月销不足 50 不显示）；Haul 页记 `—` |
| `haul` | URL 含 `s=bazaar` → `Amazon Haul`（低价商城页），否则 `—`。haul 页价格/划线价(Haul Typical Price)/评分/评论数由 haul 专属容器解析，常规解析不适用 |
| `first_available` | Product information 表 Date First Available 行 → 上架日期 `YYYY-MM-DD`。⚠️ 前台对热品/老 listing/Haul 页常不渲染该行，无值记 `—`（覆盖率可能 <10%，统计口径须注明样本量） |

## 已知边界

- Amazon 反爬强：无头模式可能触发验证码，优先用 `--headful` 或降低频率
- 动态字段（价格/BSR）以抓取时刻为准，需在 `scraped_at` 时间戳下解读
- 评论批量、关键词搜索量不在本技能范围
- **部分浏览节点没有 New Releases 榜（2026-09-11 实测）**：无榜节点访问 `gp/new-releases/<slug>/<node>` 仍返回 **200、`<title>` 正常**，但商品网格为空 → 脚本会「成功」抓到 0~2 条并 `exit=0`，极易被误判为空榜或采集中断。实测 27 个节点 **17 个无榜**（15 个大类根节点里 13 个无榜；同一大类内叶子也混杂，如 `home-improvement/553398` Wire Strippers 无榜、`home-improvement/6396128011` Cable Staples 有榜）⇒ 无结构规律，必须逐节点判。
  **采集前预检（纯 HTTP，约 1.3s，无需浏览器）**：GET 该 URL（带浏览器 UA），数 HTML 中 `zg-grid-general-faceout` 出现次数，**≥3 才有榜**（实测有榜 = 31、无榜 = 1）。工作台实现：`AmazonOpsMonitor/CODE/server/app/nr.py` → `python -m app.nr check <slug> <node>`（缓存 `data/nr_index.json`）。
