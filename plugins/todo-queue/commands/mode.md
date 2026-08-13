---
description: 切换插件模式 — 被动(只显示) / 主动(介入对话流程)
argument-hint: [passive|active]
allowed-tools: Bash(python3:*)
---

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" mode $ARGUMENTS`

把当前模式和它的含义讲清楚给用户:

- **被动 (默认)**: 插件只是个显示器。不拦截你停止、不注入行为约束、不自动改写队列。
  队列里有任务不代表要去做它 —— 一切由用户命令驱动。
- **主动**: 启用目标约束 (每轮注入"专注当前任务、新需求先入队")、auto 自动推进
  (队列非空时拦截停止)、自动归集会话 todo。

切换到 active 前提醒用户: 这会让插件影响对话流程, 随时可以 `/todo-queue:mode passive` 切回。
