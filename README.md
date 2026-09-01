# AI_OS v1.0 — 可复用的 AI Agent 记忆系统框架

> 一套**跨 Agent、跨平台**的本地记忆与协作框架。
> 让 ChatGPT / Claude / WorkBuddy / Trae / Codex / Qoder / Hermes 等不同工具，读写同一套规则、记忆与技能。

---

## 它解决什么问题

AI Agent 的记忆是碎的：换个工具就失忆，换个会话就重来，上下文塞满了还是记不住重点。

AI_OS 的思路不是「把所有信息塞进上下文」，而是建立一套**文件系统即记忆**的结构：

| 痛点 | AI_OS 的做法 |
|---|---|
| 换个 Agent 就失忆 | 规则与记忆存在本地目录，任何 Agent 都能读同一份 |
| 上下文爆炸、Token 烧不起 | 索引 → 摘要 → 目标文件，按需加载，绝不整库读取 |
| 每次会话从零开始 | `CURRENT_CONTEXT.md` + 会话总结，随时恢复进度 |
| 经验无法沉淀 | 会话记忆 → 项目记忆 → 技能库，三级沉淀 |
| Agent 自由发挥、乱改文件 | 系统规则优先级高于一切，安全修改规则约束写操作 |

---

## 核心设计

### 四个原则

```text
1. 节省 Token    —— 一切设计的基准，最小读取、按需加载
2. 效率优先      —— 先问再做，简单优先，不搞多余动作
3. 记忆持续      —— 触发词驱动写入，闭环归档、中断转储
4. 数据安全      —— 数据只在本机流转，删前备份、改动留痕
```

### 六个动作准则

```text
全量保存 · 最小读取 · 按需加载 · 小范围验证 · 验证后交付 · 有价值才沉淀
```

### 三层记忆区分

| 层级 | 存什么 | 特点 |
|---|---|---|
| 会话记忆 `03_MEMORY/SESSION/` | 这一次做了什么 | 有时间戳，持续累积，1:1 round mapping |
| 项目记忆 `04_PROJECTS/<P>/MEMORY.md` | 这个项目永远成立什么 | 无时间戳，保持精简 |
| 系统规则 `01_SYSTEM_RULES/` | 所有项目都成立什么 | 最高优先级，不可被偏好覆盖 |

> 判断标准：**信息三个月后仍然成立 → 写项目记忆；只用于恢复当前进度 → 写会话记忆。**

---

## 目录结构

```text
AI_OS/
├── AGENTS.md                 # 工作区入口，Agent 进来的第一份文件
├── CURRENT_CONTEXT.md        # 当前工作状态快照（高频读写）
├── 00_BOOTSTRAP/             # 启动协议：读什么、按什么顺序、Token 预算
├── 01_SYSTEM_RULES/          # 系统强制规则（P0/P1）
├── 02_USER_CONTEXT/          # 用户画像、协作风格、Agent 人设
├── 03_MEMORY/                # 会话记忆（ORIGINAL 原始 / SUMMARY 总结）
├── 04_PROJECTS/              # 项目工作区（含 _TEMPLATE 模板）
├── 05_SKILLS/                # 技能库（COMMON 通用 / AGENT_SPECIFIC 专属）
├── 06_KNOWLEDGE/             # 个人知识库（原始资料 → 结构化知识）
└── 07_OUTPUTS/               # 输出资产区（代码/文档/数据/工具）
```

| 目录 | 用途 | 读取策略 |
|---|---|---|
| `00_BOOTSTRAP/` | Agent 启动协议、Token 预算 | 每次会话先读 |
| `01_SYSTEM_RULES/` | Token 优化、通用行为规则、规则索引 | 先索引后目标 |
| `02_USER_CONTEXT/` | 用户是谁、如何协作、Agent 人设 | 会话初加载 |
| `03_MEMORY/` | 会话总结 + 原始记录 | 总结按需读，原始仅追溯 |
| `04_PROJECTS/` | 每个项目独立目录（TASK / MEMORY / CODE / DATA / DOCS） | 按任务加载 |
| `05_SKILLS/` | 技能索引 + 模板 + 具体技能 | 先读 INDEX，再加载单个技能 |
| `06_KNOWLEDGE/` | 知识库原文与整理稿 | 按主题检索，**禁止全量读取** |
| `07_OUTPUTS/` | 交付产物 | 生成时写入，复用时检索 |

---

## 快速上手

### 1. 克隆到本地

```bash
git clone https://github.com/guyuepiero/AI-OS-Memory.git AI_OS
cd AI_OS
```

### 2. 把入口文件挂到你的 Agent

- **自动加载型**（WorkBuddy / Claude Code / Codex 等支持 `AGENTS.md` 的）：直接把这个目录设为工作区即可，规则自动生效。
- **手动型**（ChatGPT / 网页版）：把 `AGENTS.md` 内容贴进自定义指令或项目说明。

### 3. 填你的信息

| 文件 | 填什么 |
|---|---|
| `02_USER_CONTEXT/USER.md` | 你是谁、做什么、常用工具 |
| `02_USER_CONTEXT/SOUL.md` | Agent 人设与风格 |
| `CURRENT_CONTEXT.md` | 当前在做什么、下一步是什么 |
| `04_PROJECTS/<你的项目>/` | 复制 `_TEMPLATE/`，改名为项目名 |

改完即可使用。框架本身不需要任何依赖、不需要数据库、不需要联网。

---

## Agent 默认工作流程

```text
打开 Agent
-> 读 00_BOOTSTRAP/BOOTSTRAP.md
-> 读 01_SYSTEM_RULES/RULES_INDEX.md
-> 加载必要系统规则
-> 读 02_USER_CONTEXT/
-> 读 CURRENT_CONTEXT.md
-> 识别任务类型
-> 按需加载 项目 / 技能 / 知识 / 会话总结
-> 小范围执行
-> 验证结果
-> 交付任务
-> 总结有价值信息
-> 更新记忆与当前状态
```

### 记忆写入路由

```text
跨会话长期有效的用户信息     -> 02_USER_CONTEXT/
项目长期有效的决策/架构/经验 -> 04_PROJECTS/<PROJECT>/MEMORY.md
项目当前进度                -> 04_PROJECTS/<PROJECT>/TASK.md
全局当前状态快照            -> CURRENT_CONTEXT.md
本次任务恢复摘要            -> 03_MEMORY/SESSION/SUMMARY/YYYY-MM-DD_主题.md
需追溯的原始过程            -> 03_MEMORY/SESSION/ORIGINAL/
```

**注意**：记忆按**触发词驱动**写入，不是每轮都写。闭环词（完成/交付/总结）→ 归档；中断词（暂停/下次再说）→ 转储；普通轮次不写。

---

## 不应该做的事

- ❌ 不要默认读取整个知识库
- ❌ 不要默认读取完整历史会话
- ❌ 不要把临时想法全部写入长期记忆
- ❌ 不要把用户偏好混入系统强制规则
- ❌ 不要为管理而管理，避免框架过度复杂

---

## 关于本仓库

本仓库上传的是**框架骨架**（规则 / 模板 / 索引 / 说明），不含任何实际数据：

| 已包含 | 已排除 |
|---|---|
| 系统规则、启动协议、用户上下文模板 | 实际会话记忆（`03_MEMORY/SESSION/`） |
| 项目模板 `04_PROJECTS/_TEMPLATE/` | 实际项目数据 |
| 技能索引 + 技能模板 | 知识库原文、输出产物 |
| 各目录 README 说明 | 本地工具配置、业务文件 |

`.gitignore` 已预置排除规则，克隆后可以直接往里填自己的内容，不会误提交敏感数据。

欢迎 fork 改造。若你在这个框架上长出更好的结构，欢迎回来提 issue 交流。
