---
description: 添加任务到持久化 todo 队列
argument-hint: <任务描述> [紧急/优先级说明]
allowed-tools: Bash(python3:*)
---

用户想把一个任务加入 todo 队列。任务内容: $ARGUMENTS

使用 Bash 运行 (标题务必加引号):

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" add "<标题>" [-p 优先级] [-d "<详情>"] [-a "<验收标准>"]

规则:
- 从用户输入中提炼一句简洁标题; 背景细节放进 `-d`, 明确的完成标准放进 `-a`
- 优先级 1(最高)~5, 默认 3; 用户说"紧急/优先"时用 `-p 1` 或 `-p 2`
- 运行后把任务 ID 和标题告知用户即可, **不要**现在就开始做这个任务
