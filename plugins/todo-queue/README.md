# todo-queue — Claude Code 持久化任务队列插件

跨会话持久的任务队列 + OpenCode 风格实时 TUI 面板。**默认只显示、不干涉对话流程**
(见下方"被动模式"), 需要它介入时再一条命令开启。解决的痛点:

1. **todo 会丢** — Claude 会话内的 TodoWrite 列表在会话结束/上下文重置后消失。
2. **想法散落各处** — 代码注释里的 TODO/FIXME、聊天里提过的需求, 没人收拢。
3. **多线并行没抓手** — 任务和 agent/worktree/workflow 的对应关系全靠脑记, 想拆给新会话只能复制粘贴。
4. **任务会跑偏** — 需要专注时开 `mode active`, 插件才会约束当前目标任务。

## 工作原理

```
                        ┌──────────────────────────────────┐
  会话内 TodoWrite ──┐  │  .claude/todo-queue.json         │──▶ fork 迁出 ──▶ 新 session
  代码 TODO/FIXME ───┼─▶│  (跨会话持久队列 + 事件日志)      │    (独立队列 / git worktree)
  用户 /add ─────────┘  │  queued ⇄ active ⇄ paused → done │
                        └──────────┬───────────────────────┘
                                   │
      SessionStart hook ◀──────────┤ 新会话带出上会话完成度/遗留目标/暂停任务
      UserPromptSubmit hook ◀──────┤ 被动: 一行只读状态 │ 主动: 目标约束
      Stop hook ◀──────────────────┤ 被动: 从不拦截    │ 主动: 按 auto 推进
      PostToolUse hook ◀───────────┘ 被动: 不改队列    │ 主动: 归集+绑定
```

- **归集 (collect)**: `/todo-queue:collect` 扫描代码注释里的 TODO/FIXME 入队 (随时可用);
  active 模式下 `PostToolUse` hook 还会把会话内的 TodoWrite/TaskCreate 自动汇入并对账。
- **约束 (focus)**: 同一时刻只有一个 active 目标任务。active 模式下 `UserPromptSubmit` hook
  每轮注入目标任务、验收标准和"新需求先入队、别现场展开"的规则。
- **推进 (queue)**: active + `auto on/smart` 时, Stop hook 在队列非空时拦截停止并喂入下一个;
  `max_auto`(默认 10 次/轮) 兜底防死循环, 每次用户发言重置计数。
- **动态绑定 (binding)**: 启动子 agent / Workflow 时 hook 自动把它绑定到当前目标任务;
  激活任务时自动记录所在 session 与 git worktree; 也可 `bind` 手动绑定。UI 与 list 中以
  `⚙agent ⎇worktree wf:xxx s:会话` 标签显示 (worktree 已删除会标 ✗)。
- **生命周期**: `pause`(暂停, 跨会话可 `resume` 恢复, 不参与自动推进) / `cancel`(取消) /
  `fork`(多选迁出到新 session, **迁出即从当前队列移除**)。
- **历史与完成度**: 所有事件 (入队/开始/完成/暂停/迁移/绑定) 记录会话归属;
  `history` 可查各会话完成度与事件流水; 新会话启动自动带出上会话摘要。

## 安装

```
/plugin marketplace add ChenYCL/claude-code-plugin-enhancement
/plugin install todo-queue@claude-code-plugin-enhancement
```

重启 Claude Code 后生效。队列文件按项目独立 (`<项目>/.claude/todo-queue.json`),
也可用环境变量 `TQ_QUEUE_FILE` 指定独立队列 (fork 的新 session 就靠它隔离)。

## 命令

| 命令 | 作用 |
|---|---|
| `/todo-queue:add <任务>` | 入队 (自动提炼标题/优先级/验收标准, 同名去重) |
| `/todo-queue:list` | 查看队列 |
| `/todo-queue:next` | 取下一个任务设为目标并开始执行 |
| `/todo-queue:done [id] [备注]` | 标记完成 (自动模式下顺势接下一个) |
| `/todo-queue:pause [id] [原因]` | 暂停任务, 跨会话保留上下文 |
| `/todo-queue:resume <id>` | 恢复暂停的任务 (恢复 todo 记忆) |
| `/todo-queue:cancel <id> [原因]` | 取消任务 |
| `/todo-queue:focus <id>` | 切换目标任务 |
| `/todo-queue:fork <id...>` | 多选迁移到新 session 单独处理 (支持 --worktree) |
| `/todo-queue:collect [路径]` | 归集代码 TODO 注释 + 会话遗留需求 |
| `/todo-queue:history` | 历史记录 + 各会话完成度 |
| `/todo-queue:mode [passive\|active]` | **切换被动/主动模式** |
| `/todo-queue:setup` | 首次配置引导 (statusline/auto/UI, claude-hud 式交互) |
| `/todo-queue:gc [--dry-run]` | 空间清理 (每日也会自动运行) |
| `/todo-queue:ui` | 打开实时 UI 面板 (OpenCode 风格任务列表) |
| `/todo-queue:auto [on\|off\|smart]` | 自动推进 (仅 active 生效, smart=智能判断) |
| `/todo-queue:status` | 统计概览 (含完成度进度条) |

也可以直接使用 CLI (无需进入 Claude Code):

```bash
python3 plugins/todo-queue/scripts/tq.py add "修复登录超时" -p 1 -a "重试 3 次后仍能登录"
python3 plugins/todo-queue/scripts/tq.py fork tq-2 tq-3 --worktree --launch
```

## UI 面板 (OpenCode 风格)

`/todo-queue:ui` 或手动运行:

```bash
python3 plugins/todo-queue/scripts/tq_ui.py --project /path/to/project   # 交互 TUI
python3 plugins/todo-queue/scripts/tq_ui.py --once [--history]           # 打印一次快照
```

```
 todo-queue   wallet-find
 ~/Documents/wallet-find   被动   ▓▓▓▓░░░░░░ 4/10 (40%)
 ────────────────────────────────────────────────────
当前目标
▌  ▸ tq-3 P1 修复登录超时  ⚙backend ⎇wallet-find-fix s:abcd1234
     验收 重试3次后仍能登录

已暂停 1
   ⏸ tq-7 P3 等第三方接口修复

待办 2
   · tq-5 P2 补充单元测试  wf:run42abc
   · tq-6 P3 更新 README

会话 todos
    ▸ Building the repo map context layer
    ✓ Fix auth timeout

最近完成
    ✓ tq-2 清理死代码
 ────────────────────────────────────────────────────
 会话 abcd1234   2026-08-13 21:40
 j/k 移动  ␣ 多选  n 开始  p 暂停  d 完成  x 取消  m 迁移  h 历史  q 退出
```

- **配色**: 256 色中间调 + 透明背景 (`use_default_colors`), 直接继承终端的 light/dark 主题,
  两种主题下都不突兀; 选中行用左侧色条 `▌` 而非反色块 (反色在 light 主题下会变成刺目的黑底);
  终端只有 8/16 色时自动降级到最接近的基础色。
- 500ms 轮询队列文件, 与 Claude 会话**双向实时同步**: Claude 入队/完成/绑定 agent 会立刻显示,
  面板里的操作下一轮 hook 就会被 Claude 感知。
- **␣ 多选 + m 迁移**: 勾选多个任务按 m, 立即迁出成独立队列并把新 session 启动命令复制到剪贴板。
- **h 历史视图**: 各会话完成度统计 + 最近事件流水。
- "会话 todos" 区直接读取 Claude Code 原生任务存储 (`~/.claude/tasks/session-*`,
  即 Agent SDK todo-tracking 的持久化文件), 会话 ID 由插件 hooks 自动记录关联。
- 建议放 tmux 右侧分屏或独立终端窗口常驻, 效果即 OpenCode 侧栏。

## fork / 迁移到新 session

两种模式 (迁出的任务在原队列标记 migrated 并移除, 是移动不是复制):

| 模式 | 命令 | 隔离方式 | 适用 |
|---|---|---|---|
| 队列文件 | `fork tq-1 tq-3` | 同目录, `TQ_QUEUE_FILE` 指向独立队列 | 纯任务拆分 |
| worktree | `fork tq-1 tq-3 --worktree` | 新建 git worktree + 分支 `tq/<名称>` | 需并行改代码 |

加 `--launch` 自动在新终端 (tmux 窗口 / macOS Terminal) 启动 `claude`, 新 session 的
SessionStart hook 会自动带出迁入的任务队列。

## 任务模型

```jsonc
{
  "id": "tq-3",
  "title": "修复登录超时",
  "detail": "src/auth.ts:42 附近",
  "acceptance": "重试 3 次后仍能登录",   // 完成的验收标准, 约束 done 的门槛
  "priority": 1,                        // 1(最高)~5, next 按 (优先级, FIFO) 取
  "source": "user",                     // user | session(会话归集) | code(注释归集) | collect
  "status": "active",                   // queued | active | paused | done | dropped | migrated
  "binding": {                          // 动态绑定 (hook 自动 + bind 手动)
    "agent": "backend: 排查超时",
    "worktree": "/path/to/wt",
    "workflow": "wf_run42abc",
    "session": "abcd1234"
  }
}
```

## 默认是被动模式 (不干涉对话)

**插件默认只显示状态, 绝不影响对话流程**。这是刻意的设计: 队列的判断可能出错,
而一个会拦截你、会给 Claude 下指令的插件, 出错时代价远大于收益。

| | 被动 (默认) | 主动 (`mode active`) |
|---|---|---|
| Stop hook 拦截 | 从不 | 按 auto 设置 |
| 每轮注入 | 一行只读状态, 明示"用户请求优先" | 目标约束 (专注当前任务、新需求先入队) |
| 自动归集会话 todo | 不做 (用 `/todo-queue:collect` 主动归集) | 自动 |
| done 后 | 只报完成度 | 按 auto 自动接下一个 |
| 队列推进 | 完全由你的命令驱动 | 可自动 |

被动模式下仍然保留的: 状态显示、statusline、UI 面板、所有手动命令、每日 GC。

### auto 三档 (仅 active 模式生效)

- `off` — 每个任务完成后停下
- `smart` — **智能判断**: 只在同批次且定义清晰时自动接下一个; 遇到这些情况主动停下交回用户:
  连续推进已达 3 个 / 下一个任务没有验收标准 / 下一个优先级比刚完成的低 2 级以上 /
  上一个是被取消或迁移而非正常完成
- `on` — 一直推进到队列清空 (max_auto=10 兜底)

## 首次引导

装好即用: 动态绑定、会话记录、每日 GC 默认开启, 干涉性功能默认关闭。
首次会话会提示一次运行 `/todo-queue:setup`, 引导完成 3 项**可选**配置 (类似 claude-hud):

1. **statusline 常驻显示** — 需写入你的 `~/.claude/settings.json`; 已有其它 statusline
   (如 claude-hud) 时自动生成 wrapper 脚本合并两者输出。
2. **auto 自动推进** — 默认关, 且只在 `mode active` 下生效。
3. **UI 面板** — 选择 tmux 分屏或新终端窗口常驻。

## 空间管理 (全自动, 不用管)

数据全部是纯文本 JSON, 典型占用几 KB~几十 KB, 且有硬上限:

| 数据 | 位置 | 上限/策略 |
|---|---|---|
| 队列文件 | `.claude/todo-queue.json` | 已完成保留最近 30 条, 关闭超 14 天归档 |
| 事件日志 | (队列文件内) | 500 条滚动 |
| 归档 | `.claude/todo-queue-archive.jsonl` | 200KB, 超限从最旧端裁剪 |
| fork 队列 | `.claude/todo-queue-forks/` | 清空或 30 天未动自动删除 (任务先并入归档) |
| 会话指针 | `.claude/todo-queue-session.json` | 单文件覆写, <1KB |
| worktree fork | 项目同级目录 | **含代码永不自动删**, GC 报告给出确认后的清理命令 |

GC 每日在 SessionStart 时静默运行一次; `tq.py gc --dry-run` 可随时预览,
`status` 显示当前占用。保留参数可在队列文件 `config.gc` 中调整。
Claude Code 原生任务文件 (`~/.claude/tasks/`) 归 Claude Code 自己管理, 插件只读不写。

## 状态栏集成 (statusline)

在 `~/.claude/settings.json` (或项目 `.claude/settings.json`) 中配置:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 <插件安装路径>/plugins/todo-queue/scripts/tq.py statusline"
  }
}
```

Claude Code 底部会常显: `🎯 tq-3 修复登录超时 │ 待办4 ✔12 60% │ ⏸1 │ Fable 5 │ $2.74`

已有其它 statusline (如 claude-hud) 时, `/todo-queue:setup` 会生成 wrapper 脚本
把 todo-queue 那行追加到原输出下面, 两者共存。

## 设计取舍

- **纯标准库 Python**, 无任何依赖; 原子写 (temp + rename) 防并发损坏。
- 会话归集的任务 (source=session) 完成时自动对账关闭; 用户手动入队的任务必须显式 `done`, 防止 Claude 擅自销单。
- 暂停任务不参与 `next`/自动推进 — 暂停是明确的人为意图, 只能显式 `resume`。
- Stop hook 只在 `auto on` 时拦截; 手动模式下不打扰。
- 事件日志上限 500 条, 自动滚动截断。
- hook 内部任何异常都吞掉并 exit 0, 保证插件故障不阻塞 Claude Code 主流程。
