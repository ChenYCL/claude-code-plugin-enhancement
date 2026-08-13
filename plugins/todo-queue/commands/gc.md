---
description: 空间清理 — 归档旧任务、回收 fork 队列 (每日也会自动运行)
argument-hint: [--dry-run 只预览]
allowed-tools: Bash(python3:*)
---

## GC 报告

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" gc $ARGUMENTS`

把结果简要汇报给用户。若报告中出现"worktree fork 任务已清空"的清理建议,
询问用户是否执行给出的 `git worktree remove` 命令 (含代码, 不会自动删)。
