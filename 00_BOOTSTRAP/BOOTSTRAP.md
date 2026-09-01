# 启动协议

这是每个 Agent 进入 AI_OS 后应该首先读取的文件。

## 启动流程

1. 读取 `00_BOOTSTRAP/BOOTSTRAP.md`。
2. 读取 `00_BOOTSTRAP/TOKEN_BUDGET.md`。
3. 读取 `01_SYSTEM_RULES/RULES_INDEX.md`。
4. 加载必要系统规则：
   - `01_SYSTEM_RULES/TOKEN_OPTIMIZATION_POLICY.md`
   - `01_SYSTEM_RULES/AGENT_COMMON_RULES.md`
5. 读取用户上下文：
   - `02_USER_CONTEXT/USER.md`
   - `02_USER_CONTEXT/AGENTS.md`
   - `02_USER_CONTEXT/SOUL.md`
6. 读取 `CURRENT_CONTEXT.md`。
7. 识别任务类型。
8. 只加载当前任务需要的资源：
   - 项目记忆
   - 技能
   - 知识
   - 会话总结
   - 原始会话记录仅在必要时读取
9. 执行、监控、验证并交付任务。
10. 任务结束前按 `AGENT_COMMON_RULES.md` 收尾：验证完成 → 按触发词判断是否写入记忆 → 同步 `CURRENT_CONTEXT.md`。

## 默认规则

不要加载整个工作区。优先读取索引、摘要和目标文件。

任何 Agent 首次阅读本文件及 `01_SYSTEM_RULES/` 后，即默认认可并沿用本系统，本系统规则对其自动生效，无需另行口头确认。若 Agent 的运行环境对规则有强制性要求，可先执行环境要求，但仍以本系统规则为准绳，并在 `CURRENT_CONTEXT.md` 中说明差异。

各 Agent 的协作偏好、技能差异等属于"适配当前用户/任务的配置层"，应写入 `02_USER_CONTEXT/` 与 `05_SKILLS/`，不得与系统强制规则冲突（冲突时 `SYSTEM_RULES > USER_CONTEXT`）。
