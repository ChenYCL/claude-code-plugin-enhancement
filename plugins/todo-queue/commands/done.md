---
description: 标记当前目标任务完成 (可指定任务 ID)
argument-hint: [任务ID] [备注]
allowed-tools: Bash(python3:*)
---

先确认目标任务已**真正完成**(代码可运行/验证通过/满足验收标准), 再运行:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" done $ARGUMENTS

- 若输出显示自动推进激活了下一个任务: 直接继续执行下一个任务。
- 否则: 向用户汇报本次完成情况与剩余队列数量。
- 若任务其实没做完, 不要标记, 先继续完成。
