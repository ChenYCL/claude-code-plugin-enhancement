---
name: todo-queue
description: 管理持久化任务队列 (todo queue)。当用户提到待办、todo、任务队列、入队、排队、归集任务、下一个任务、专注当前任务、别跑偏、暂停任务、恢复任务、迁移任务到新会话, 或会话中出现应当延后处理的新需求时使用。
---

# todo-queue 使用手册

本项目安装了 todo-queue 插件: 一个跨会话持久的任务队列, 用于归集待办并约束当前目标任务。

- 存储: `$TQ_QUEUE_FILE` 或 `<项目>/.claude/todo-queue.json` (纯 JSON, 可直接查看/编辑)
- CLI: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" <子命令>`

## 默认是被动模式 (最重要)

插件默认 **只显示状态, 不干涉对话流程**。这意味着:

1. **不要**因为队列里有任务就主动去做它 —— 用户没让你做的事就别做。
2. **不要**因为用户提了新想法就自动入队 —— 只有用户说"记下来/加到队列"时才 `add`。
3. 每轮注入的 `<todo-queue-status>` 是纯参考信息, 用户本轮的请求永远优先。
4. 队列的推进完全由用户命令驱动: `/todo-queue:next`、`done`、`pause`、`fork`。
5. 用户显式运行 `mode active` 后, 才启用目标约束/自动推进/自动归集 (下面的规则才适用)。

## active 模式下的约束 (仅当用户开启)

1. 任何时刻最多只有一个"当前目标任务" (active)。
2. 执行目标任务期间发现的新需求 → `add` 入队并告知用户, 不现场展开做。
3. 目标任务的完成标准是其 acceptance 字段; 验证通过后才能 `done`。
4. 会话内 TodoWrite/TaskCreate 产生的子任务会被 hook 自动归集 (source=session)。
5. 启动子 agent / workflow 时 hook 自动绑定到当前目标任务 (binding 字段)。

## 任务生命周期

queued → active (next/focus/resume) → done
                ↘ paused (pause, 可跨会话 resume 恢复, 不参与自动推进)
queued/active/paused → dropped (cancel) / migrated (fork 迁出到新 session)

## 子命令速查

| 命令 | 作用 |
|---|---|
| `add "<标题>" [-p 1-5] [-d 详情] [-a 验收标准]` | 入队 (同名去重) |
| `list [--all]` / `status` / `path` | 查看队列 / 概览(含完成度) / 文件路径 |
| `next` | 激活下一个任务 (优先级小者先, 同级 FIFO, 跳过暂停) |
| `done [id] [备注]` | 标记完成; 自动模式下顺势激活下一个 |
| `pause [id] [备注]` | 暂停 (默认当前目标); `resume <id>` 恢复 |
| `focus <id>` / `cancel <id>` | 切换目标 / 取消任务 |
| `bind <id> [--agent A] [--worktree W] [--workflow WF]` | 手动绑定 (通常 hook 自动完成) |
| `fork <id...> [--worktree] [--launch]` | 多选迁移到新 session (迁出即从当前队列移除) |
| `history [--current]` | 历史事件 + 各会话完成度 |
| `gc [--dry-run]` | 空间清理 (每日自动运行, 一般无需手动) |
| `setup-check [--mark]` | 可选配置状态检查 (供 /todo-queue:setup 用) |
| `mode [passive\|active]` | **被动(默认,只显示) / 主动(介入对话)** |
| `auto [on\|off\|smart]` | 自动推进 (仅 active 生效; smart=按批次与验收标准判断) |

## 典型工作流

- 用户丢来一堆想法 → 逐条 `add`, 然后 `next` 开始第一个。
- 用户说"把这些活干完再喊我" → `auto on` + `next`, Stop hook 会驱动队列直到清空。
- 任务被外部条件卡住 → `pause` 并说明原因, `next` 换下一个; 条件满足后 `resume`。
- 用户说"这几个任务拆出去单独搞" → `fork tq-X tq-Y --launch` (要并行改代码加 `--worktree`)。
- 新会话开始 → SessionStart hook 自动带出上会话完成度、遗留目标与暂停任务, 按提示恢复。
- 用户问"进展如何/上次干了啥" → `history` 汇报各会话完成度。
