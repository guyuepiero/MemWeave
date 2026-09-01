# 01_SYSTEM_RULES 系统规则目录说明

本目录保存所有 Agent 必须遵守的系统级规则。

系统规则是 AI_OS 的底层约束，优先级高于用户偏好、项目规则和会话历史。

## 目录结构

```text
01_SYSTEM_RULES/
├── README.md
├── RULES_INDEX.md
├── TOKEN_OPTIMIZATION_POLICY.md
└── AGENT_COMMON_RULES.md
```

## 文件用途

### RULES_INDEX.md

规则索引。

用于告诉 Agent 当前规则体系有哪些文件、规则优先级是什么、规则冲突时如何处理。

### TOKEN_OPTIMIZATION_POLICY.md

Token 优化规则。

这是最高优先级规则，约束 Agent 如何读取内容、执行任务、写代码、调用工具和输出结果。

核心原则：

```text
正确性和质量优先前提下，Token 消耗最小化。
```

### AGENT_COMMON_RULES.md

Agent 通用行为规则。

用于定义所有 Agent 的基本工作方式，包括：

- 先理解再行动
- 简单优先
- 精准修改
- 目标驱动
- 验证后交付
- 真实性优先
- 上下文意识
- 记忆读取优先级
- 可恢复性
- 先复用再创建
- 记忆写入规则

## 使用规则

- Agent 不应跳过本目录规则直接执行任务。
- 系统规则只放“所有 Agent 都必须遵守”的内容。
- 用户个人偏好应放入 `02_USER_CONTEXT/`。
- 项目特定规则应放入对应项目目录。

