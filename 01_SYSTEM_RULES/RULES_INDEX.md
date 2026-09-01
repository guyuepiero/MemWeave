# 规则索引

## 规则优先级

```text
P0 TOKEN_OPTIMIZATION_POLICY.md
P1 AGENT_COMMON_RULES.md
P2 项目 / 技能 / 用户规则
```

## 规则边界

`SYSTEM_RULES` 定义 Agent 必须遵守的系统行为规则。

`USER_CONTEXT` 定义当前用户的协作偏好和工作方式。

如果发生冲突：

```text
SYSTEM_RULES > USER_CONTEXT > PROJECT RULES > SESSION HISTORY
```

## 必读规则文件

- `TOKEN_OPTIMIZATION_POLICY.md`：控制资源、上下文、Token、执行规模和输出规模。
- `AGENT_COMMON_RULES.md`：定义通用行为、真实性、验证、可恢复性、复用、记忆和安全修改规则。

任何 Agent 首次阅读规则后默认沿用本系统，本规则自动生效，无需另行确认。

## 记忆位置约束

AI_OS 是本工作区唯一的记忆系统。

任何 Agent 都不得把记忆写入 AI_OS 之外的自带记忆目录。

会话记忆与项目记忆必须分开，具体路由见 `AGENT_COMMON_RULES.md` 的记忆写入规则。

会话归档按触发词执行：闭环触发词写 `03_MEMORY/SESSION/`（总结+原始），中断触发词写根目录 `CURRENT_ORIGINAL.md`，平时对话不自动写入。

## 修改安全约束

对框架文件的任何改动都必须先备份、可回退。

默认只增不改、只改不删。删除或覆盖前必须先备份到 `_BACKUP_YYYY-MM-DD/`，并保留至用户确认最终版可用。

详见 `AGENT_COMMON_RULES.md` 的安全修改规则。
