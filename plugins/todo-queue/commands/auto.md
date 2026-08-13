---
description: 自动推进模式 off | on | smart (仅在 active 模式下生效)
argument-hint: [on|off|smart]
allowed-tools: Bash(python3:*)
---

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" auto $ARGUMENTS`

向用户说明三档的区别:

- **off**: 每个任务完成后停下等指令。
- **smart**: 只在"同批次且定义清晰"时自动接下一个; 遇到下列情况主动停下交回用户 ——
  连续推进已达 3 个、下一个任务没有验收标准、下一个优先级比刚完成的低 2 级以上、
  上一个是被取消/迁移而非正常完成。
- **on**: 队列非空就一直推进到清空 (max_auto=10 兜底)。

**重要**: 这三档只在 `mode active` 下生效。被动模式 (默认) 下插件不拦截对话,
auto 设置会被保存但不起作用 —— 如果用户想要它生效, 需要先 `/todo-queue:mode active`。

