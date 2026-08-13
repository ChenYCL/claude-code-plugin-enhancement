---
description: 首次配置引导 — 逐项确认可选功能 (statusline/auto/UI 面板), 类似 claude-hud 的交互
allowed-tools: Bash, Read, Edit, Write, AskUserQuestion
---

引导用户完成 todo-queue 的可选配置。核心功能 (归集/约束/绑定/GC) 已默认开启, 无需配置。

## 第一步: 检查现状

运行: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" setup-check`

## 第二步: 逐项询问用户 (用 AskUserQuestion, 已配置好的项跳过)

**1. statusline 底部常驻显示** (`🎯 tq-3 修复登录超时 │ 待办4 ✔12 60% │ auto开`)
- 若 setup-check 显示"未配置": 询问是否开启; 同意则把以下写入 `~/.claude/settings.json`
  (用 python 读-改-写合并 JSON, 保留其它字段, 不要整文件覆盖):

      "statusLine": {"type": "command", "command": "python3 '${CLAUDE_PLUGIN_ROOT}/scripts/tq.py' statusline"}

- 若显示"已被其它命令占用" (如 claude-hud): 询问是否合并显示; 同意则生成 wrapper 脚本
  `~/.claude/tq-statusline-wrapper.sh` 并把 statusLine.command 指向它:

      #!/bin/bash
      input=$(cat)
      a=$(echo "$input" | <原有命令>)
      b=$(echo "$input" | python3 '${CLAUDE_PLUGIN_ROOT}/scripts/tq.py' statusline)
      printf '%s │ %s\n' "$a" "$b"

  记得 chmod +x。原有命令从 setup-check 输出里取。

**2. auto 自动推进** (默认关)
- 说明影响: 开启后队列非空时会拦截 Claude 停止、连续执行直到清空 (max_auto=10 兜底)。
  适合"丢一堆任务让它自己跑"的用法; 日常对话建议关, 随时可 /todo-queue:auto on 临时开。
- 用户选开则运行: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" auto on`

**3. UI 面板** (OpenCode 风格实时任务列表)
- 询问是否现在打开; 同意则按 /todo-queue:ui 的方式启动 (tmux 分屏或新终端窗口)。

## 第三步: 收尾

1. 运行: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" setup-check --mark` (新会话不再提示)
2. 汇总: 哪些已开启、哪些跳过、之后如何再次配置 (随时可再运行 /todo-queue:setup)。
