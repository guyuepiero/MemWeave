---
title: "douyin-video-transcribe"
summary: "抖音视频下载+口播文案提取（SSR失效后的浏览器拦截方案），自包含可迁移技能"
agent_created: true
---

# 抖音视频下载与文案提取

抖音视频 → 本地 mp4 + 口播文案 txt。本技能自包含（SKILL.md + 脚本 + 配置同目录），随 AI_OS 框架迁移，任何 Agent / 任何电脑可用。

## 触发词
下载抖音视频、提取抖音文案、抖音口播、抖音转文字、抖音链接处理

## 环境已就绪声明（零配置）

本技能依赖已全部预装于本机，Agent 直接执行以下流程，**无需任何安装步骤**：

- 共享 Python（含 httpx / faster-whisper / imageio-ffmpeg）：`$HOME/.workbuddy/binaries/python/envs/default/Scripts/python.exe`
- agent-browser CLI（v0.27.0）：`$HOME/.workbuddy/binaries/node/workspace/node_modules/.bin/agent-browser`
- ffmpeg：imageio-ffmpeg 附带 exe，config.json `ffmpeg_path` 留空时自动探测（勿改）
- faster-whisper 模型：small/base 均已缓存，无需下载

## 标准工作流

### 第1步：解析短链拿 video_id
```bash
curl -sL -A "Mozilla/5.0" -o /dev/null -w "%{url_effective}\n" "https://v.douyin.com/XXXX/"
```

### 第2步：浏览器拦截详情 API（SSR 失效，必须走这条）
```bash
AB="$HOME/.workbuddy/binaries/node/workspace/node_modules/.bin/agent-browser"
"$AB" network requests --clear
"$AB" open "https://www.douyin.com/video/<video_id>"
sleep 5
"$AB" network requests --filter "aweme/detail" --type xhr   # 记下请求ID
"$AB" network request <请求ID> --json > detail.json
```

### 第3步：下载 + 提取文案
```bash
VENVPY="$HOME/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
export HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1
"$VENVPY" douyin_fetch.py download <video_id> --keyword <搜索关键字> --json detail.json
```

## 产物
```
~/抖音下载/<关键字>/
├── yyyy-MM-dd <关键字>.mp4   ← 视频
└── yyyy-MM-dd <关键字>.txt   ← 口播文案（含ID/标题/作者/互动/来源头）
```

## 配置（config.json，与本脚本同目录）
- `subtitle.model`：ASR 档位，`small`（默认更准）或 `base`（更快）
- `subtitle.max_length`：文案截断长度，0=不截断
- `ffmpeg_path`：ffmpeg 可执行路径（Windows 需填，macOS 可留空走 PATH）
- `output_dir`：输出根目录（默认 `~/抖音下载/`）

## 踩坑记录（必读）

1. **SSR 解析已失效**：抖音改版后 RENDER_DATA 不再含视频详情，脚本直取页面必然失败。必须浏览器拦截 → `--json`。
2. **签名**：详情 API 需浏览器生成的 a_bogus；无签名 fetch 返回 200 空 body。
3. **body 捕获不稳定**：agent-browser 请求日志 body 可能被丢弃，须清空日志→重开页面→立即查。
4. **faster-whisper 模型下载**：必须设 `HF_ENDPOINT=https://hf-mirror.com` + `HF_HUB_DISABLE_XET=1`（新版默认 xet 通道，镜像 401）。
5. **Windows snapshot 0字节 bug**：HF 缓存 snapshot 引用文件可能 0 字节（符号链接失败）→ 按大小匹配 `blobs/` 目录手动 cp 修复。
6. **文案截断 bug**：原 max_length=200 会把文案截到 200 字，已改 0。
7. **ASR 术语误转**：专业术语会误转（卖家精灵→Safe、ASIN→Eason、ABA→ab a、挂绳→夸神），交付需人工修正说明。
8. **下载频率**：大量下载可能触发反爬，建议控制频率。

## 验证方式
- 输出目录出现 .mp4（>0字节）与 .txt（含「【口播文案】」头 + 全文）
- 脚本 stdout 显示「✅ 文案已保存: xxx.txt (N字)」

## 迁移说明
本目录（SKILL.md + douyin_fetch.py + config.json）完整自包含，本机环境已预装全部依赖，**零配置直接运行**。

迁移到其他电脑/环境时：
- 预装 Python 依赖（httpx / faster-whisper / imageio-ffmpeg）到共享 venv
- 安装 agent-browser CLI 并初始化浏览器 runtime
- 改 config.json 的 `ffmpeg_path`（Windows）与 `output_dir`
- 将本 SKILL.md 中的 venv / agent-browser 绝对路径改为目标环境路径
