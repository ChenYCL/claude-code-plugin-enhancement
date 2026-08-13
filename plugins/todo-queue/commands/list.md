---
description: 查看持久化 todo 队列
argument-hint: [--all 显示全部历史]
allowed-tools: Bash(python3:*)
---

## 当前队列

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" list $ARGUMENTS`

把上面的队列状态整理成简洁清单展示给用户, 保持任务 ID 可见。
若队列为空, 提示可用 /todo-queue:add 添加任务, 或 /todo-queue:collect 归集散落的 TODO。
