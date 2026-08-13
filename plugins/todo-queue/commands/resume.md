---
description: 恢复暂停的任务
argument-hint: <任务ID>
allowed-tools: Bash(python3:*)
---

运行:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" resume $ARGUMENTS

- 若输出显示已恢复为当前目标: 按该任务的详情/验收标准继续工作 (这就是"恢复 todo 记忆")。
- 若输出显示恢复到待办 (已有其它目标任务): 告知用户, 继续当前目标。
