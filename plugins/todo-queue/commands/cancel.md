---
description: 取消队列中的某个任务
argument-hint: <任务ID> [原因]
allowed-tools: Bash(python3:*)
---

运行:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" cancel $ARGUMENTS

向用户确认已取消的任务。
