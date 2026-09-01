# AGENTS.md — 工作区入口指南

本工作区使用 **AI_OS** 作为唯一记忆系统与协作框架。任何 Agent 进入本工作区后，请按以下顺序读取，并**默认沿用**本系统规则（无需另行口头确认）：

- `00_BOOTSTRAP/BOOTSTRAP.md` — 启动协议（先读）
- `01_SYSTEM_RULES/` — 系统强制规则（TOKEN_OPTIMIZATION_POLICY.md + AGENT_COMMON_RULES.md）
- `02_USER_CONTEXT/` — 用户上下文（USER.md / AGENTS.md / SOUL.md）
- `CURRENT_CONTEXT.md` — 当前工作状态快照

## 最高优先级：Token 节省

Token 节省是本工作区**最核心的规则**（P0，详见 `01_SYSTEM_RULES/TOKEN_OPTIMIZATION_POLICY.md`）。核心原则：**在保证正确性和质量的前提下，最小化 Token 消耗**。

- **最小读取**：先索引 → 摘要 → 目标文件；不默认加载整个工作区、知识库或历史记录。
- **小范围优先**：先小范围执行并验证，再扩大范围；避免大规模未验证修改。
- **增量执行**：复杂任务拆分为 目标 → 阶段 → 步骤 → 验证点。
- **输出控制**：默认简洁、结构化（完成内容 / 修改内容 / 验证结果 / 下一步）。
- **记忆按触发词写入**：平时对话不自动写记忆，避免每轮浪费。

## 其他规则

读取优先级、记忆路由、安全修改、唯一记忆系统等详细规则见 `01_SYSTEM_RULES/AGENT_COMMON_RULES.md` 与 `RULES_INDEX.md`，此处不重复。
