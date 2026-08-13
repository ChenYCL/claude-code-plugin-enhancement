#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""todo-queue UI — OpenCode 风格的实时任务面板。

用法:
  python3 tq_ui.py [--project 路径]       交互 TUI
  python3 tq_ui.py --once [--history]     打印一次快照后退出 (预览/脚本用)

按键:
  j/k 移动  space 多选  n/⏎ 开始  p 暂停/恢复  d 完成  x 取消
  m 迁移(fork)选中到新 session  +/- 优先级  a 自动推进  h 历史视图  q 退出

数据源:
  1. $TQ_QUEUE_FILE 或 <项目>/.claude/todo-queue.json — 插件持久队列
  2. ~/.claude/tasks/session-<会话前8位>/*.json        — Claude Code 原生会话任务 (SDK todo-tracking)
"""
import argparse
import json
import os
import subprocess
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tq  # noqa: E402

NATIVE_ICON = {"pending": "·", "in_progress": "▸", "completed": "✓"}
STATUS_GLYPH = {"queued": "·", "active": "▸", "paused": "⏸",
                "done": "✓", "dropped": "✕", "migrated": "↗"}

# 配色: 256 色中间调 —— 亮度居中的色相在 light/dark 终端上都可读, 且不刺眼。
# 背景一律透明 (curses use_default_colors + ANSI 只设前景), 直接继承终端主题,
# 因此不会在任一主题下出现突兀的色块。选中行用左侧色条而非反色块 (反色在
# light 主题下会变成刺目的黑底)。
PALETTE = {
    #  语义         256色  ANSI回退   加粗
    "title":     (75,  "\033[38;5;75m",  True),   # 柔和天蓝
    "accent":    (109, "\033[38;5;109m", True),   # 灰蓝, 分区标题
    "focus":     (73,  "\033[38;5;73m",  True),   # 青绿, 当前目标
    "warn":      (179, "\033[38;5;179m", False),  # 琥珀, 暂停
    "ok":        (108, "\033[38;5;108m", False),  # 鼠尾草绿, 完成
    "danger":    (167, "\033[38;5;167m", False),  # 砖红, 失效/取消
    "dim":       (245, "\033[38;5;245m", False),  # 中灰, 两主题皆可读
    "muted":     (240, "\033[38;5;240m", False),  # 更淡, 分隔线
    "normal":    (None, "", False),               # 跟随终端前景色
    "mark":      (140, "\033[38;5;140m", False),  # 淡紫, 多选标记
}
RESET = "\033[0m"


# ---------- CJK 宽度处理 ----------

def clip(s, width):
    out, w = "", 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in "FW" else 1
        if w + cw > width - 1:
            return out + "…"
        out += c
        w += cw
    return out


# ---------- 数据源 ----------

def session_info():
    try:
        with open(os.path.join(tq.project_dir(), ".claude", "todo-queue-session.json"),
                  encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def tasks_root():
    return os.environ.get("CLAUDE_TASKS_ROOT") or os.path.expanduser("~/.claude/tasks")


def native_tasks():
    sid = (session_info().get("session_id") or "")[:8]
    if not sid:
        return []
    d = os.path.join(tasks_root(), "session-{}".format(sid))
    try:
        files = [f for f in os.listdir(d) if f.endswith(".json")]
    except OSError:
        return []
    files.sort(key=lambda f: int(f[:-5]) if f[:-5].isdigit() else 0)
    items = []
    for fn in files:
        try:
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                items.append(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
    return items


def selectable_tasks(state):
    """可选中操作的任务: 进行中 → 暂停 → 待办。"""
    active = [t for t in state["tasks"] if t["status"] == "active"]
    return active + tq.paused_tasks(state) + tq.queued(state)


# ---------- 面板内容 ----------

def task_row(t, selected, marked):
    bar = "▌" if selected else " "        # 左侧色条代替反色块, light/dark 都不刺眼
    mark = "◆" if marked else " "
    row = "{}{} {} {} P{} {}".format(
        bar, mark, STATUS_GLYPH.get(t["status"], "·"),
        t["id"], t.get("priority", 3), t["title"])
    tags = tq.fmt_binding(t)
    return row + ("  " + tags if tags else "")


def build_board(state, native, sel, marks):
    lines = []
    q = tq.queued(state)
    paused = tq.paused_tasks(state)
    sel_list = selectable_tasks(state)
    sel_id = sel_list[sel]["id"] if sel_list and 0 <= sel < len(sel_list) else None

    lines.append(("accent", "当前目标"))
    active = [t for t in state["tasks"] if t["status"] == "active"]
    if active:
        for t in active:
            lines.append(("focus", task_row(t, t["id"] == sel_id, t["id"] in marks)))
            if t.get("acceptance"):
                lines.append(("dim", "     验收 {}".format(t["acceptance"])))
            if t.get("detail"):
                lines.append(("dim", "     {}".format(t["detail"])))
    else:
        lines.append(("dim", "     无 — 选中任务后按 n 开始"))
    lines.append(("normal", ""))

    if paused:
        lines.append(("accent", "已暂停 {}".format(len(paused))))
        for t in paused:
            lines.append(("warn", task_row(t, t["id"] == sel_id, t["id"] in marks)))
        lines.append(("normal", ""))

    lines.append(("accent", "待办 {}".format(len(q))))
    if q:
        for t in q:
            style = "focus" if t["id"] == sel_id else "normal"
            lines.append((style, task_row(t, t["id"] == sel_id, t["id"] in marks)))
    else:
        lines.append(("dim", "     空"))
    lines.append(("normal", ""))

    if native:
        lines.append(("accent", "会话 todos"))
        for t in native:
            st = t.get("status", "pending")
            text = t.get("activeForm") if st == "in_progress" else t.get("subject", "")
            style = {"in_progress": "warn", "completed": "dim"}.get(st, "normal")
            lines.append((style, "    {} {}".format(NATIVE_ICON.get(st, "·"), text)))
        lines.append(("normal", ""))

    done = [t for t in state["tasks"] if t["status"] == "done"]
    if done:
        lines.append(("accent", "最近完成"))
        for t in done[-4:]:
            lines.append(("ok", "    ✓ {} {}".format(t["id"], t["title"])))
        lines.append(("normal", ""))
    return lines


def build_history(state):
    lines = [("accent", "会话统计")]
    cur = (tq.current_session_id() or "")[:8]
    sessions, per = [], {}
    for e in state["log"]:
        s = e.get("session") or "-"
        if s not in per:
            per[s] = {"touched": set(), "done": set()}
            sessions.append(s)
        if e.get("task"):
            per[s]["touched"].add(e["task"])
            if e["event"] == "done":
                per[s]["done"].add(e["task"])
    for s in sessions[-8:]:
        mark = "  ← 当前" if s == cur and s != "-" else ""
        style = "focus" if s == cur and s != "-" else "normal"
        lines.append((style, "    {}   完成 {} / 触达 {}{}".format(
            s, len(per[s]["done"]), len(per[s]["touched"]), mark)))
    lines.append(("normal", ""))
    lines.append(("accent", "事件记录"))
    styles = {"done": "ok", "migrate": "warn", "cancel": "danger",
              "pause": "warn", "add": "dim", "bind": "dim", "resume": "ok"}
    for e in state["log"][-25:]:
        lines.append((styles.get(e["event"], "normal"), "    {}  {:7} {} {}".format(
            e["ts"][5:], e["event"], e.get("task", ""), e.get("title", ""))))
    return lines


def build_lines(state, native, sel, marks, view="board"):
    proj = tq.project_dir()
    mode = "被动" if tq.passive(state) else "主动·auto{}".format(
        tq.AUTO_LABEL[state["config"].get("auto", "off")])
    lines = [("title", " todo-queue   {}".format(os.path.basename(proj) or proj))]
    lines.append(("dim", " {}   {}   {}".format(
        proj.replace(os.path.expanduser("~"), "~"), mode, tq.progress_bar(state))))
    lines.append(("rule", ""))
    if view == "history":
        lines += build_history(state)
    else:
        lines += build_board(state, native, sel, marks)
    lines.append(("rule", ""))
    si = session_info()
    if si.get("session_id"):
        lines.append(("muted", " 会话 {}   {}".format(si["session_id"][:8], si.get("ts", ""))))
    lines.append(("muted", " j/k 移动  ␣ 多选  n 开始  p 暂停  d 完成  x 取消  m 迁移  h 历史  q 退出"))
    return lines


# ---------- 快照模式 (ANSI) ----------

def ansi(style):
    if style == "rule":
        style = "muted"
    seq, bold = PALETTE.get(style, PALETTE["normal"])[1], PALETTE.get(style, PALETTE["normal"])[2]
    return ("\033[1m" if bold else "") + seq


def print_once(view="board"):
    state = tq.load_state()
    sel = 0 if selectable_tasks(state) else -1
    for style, text in build_lines(state, native_tasks(), sel, set(), view):
        if style == "rule":
            text = " " + "─" * 52
        print("{}{}{}".format(ansi(style), text, RESET))


# ---------- 交互 TUI ----------

def pbcopy(text):
    try:
        subprocess.run(["pbcopy"], input=text.encode(), timeout=3)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _fallback8(c256):
    """终端只有 8/16 色时, 把 256 色号映射到最接近的基础色。"""
    return {75: 6, 109: 6, 73: 6, 179: 3, 108: 2, 167: 1, 245: 7, 240: 7, 140: 5}.get(c256, 7)


def run_tui():
    import curses
    import locale
    locale.setlocale(locale.LC_ALL, "")

    def _main(scr):
        curses.curs_set(0)
        scr.timeout(500)  # 500ms 轮询, 文件变化自动刷新
        curses.start_color()
        curses.use_default_colors()   # 背景 -1 = 透明, 直接继承终端 light/dark 主题
        amap = {}
        for i, (name, (c256, _seq, bold)) in enumerate(PALETTE.items(), start=1):
            if c256 is None or i >= curses.COLORS:
                amap[name] = curses.A_BOLD if bold else curses.A_NORMAL
                continue
            try:
                curses.init_pair(i, c256 if curses.COLORS >= 256 else _fallback8(c256), -1)
                amap[name] = curses.color_pair(i) | (curses.A_BOLD if bold else 0)
            except curses.error:
                amap[name] = curses.A_BOLD if bold else curses.A_NORMAL
        amap["rule"] = amap.get("muted", curses.A_DIM)
        sel = 0
        marks = set()
        view = "board"
        msg = ""
        while True:
            state = tq.load_state()
            sl = selectable_tasks(state)
            sel = min(max(sel, 0), max(len(sl) - 1, 0))
            marks &= {t["id"] for t in sl}
            lines = build_lines(state, native_tasks(), sel if sl else -1, marks, view)
            h, w = scr.getmaxyx()
            scr.erase()
            body = lines[:h - 1] if msg else lines[:h]
            for i, (style, text) in enumerate(body):
                if style == "rule":
                    text = " " + "─" * min(52, max(w - 2, 1))
                try:
                    scr.addstr(i, 0, clip(text, w), amap.get(style, 0))
                except curses.error:
                    pass
            if msg:
                try:
                    scr.addstr(min(len(body), h - 1), 0, clip("✳ " + msg, w),
                               amap["ok"] | curses.A_BOLD)
                except curses.error:
                    pass
            scr.refresh()

            ch = scr.getch()
            if ch == -1:
                continue
            msg = ""
            cur = sl[sel] if sl else None
            if ch in (ord("q"), 27):
                return
            elif ch in (ord("j"), curses.KEY_DOWN):
                sel += 1
            elif ch in (ord("k"), curses.KEY_UP):
                sel -= 1
            elif ch == ord(" ") and cur:
                marks.symmetric_difference_update({cur["id"]})
            elif ch == ord("h"):
                view = "history" if view == "board" else "board"
            elif ch in (ord("n"), 10, 13) and cur:
                if cur["status"] in ("queued", "paused", "active"):
                    tq.activate(state, cur)
                    tq.save_state(state)
            elif ch == ord("p") and cur:
                if cur["status"] == "paused":
                    tq.resume_task(state, cur)
                    msg = "已恢复 {}".format(cur["id"])
                else:
                    tq.pause_task(state, cur, note="UI 面板暂停")
                    msg = "已暂停 {}".format(cur["id"])
                tq.save_state(state)
            elif ch == ord("d") and cur:
                tq.close_task(state, cur, "done", note="UI 面板标记完成")
                if state["config"]["auto"]:
                    q2 = tq.queued(state)
                    if q2:
                        tq.activate(state, q2[0])
                tq.save_state(state)
                msg = "已完成 {}".format(cur["id"])
            elif ch == ord("x") and cur:
                tq.close_task(state, cur, "dropped", note="UI 面板取消")
                tq.save_state(state)
                msg = "已取消 {}".format(cur["id"])
            elif ch == ord("m"):
                targets = [t for t in sl if t["id"] in marks] or ([cur] if cur else [])
                if targets:
                    try:
                        name, _dest, launch = tq.do_fork(state, targets)
                        tq.save_state(state)
                        marks.clear()
                        copied = pbcopy(launch)
                        msg = "已迁出 {} 个任务 → {}{}".format(
                            len(targets), name,
                            " · 启动命令已复制到剪贴板" if copied else " · " + launch)
                    except RuntimeError as e:
                        msg = "迁移失败: {}".format(e)
            elif ch in (ord("+"), ord("=")) and cur:
                cur["priority"] = max(1, cur.get("priority", 3) - 1)
                tq.save_state(state)
            elif ch == ord("-") and cur:
                cur["priority"] = min(5, cur.get("priority", 3) + 1)
                tq.save_state(state)
            elif ch == ord("a"):
                state["config"]["auto"] = not state["config"]["auto"]
                tq.save_state(state)

    curses.wrapper(_main)


def check_active():
    """队列是否存在且有未关闭任务。供 claude wrapper 决定是否自动开面板。"""
    try:
        state = tq.load_state()
    except Exception:
        sys.exit(1)
    open_n = sum(1 for t in state["tasks"] if t["status"] in tq.OPEN_STATUSES)
    sys.exit(0 if open_n > 0 else 1)


def main():
    parser = argparse.ArgumentParser(description="todo-queue 实时任务面板")
    parser.add_argument("--project", help="项目路径 (默认 CLAUDE_PROJECT_DIR 或 cwd)")
    parser.add_argument("--once", action="store_true", help="打印一次快照后退出")
    parser.add_argument("--history", action="store_true", help="快照显示历史视图")
    parser.add_argument("--check-active", action="store_true",
                        help="静默模式: 队列有未关闭任务 exit 0, 否则 exit 1")
    args = parser.parse_args()
    if args.project:
        os.environ["CLAUDE_PROJECT_DIR"] = os.path.abspath(args.project)
    if args.check_active:
        check_active()
        return 0
    if args.once or not sys.stdout.isatty():
        print_once("history" if args.history else "board")
        return 0
    run_tui()
    return 0


if __name__ == "__main__":
    sys.exit(main())
