---
description: 查看 todo 历史记录与各会话完成度
argument-hint: [--current 仅当前会话]
allowed-tools: Bash(python3:*)
---

## 历史记录

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" history $ARGUMENTS`

把上面的信息整理给用户: 总完成度、各会话的完成情况 (哪个会话完成了几个任务)、
以及最近的关键事件 (完成/迁移/暂停)。不必逐行复述事件流水。
