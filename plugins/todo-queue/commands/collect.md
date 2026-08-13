---
description: 归集 TODO — 扫描代码注释与本次会话中的待办, 汇入持久队列
argument-hint: [扫描路径, 默认整个项目]
allowed-tools: Bash(python3:*), Grep, Glob, Read
---

把散落的 TODO 归集进持久队列。扫描范围: $ARGUMENTS (为空则为整个项目)。

执行步骤:

1. **扫描代码注释**: 用 Grep 搜索模式 `TODO|FIXME|HACK|XXX` (输出模式 content, 带行号),
   忽略 .git、node_modules、dist、build、vendor、.claude 等目录。
2. **回顾本次会话**: 找出用户提到过、但既没完成也没入队的需求或想法。
3. **逐条入队** (脚本会按标题自动去重, 已存在的会提示跳过):

       python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" add "<提炼的标题>" --source code -d "<文件:行号 | 注释原文>"

   会话来源的用 `--source collect`。
4. 最后运行 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tq.py" list`, 向用户汇总: 新增几条、跳过几条。

**只归集, 不要开始执行任何任务。**
