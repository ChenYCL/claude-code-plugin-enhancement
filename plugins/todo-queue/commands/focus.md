---
description: 切换当前目标任务
argument-hint: <任务ID>
allowed-tools: Bash(python3:*)
---

运行:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" focus $ARGUMENTS

向用户确认切换结果 (原目标任务会自动退回待办队列), 然后按新目标任务开始工作, 遵守专注约束。
