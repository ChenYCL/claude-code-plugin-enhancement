---
description: 取出队列中下一个任务并开始执行 (设为当前目标任务)
allowed-tools: Bash(python3:*)
---

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" next`

根据上面的输出:

- **若激活了任务**: 立即开始执行该任务, 并遵守约束——专注于此任务范围, 期间发现的新需求用
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" add "<标题>"` 入队而不是顺手去做。
  完成并验证后运行 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" done`, 然后向用户汇报。
- **若队列为空**: 告知用户, 建议用 /todo-queue:add 或 /todo-queue:collect 补充任务。
