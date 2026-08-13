---
description: 暂停任务 (默认当前目标任务), 可稍后 resume 恢复
argument-hint: [任务ID] [原因]
allowed-tools: Bash(python3:*)
---

运行:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" pause $ARGUMENTS

向用户确认暂停结果。暂停的任务不参与自动推进, 会保留全部上下文 (详情/验收标准/绑定),
跨会话持久, 之后任何会话里 `/todo-queue:resume <id>` 都能恢复。
暂停当前目标后, 可用 /todo-queue:next 继续队列中的其它任务。
