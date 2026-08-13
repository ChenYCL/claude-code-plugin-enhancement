---
description: 多选任务 fork/迁移到新 session 单独处理 (迁出后从当前队列移除)
argument-hint: <任务ID...> [--worktree] [--launch]
allowed-tools: Bash
---

把用户指定的一个或多个任务迁移到独立的新 session。参数: $ARGUMENTS

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" fork <id...> [--name 名称] [--worktree] [--launch]

模式选择:
- **默认 (队列文件 fork)**: 在同一项目目录建独立队列 (`.claude/todo-queue-forks/`),
  新 session 用 `TQ_QUEUE_FILE` 环境变量指向它, 与当前队列完全隔离。适合无需改代码隔离的任务。
- **`--worktree`**: 创建 git worktree (分支 `tq/<名称>`) 承载新 session, 任务队列放在
  worktree 内。适合需要并行改代码、互不干扰的任务。要求项目是 git 仓库且有提交。

执行规则:
1. 用户说了"新分支/worktree/并行开发"就加 `--worktree`; 否则用默认模式。
2. 默认加 `--launch` 自动在新终端 (tmux 窗口或 macOS Terminal) 启动 claude;
   用户明确说"只导出不启动"才省略。
3. 迁出的任务会自动标记 migrated 并从当前队列移除 (这是移动不是复制), 向用户确认迁出清单。
4. 若 --worktree 失败 (非 git 仓库等), 回退到默认模式并说明。
