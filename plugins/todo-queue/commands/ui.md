---
description: 打开 todo 队列实时 UI 面板 (OpenCode 风格任务列表)
allowed-tools: Bash
---

为用户打开 todo-queue 的实时任务面板。面板命令是:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq_ui.py" --project "<当前项目绝对路径>"

按环境选择打开方式 (依次判断):

1. **tmux 内** (`$TMUX` 非空): 用 Bash 运行
   `tmux split-window -h 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq_ui.py" --project "<项目路径>"'`
   在右侧分屏常驻显示。
2. **macOS**: 用 osascript 打开新 Terminal 窗口:

       osascript -e 'tell application "Terminal"' \
                 -e 'do script "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/tq_ui.py\" --project \"<项目路径>\""' \
                 -e 'activate' -e 'end tell'

3. **其它**: 直接把完整命令打印给用户, 让其在另一个终端 pane 自行运行。

面板 500ms 轮询队列文件, Claude 这边的任何入队/完成操作都会实时反映; 面板内也可直接操作
(j/k 选择, ␣ 多选, n 开始, p 暂停/恢复, d 完成, x 取消, m 迁移选中任务到新 session,
+/- 调优先级, a 自动推进, h 历史视图, q 退出)。

打开后告知用户面板已启动及按键说明, 不要等待面板进程退出。
