---
description: 放弃队列中的某个任务
argument-hint: <任务ID> [原因]
allowed-tools: Bash(python3:*)
---

运行:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" drop $ARGUMENTS

向用户确认已放弃的任务。
