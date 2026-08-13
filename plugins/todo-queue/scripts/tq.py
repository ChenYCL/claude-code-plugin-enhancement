#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""todo-queue — Claude Code 持久化任务队列 CLI + hooks 后端。

存储位置: $TQ_QUEUE_FILE 或 <项目>/.claude/todo-queue.json
仅依赖 Python 标准库。

子命令:
  add <标题> [-p N] [-d 详情] [-a 验收标准] [--source S]   入队 (同名去重)
  list [--all]                                              查看队列
  next                                                      激活下一个任务为当前目标
  done [id] [备注...]                                       标记完成 (默认当前目标)
  pause [id] [备注...]                                      暂停任务 (默认当前目标)
  resume <id>                                               恢复暂停的任务
  drop/cancel <id> [备注...]                                取消任务
  focus <id>                                                切换当前目标任务
  bind <id> [--agent A] [--worktree W] [--workflow WF]      绑定 agent/worktree/workflow
  fork <id...> [--name N] [--worktree] [--launch]           多选迁移到新 session (迁出即移除)
  history [--current|--session SID] [--limit N]             会话历史记录 + 完成度
  auto [on|off|smart]                                       自动推进模式 (smart=智能判断)
  status                                                    统计概览 (含完成度)
  path                                                      打印队列文件路径
  statusline                                                Claude Code 状态栏输出 (读 stdin)
  hook <session-start|user-prompt|post-tool|stop>           供 hooks 调用, 读 stdin JSON
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

DEFAULT_STATE = {
    "version": 2,
    "config": {
        "auto": "off", "max_auto": 10, "smart_max_auto": 3, "harvest": True,
        "intervene": False,
        "gc": {"done_keep": 30, "closed_days": 14, "fork_days": 30, "archive_kb": 200},
    },
    "focus": None,
    "seq": 0,
    "auto_continues": 0,
    "tasks": [],
    "log": [],
    "forks": [],
    "last_gc": "",
}

OPEN_STATUSES = ("queued", "active", "paused")
STATUS_ICON = {"queued": "[ ]", "active": "[>]", "paused": "[=]",
               "done": "[x]", "dropped": "[-]", "migrated": "[^]"}
LOG_EVENT_OF_STATUS = {"done": "done", "dropped": "cancel", "migrated": "migrate"}
MAX_LOG = 500


# ---------- 存储 ----------

def project_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def queue_path():
    override = os.environ.get("TQ_QUEUE_FILE")
    if override:
        return os.path.abspath(override)
    return os.path.join(project_dir(), ".claude", "todo-queue.json")


def load_state():
    try:
        with open(queue_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        raw = {}
    state = json.loads(json.dumps(DEFAULT_STATE))
    for k, v in raw.items():
        if k == "config":
            gc_defaults = dict(state["config"]["gc"])
            state["config"].update(v if isinstance(v, dict) else {})
            gc_defaults.update(state["config"].get("gc") or {})
            state["config"]["gc"] = gc_defaults
        else:
            state[k] = v
    a = state["config"].get("auto")
    if isinstance(a, bool):            # v0.4 及更早为 bool, 迁移为三态
        state["config"]["auto"] = "on" if a else "off"
    elif a not in ("off", "on", "smart"):
        state["config"]["auto"] = "off"
    return state


def save_state(state, path=None):
    path = path or queue_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".todo-queue-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------- 工具函数 ----------

def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def norm(title):
    return re.sub(r"\s+", " ", title.strip().lower())


def self_cmd():
    return 'python3 "{}"'.format(os.path.abspath(__file__))


def current_session_id():
    try:
        with open(os.path.join(project_dir(), ".claude", "todo-queue-session.json"),
                  encoding="utf-8") as f:
            return json.load(f).get("session_id") or ""
    except (OSError, json.JSONDecodeError):
        return ""


def log_event(state, event, task=None, detail=""):
    state["log"].append({
        "ts": now(),
        "session": (current_session_id() or "")[:8],
        "event": event,
        "task": task["id"] if task else "",
        "title": task["title"] if task else "",
        "detail": detail,
    })
    del state["log"][:-MAX_LOG]


def find_by_title(state, title):
    nt = norm(title)
    for t in state["tasks"]:
        if t["status"] in OPEN_STATUSES and norm(t["title"]) == nt:
            return t
    return None


def find_by_id(state, tid):
    if not tid:
        return None
    tid = tid if str(tid).startswith("tq-") else "tq-{}".format(tid)
    for t in state["tasks"]:
        if t["id"] == tid:
            return t
    return None


def focus_task(state):
    t = find_by_id(state, state.get("focus"))
    if t and t["status"] == "active":
        return t
    return None


def queued(state):
    return sorted(
        (t for t in state["tasks"] if t["status"] == "queued"),
        key=lambda t: (t.get("priority", 3), int(t["id"].split("-")[1])),
    )


def paused_tasks(state):
    return [t for t in state["tasks"] if t["status"] == "paused"]


# ---------- auto 模式 ----------

AUTO_LABEL = {"off": "关", "on": "开", "smart": "智能"}


def passive(state):
    """被动模式 (默认): 插件只显示状态, 绝不干涉对话流程。

    干涉 = 拦截 Claude 停止、向每轮注入行为约束、自动改写队列。
    这些只在用户显式 `mode active` 后才启用。
    """
    return not state["config"].get("intervene", False)


def auto_mode(state):
    if passive(state):
        return "off"
    return state["config"].get("auto", "off")


def last_closed_task(state):
    """最近一个被关闭的任务 (done/dropped/migrated), 按 closed 时间。"""
    closed = [t for t in state["tasks"] if t.get("closed")]
    return max(closed, key=lambda t: (t["closed"], t["id"])) if closed else None


def smart_decision(state, nxt):
    """smart 模式下是否自动推进到 nxt。返回 (是否推进, 原因)。

    停下的判据都指向同一件事: 这一步需要用户参与, 不该由队列自己往前冲。
    """
    cfg = state["config"]
    cap = cfg.get("smart_max_auto", 3)
    if state["auto_continues"] >= cap:
        return False, "已连续自动推进 {} 个任务, 先停下来向用户汇报进展".format(cap)

    prev = last_closed_task(state)
    if prev and prev.get("status") in ("dropped", "migrated"):
        return False, "上一个任务是被取消/迁移而非完成, 节奏已被打断, 交回用户决定"

    if not (nxt.get("acceptance") or "").strip():
        return False, "下一个任务「{}」没有验收标准, 完成的定义不清晰, 需要用户先确认范围".format(nxt["title"])

    if prev and prev.get("status") == "done":
        gap = nxt.get("priority", 3) - prev.get("priority", 3)
        if gap >= 2:
            return False, "下一个任务优先级 P{} 明显低于刚完成的 P{}, 这批紧急任务已收尾".format(
                nxt.get("priority", 3), prev.get("priority", 3))

    return True, "下一个任务同批次且验收标准明确"


def progress(state):
    """返回 (done数, 总数, 百分比)。总数 = 未关闭 + 已完成 (不含取消/迁移)。"""
    done_n = sum(1 for t in state["tasks"] if t["status"] == "done")
    open_n = sum(1 for t in state["tasks"] if t["status"] in OPEN_STATUSES)
    total = done_n + open_n
    return done_n, total, int(done_n * 100 / total) if total else 0


def progress_bar(state, width=10):
    done_n, total, pct = progress(state)
    filled = int(width * pct / 100)
    return "{}{} {}/{} ({}%)".format("▓" * filled, "░" * (width - filled), done_n, total, pct)


# ---------- GC / 空间管理 ----------

def archive_path(qp=None):
    return os.path.splitext(qp or queue_path())[0] + "-archive.jsonl"


def forks_dir():
    return os.path.join(os.path.dirname(queue_path()), "todo-queue-forks")


def parse_ts(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return None


def fork_open_count(dest):
    """fork 队列文件中未关闭任务数; 读不了返回 None。"""
    try:
        with open(dest, encoding="utf-8") as f:
            fs = json.load(f)
        return sum(1 for t in fs.get("tasks", []) if t.get("status") in OPEN_STATUSES)
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def append_archive(tasks, dry_run=False):
    if not tasks or dry_run:
        return
    with open(archive_path(), "a", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")


def trim_archive(cap_kb, dry_run=False):
    """归档文件超过 cap_kb 时, 从最旧一端裁剪到 80% 容量。返回是否裁剪。"""
    p = archive_path()
    try:
        if not os.path.exists(p) or os.path.getsize(p) <= cap_kb * 1024:
            return False
        if dry_run:
            return True
        with open(p, encoding="utf-8") as f:
            lines = f.readlines()
        keep, size = [], 0
        for line in reversed(lines):
            size += len(line.encode("utf-8"))
            if size > cap_kb * 1024 * 0.8:
                break
            keep.append(line)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), prefix=".tq-arc-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(reversed(keep))
        os.replace(tmp, p)
        return True
    except OSError:
        return False


def run_gc(state, dry_run=False):
    """按保留策略归档旧任务、回收 fork 文件。返回报告 dict。"""
    g = state["config"]["gc"]
    now_dt = datetime.datetime.now()
    report = {"archived": 0, "forks_deleted": [], "stale_worktrees": [], "trimmed": False}

    # 1) 旧的已关闭任务 → 归档文件 (jsonl)
    cutoff = now_dt - datetime.timedelta(days=g["closed_days"])
    to_archive = []
    for t in state["tasks"]:
        if t["status"] in OPEN_STATUSES:
            continue
        ts = parse_ts(t.get("closed") or t.get("created"))
        if ts and ts < cutoff:
            to_archive.append(t)
    done = [t for t in state["tasks"] if t["status"] == "done" and t not in to_archive]
    if len(done) > g["done_keep"]:
        to_archive += done[:len(done) - g["done_keep"]]
    append_archive(to_archive, dry_run)
    if to_archive and not dry_run:
        ids = {t["id"] for t in to_archive}
        state["tasks"] = [t for t in state["tasks"] if t["id"] not in ids]
    report["archived"] = len(to_archive)
    report["trimmed"] = trim_archive(g["archive_kb"], dry_run)

    # 2) fork 队列回收: 已清空或长期未动的文件 fork 直接删 (任务先并入归档);
    #    worktree fork 含代码, 永不自动删, 只给出清理建议。
    registry = state.setdefault("forks", [])
    known = {f.get("dest") for f in registry}
    candidates = [dict(f) for f in registry]
    try:
        for fn in os.listdir(forks_dir()):
            full = os.path.join(forks_dir(), fn)
            if fn.endswith(".json") and full not in known:
                candidates.append({"name": fn[:-5], "dest": full, "worktree": False, "path": ""})
    except OSError:
        pass
    for fork in candidates:
        dest = fork.get("dest") or ""
        if not os.path.exists(dest):
            if not dry_run:
                registry[:] = [f for f in registry if f.get("dest") != dest]
            continue
        open_n = fork_open_count(dest)
        age_days = (now_dt - datetime.datetime.fromtimestamp(os.path.getmtime(dest))).days
        if fork.get("worktree"):
            if open_n == 0:
                report["stale_worktrees"].append(fork)
            continue
        if open_n == 0 or (open_n is None and age_days > g["fork_days"]) or age_days > g["fork_days"]:
            if not dry_run:
                try:
                    with open(dest, encoding="utf-8") as f:
                        append_archive(json.load(f).get("tasks", []))
                except (OSError, json.JSONDecodeError):
                    pass
                for p in (dest, archive_path(dest)):
                    if os.path.exists(p):
                        os.unlink(p)
                registry[:] = [f for f in registry if f.get("dest") != dest]
            report["forks_deleted"].append(fork.get("name") or dest)

    # 3) 日志上限兜底
    del state["log"][:-MAX_LOG]
    if not dry_run:
        state["last_gc"] = now()
    return report


def maybe_auto_gc(state):
    """每 24h 静默 GC 一次; 队列文件不存在时不做任何事 (避免凭空建文件)。"""
    if not os.path.exists(queue_path()):
        return
    last = parse_ts(state.get("last_gc"))
    if last and (datetime.datetime.now() - last).total_seconds() < 86400:
        return
    try:
        run_gc(state)
        save_state(state)
    except Exception:
        pass


def disk_usage():
    """返回 [(标签, 字节)] 与合计。"""
    parts = []
    qp = queue_path()
    for label, p in (("队列", qp), ("归档", archive_path())):
        if os.path.exists(p):
            parts.append((label, os.path.getsize(p)))
    total_forks = 0
    try:
        for fn in os.listdir(forks_dir()):
            total_forks += os.path.getsize(os.path.join(forks_dir(), fn))
    except OSError:
        pass
    if total_forks:
        parts.append(("forks", total_forks))
    return parts, sum(s for _, s in parts)


def fmt_bytes(n):
    return "{:.1f}KB".format(n / 1024) if n >= 1024 else "{}B".format(n)


def cmd_gc(args):
    state = load_state()
    report = run_gc(state, dry_run=args.dry_run)
    if not args.dry_run:
        save_state(state)
    print("todo-queue GC{}:".format(" (dry-run, 未实际改动)" if args.dry_run else ""))
    print("  归档旧任务: {} 条 → {}".format(report["archived"], os.path.basename(archive_path())))
    print("  回收 fork 队列: {}".format(", ".join(report["forks_deleted"]) or "无"))
    print("  归档裁剪(>{}KB): {}".format(state["config"]["gc"]["archive_kb"],
                                         "已裁剪" if report["trimmed"] else "无需"))
    for f in report["stale_worktrees"]:
        print("  ⚠ worktree fork「{}」任务已清空, 含代码不自动删, 确认后手动执行:".format(f.get("name")))
        print('     git worktree remove "{}" && git branch -D "tq/{}"'.format(
            f.get("path"), f.get("name")))
    parts, total = disk_usage()
    print("  当前占用: {} = {}".format(
        " + ".join("{} {}".format(l, fmt_bytes(s)) for l, s in parts) or "0",
        fmt_bytes(total)))
    return 0


def detect_worktree():
    """若当前项目目录是 git worktree (非主仓), 返回其绝对路径。"""
    try:
        gd = subprocess.run(["git", "-C", project_dir(), "rev-parse", "--git-dir"],
                            capture_output=True, text=True, timeout=3)
        gc = subprocess.run(["git", "-C", project_dir(), "rev-parse", "--git-common-dir"],
                            capture_output=True, text=True, timeout=3)
        if gd.returncode == 0 and gc.returncode == 0:
            d, c = gd.stdout.strip(), gc.stdout.strip()
            if d and c and os.path.abspath(d) != os.path.abspath(c):
                return project_dir()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def stamp_bindings(state, task):
    """激活任务时自动绑定当前 session / worktree。"""
    b = task.setdefault("binding", {})
    sid = current_session_id()
    if sid:
        b["session"] = sid[:8]
    wt = detect_worktree()
    if wt:
        b["worktree"] = wt


def fmt_binding(task):
    b = task.get("binding") or {}
    tags = []
    if b.get("agent"):
        tags.append("⚙" + b["agent"].split(":")[0])
    if b.get("worktree"):
        gone = "" if os.path.isdir(b["worktree"]) else "✗"
        tags.append("⎇" + os.path.basename(b["worktree"]) + gone)
    if b.get("workflow"):
        tags.append("wf:" + b["workflow"].replace("wf_", "")[:8])
    if b.get("session"):
        tags.append("s:" + b["session"])
    return " ".join(tags)


def add_task(state, title, priority=3, detail="", acceptance="", source="user"):
    """返回 (task, created)。同名未关闭任务视为重复, 不再入队。"""
    existing = find_by_title(state, title)
    if existing:
        return existing, False
    state["seq"] += 1
    task = {
        "id": "tq-{}".format(state["seq"]),
        "title": re.sub(r"\s+", " ", title.strip()),
        "detail": detail,
        "acceptance": acceptance,
        "priority": priority,
        "source": source,
        "status": "queued",
        "created": now(),
        "closed": None,
        "note": "",
        "binding": {},
    }
    state["tasks"].append(task)
    log_event(state, "add", task, source)
    return task, True


def activate(state, task):
    cur = focus_task(state)
    if cur and cur["id"] != task["id"]:
        cur["status"] = "queued"
    task["status"] = "active"
    state["focus"] = task["id"]
    stamp_bindings(state, task)
    log_event(state, "start", task)


def close_task(state, task, status, note=""):
    task["status"] = status
    task["closed"] = now()
    if note:
        task["note"] = note
    if state.get("focus") == task["id"]:
        state["focus"] = None
    log_event(state, LOG_EVENT_OF_STATUS.get(status, status), task, note)


def pause_task(state, task, note=""):
    if state.get("focus") == task["id"]:
        state["focus"] = None
    task["status"] = "paused"
    log_event(state, "pause", task, note)


def resume_task(state, task):
    """恢复暂停任务: 无当前目标则直接接管, 否则回到待办。返回是否成为目标。"""
    if focus_task(state) is None:
        activate(state, task)
        log_event(state, "resume", task, "恢复为当前目标")
        return True
    task["status"] = "queued"
    log_event(state, "resume", task, "恢复到待办")
    return False


def fmt_task(t):
    line = "{} {} P{} ({}) {}".format(
        STATUS_ICON.get(t["status"], "[?]"), t["id"],
        t.get("priority", 3), t.get("source", "user"), t["title"])
    tags = fmt_binding(t)
    return line + ("  " + tags if tags else "")


def activation_block(state, task, header="▶ 开始任务"):
    lines = ["{} {}: {}".format(header, task["id"], task["title"])]
    if task.get("detail"):
        lines.append("  详情: {}".format(task["detail"]))
    if task.get("acceptance"):
        lines.append("  验收标准: {}".format(task["acceptance"]))
    lines.append("  优先级: P{}  来源: {}".format(task.get("priority", 3), task.get("source", "user")))
    tags = fmt_binding(task)
    if tags:
        lines.append("  绑定: {}".format(tags))
    lines.append("  剩余待办: {} 个".format(len(queued(state))))
    lines.append('  约束: 专注完成此任务; 期间出现的新需求先入队: {} add "<标题>"'.format(self_cmd()))
    lines.append("  完成并验证后运行: {} done".format(self_cmd()))
    return "\n".join(lines)


# ---------- CLI 子命令 ----------

def cmd_add(args):
    title = " ".join(args.title).strip()
    if not title:
        print("错误: 缺少任务标题", file=sys.stderr)
        return 1
    state = load_state()
    task, created = add_task(state, title, priority=args.priority,
                             detail=args.detail, acceptance=args.acceptance,
                             source=args.source)
    if created:
        save_state(state)
        print("已入队: {} {} (P{})".format(task["id"], task["title"], task["priority"]))
    else:
        print("已存在同名任务 {} (状态: {}), 跳过".format(task["id"], task["status"]))
    return 0


def cmd_list(args):
    state = load_state()
    tasks = state["tasks"]
    if not tasks:
        print("队列为空。用 add 添加任务, 或用 /todo-queue:collect 归集散落的 TODO。")
        return 0
    print("todo-queue @ {}".format(queue_path()))
    print("自动推进: {}  完成度: {}".format(
        AUTO_LABEL[auto_mode(state)], progress_bar(state)))
    ft = focus_task(state)
    print("\n进行中:")
    print("  " + fmt_task(ft) if ft else "  (无)")
    if ft and ft.get("acceptance"):
        print("      验收标准: {}".format(ft["acceptance"]))
    paused = paused_tasks(state)
    if paused:
        print("\n已暂停 ({}):".format(len(paused)))
        for t in paused:
            print("  " + fmt_task(t))
    q = queued(state)
    print("\n待办 ({}):".format(len(q)))
    for t in q:
        print("  " + fmt_task(t))
        if t.get("detail"):
            print("      {}".format(t["detail"]))
    done = [t for t in tasks if t["status"] == "done"]
    shown = done if args.all else done[-5:]
    if shown:
        print("\n已完成 ({}{}):".format(len(done), "" if args.all else ", 最近 5 条"))
        for t in shown:
            print("  " + fmt_task(t))
    if args.all:
        for status, label in (("dropped", "已取消"), ("migrated", "已迁移")):
            closed = [t for t in tasks if t["status"] == status]
            if closed:
                print("\n{} ({}):".format(label, len(closed)))
                for t in closed:
                    print("  " + fmt_task(t) + ("  → " + t.get("note", "") if t.get("note") else ""))
    return 0


def cmd_next(args):
    state = load_state()
    ft = focus_task(state)
    if ft:
        print(activation_block(state, ft, header="▶ 当前已有进行中任务"))
        return 0
    q = queued(state)
    if not q:
        paused = paused_tasks(state)
        if paused:
            print("待办队列为空, 但有 {} 个暂停任务, 可用 resume <id> 恢复:".format(len(paused)))
            for t in paused:
                print("  " + fmt_task(t))
        else:
            print("队列为空, 没有可执行的任务。")
        return 0
    task = q[0]
    activate(state, task)
    save_state(state)
    print(activation_block(state, task))
    return 0


def cmd_done(args):
    state = load_state()
    words = list(args.words)
    task = None
    if words:
        task = find_by_id(state, words[0])
        if task:
            words = words[1:]
    if task is None:
        task = focus_task(state)
    if task is None:
        active = [t for t in state["tasks"] if t["status"] == "active"]
        task = active[0] if len(active) == 1 else None
    if task is None:
        print("错误: 没有进行中的任务, 请指定任务 ID (如: done tq-3)", file=sys.stderr)
        return 1
    if task["status"] == "done":
        print("{} 已是完成状态".format(task["id"]))
        return 0
    close_task(state, task, "done", note=" ".join(words))
    lines = ["✔ 已完成: {} {}".format(task["id"], task["title"])]
    q = queued(state)
    mode = auto_mode(state)
    advance, why = (mode != "off" and bool(q)), ""
    if advance and mode == "smart":
        advance, why = smart_decision(state, q[0])
    if advance:
        nxt = q[0]
        activate(state, nxt)
        state["auto_continues"] += 1   # 计入连续推进, smart_max_auto 才能生效
        lines.append("")
        lines.append(activation_block(state, nxt, header="▶ {}推进, 开始下一个任务".format(
            "智能" if mode == "smart" else "自动")))
    else:
        if mode == "smart" and q and why:
            lines.append("智能推进已停下: {}".format(why))
            lines.append("确认后可用 next 继续。")
            state["auto_continues"] = 0
        lines.append("完成度: {}{}".format(
            progress_bar(state), "  运行 next 继续" if q else "  队列已清空 🎉"))
    save_state(state)
    print("\n".join(lines))
    return 0


def cmd_pause(args):
    state = load_state()
    words = list(args.words)
    task = None
    if words:
        task = find_by_id(state, words[0])
        if task:
            words = words[1:]
    if task is None:
        task = focus_task(state)
    if task is None:
        print("错误: 没有进行中的任务且未指定 ID", file=sys.stderr)
        return 1
    if task["status"] == "paused":
        print("{} 已是暂停状态".format(task["id"]))
        return 0
    if task["status"] not in OPEN_STATUSES:
        print("错误: {} 已关闭 ({}), 不能暂停".format(task["id"], task["status"]), file=sys.stderr)
        return 1
    pause_task(state, task, note=" ".join(words))
    save_state(state)
    print("⏸ 已暂停: {} {} (resume {} 可恢复)".format(task["id"], task["title"], task["id"]))
    return 0


def cmd_resume(args):
    state = load_state()
    task = find_by_id(state, args.id)
    if not task:
        print("错误: 找不到任务 {}".format(args.id), file=sys.stderr)
        return 1
    if task["status"] != "paused":
        print("错误: {} 不是暂停状态 (当前: {})".format(task["id"], task["status"]), file=sys.stderr)
        return 1
    became_focus = resume_task(state, task)
    save_state(state)
    if became_focus:
        print(activation_block(state, task, header="▶ 已恢复为当前目标"))
    else:
        print("已恢复到待办: {} {} (当前目标未变)".format(task["id"], task["title"]))
    return 0


def cmd_focus(args):
    state = load_state()
    task = find_by_id(state, args.id)
    if not task:
        print("错误: 找不到任务 {}".format(args.id), file=sys.stderr)
        return 1
    if task["status"] not in OPEN_STATUSES:
        print("错误: {} 已关闭 ({}), 不能设为目标".format(task["id"], task["status"]), file=sys.stderr)
        return 1
    activate(state, task)
    save_state(state)
    print(activation_block(state, task, header="▶ 已切换目标任务"))
    return 0


def cmd_drop(args):
    state = load_state()
    task = find_by_id(state, args.id)
    if not task:
        print("错误: 找不到任务 {}".format(args.id), file=sys.stderr)
        return 1
    close_task(state, task, "dropped", note=" ".join(args.note))
    save_state(state)
    print("已取消: {} {}".format(task["id"], task["title"]))
    return 0


def cmd_bind(args):
    state = load_state()
    task = find_by_id(state, args.id)
    if not task:
        print("错误: 找不到任务 {}".format(args.id), file=sys.stderr)
        return 1
    if args.clear:
        task["binding"] = {}
    b = task.setdefault("binding", {})
    if args.agent:
        b["agent"] = args.agent
    if args.worktree:
        b["worktree"] = os.path.abspath(args.worktree)
    if args.workflow:
        b["workflow"] = args.workflow
    if args.session:
        b["session"] = args.session[:8]
    log_event(state, "bind", task, fmt_binding(task))
    save_state(state)
    print("绑定更新: {} {}  [{}]".format(task["id"], task["title"], fmt_binding(task) or "无"))
    return 0


# ---------- fork / 迁移 ----------

def do_fork(state, tasks, name=None, worktree=False):
    """把 tasks 迁移到新 session 的独立队列。返回 (fork_name, 队列路径, 启动命令)。
    原任务标记 migrated (从当前队列移除); 调用方负责 save_state(state)。"""
    fork_name = name or "fork-" + datetime.datetime.now().strftime("%m%d-%H%M%S")
    root = project_dir()
    new_state = json.loads(json.dumps(DEFAULT_STATE))
    new_state["config"].update(state["config"])
    new_state["config"]["auto"] = "off"
    for t in tasks:
        nt = json.loads(json.dumps(t))
        nt["status"] = "queued"
        nt["binding"] = {}
        nt["note"] = "fork 自 {}".format(os.path.basename(root))
        new_state["tasks"].append(nt)
        new_state["seq"] = max(new_state["seq"], int(t["id"].split("-")[1]))

    hello = "todo 队列已就绪 ({} 个任务): 运行 /todo-queue:list 查看, /todo-queue:next 开始".format(len(tasks))
    if worktree:
        target = os.path.join(os.path.dirname(root), os.path.basename(root) + "-" + fork_name)
        branch = "tq/" + fork_name
        r = subprocess.run(["git", "-C", root, "worktree", "add", "-b", branch, target],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError("git worktree 创建失败: " + (r.stderr.strip() or r.stdout.strip()))
        dest = os.path.join(target, ".claude", "todo-queue.json")
        launch = 'cd "{}" && claude "{}"'.format(target, hello)
    else:
        target = None
        dest = os.path.join(root, ".claude", "todo-queue-forks", fork_name + ".json")
        launch = 'cd "{}" && TQ_QUEUE_FILE="{}" claude "{}"'.format(root, dest, hello)
    save_state(new_state, path=dest)
    state.setdefault("forks", []).append({
        "name": fork_name, "dest": dest, "path": target or "",
        "worktree": bool(worktree), "created": now(),
    })

    for t in tasks:
        note = "迁移至 {}".format(target or fork_name)
        close_task(state, t, "migrated", note=note)
    return fork_name, dest, launch


def launch_in_terminal(cmd):
    """新终端里启动命令。返回启动方式描述, 失败返回 None。"""
    try:
        if os.environ.get("TMUX"):
            subprocess.run(["tmux", "new-window", cmd], timeout=10)
            return "tmux 新窗口"
        if sys.platform == "darwin":
            script = 'tell application "Terminal"\ndo script "{}"\nactivate\nend tell'.format(
                cmd.replace("\\", "\\\\").replace('"', '\\"'))
            subprocess.run(["osascript", "-e", script], timeout=10)
            return "Terminal 新窗口"
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def cmd_fork(args):
    state = load_state()
    tasks = []
    for tid in args.ids:
        t = find_by_id(state, tid)
        if not t:
            print("错误: 找不到任务 {}".format(tid), file=sys.stderr)
            return 1
        if t["status"] not in OPEN_STATUSES:
            print("错误: {} 已关闭 ({}), 不能迁移".format(t["id"], t["status"]), file=sys.stderr)
            return 1
        tasks.append(t)
    try:
        fork_name, dest, launch = do_fork(state, tasks, name=args.name, worktree=args.worktree)
    except RuntimeError as e:
        print("错误: {}".format(e), file=sys.stderr)
        return 1
    save_state(state)
    print("已迁出 {} 个任务 → {} ({})".format(len(tasks), fork_name, dest))
    for t in tasks:
        print("  [^] {} {}".format(t["id"], t["title"]))
    print("新 session 启动命令:\n  {}".format(launch))
    if args.launch:
        how = launch_in_terminal(launch)
        print("已在{}启动新 session。".format(how) if how else "自动启动失败, 请手动运行上面的命令。")
    return 0


def cmd_history(args):
    state = load_state()
    log = state["log"]
    if not log:
        print("暂无历史记录。")
        return 0
    cur = (current_session_id() or "")[:8]
    filt = args.session[:8] if args.session else (cur if args.current else None)
    entries = [e for e in log if not filt or e.get("session") == filt]
    if not entries:
        print("会话 {} 无历史记录。".format(filt))
        return 0
    print("总完成度: {}".format(progress_bar(state)))
    # 按会话统计完成度
    sessions, per = [], {}
    for e in log if not filt else entries:
        s = e.get("session") or "-"
        if s not in per:
            per[s] = {"touched": set(), "done": set()}
            sessions.append(s)
        if e.get("task"):
            per[s]["touched"].add(e["task"])
            if e["event"] == "done":
                per[s]["done"].add(e["task"])
    print("会话统计:")
    for s in sessions:
        mark = " ← 当前" if s == cur and s != "-" else ""
        print("  {}: 完成 {} / 触达 {}{}".format(s, len(per[s]["done"]), len(per[s]["touched"]), mark))
    print("\n事件记录{}:".format(" (会话 {})".format(filt) if filt else ""))
    for e in entries[-args.limit:]:
        print("  {} [{}] {:7} {} {}{}".format(
            e["ts"], e.get("session") or "-", e["event"], e.get("task", ""),
            e.get("title", ""), "  ({})".format(e["detail"]) if e.get("detail") else ""))
    return 0


def cmd_mode(args):
    state = load_state()
    if args.mode == "passive":
        state["config"]["intervene"] = False
        save_state(state)
    elif args.mode == "active":
        state["config"]["intervene"] = True
        save_state(state)
    if passive(state):
        print("模式: 被动 (默认) — 插件只显示状态, 不影响对话流程")
        print("  · Stop hook 不拦截 (auto 设置暂不生效)")
        print("  · 每轮只注入一行只读状态, 不下达任何行为约束")
        print("  · 不自动归集会话 todo (需要时用 /todo-queue:collect 主动归集)")
        print("  · 队列的推进完全由你的命令驱动: next / done / pause / fork")
        print("切换: mode active (启用 auto 推进、目标约束、自动归集)")
    else:
        print("模式: 主动 — 插件会介入对话流程")
        print("  · auto={}: {}".format(
            AUTO_LABEL[state["config"].get("auto", "off")],
            "队列非空时拦截 Claude 停止" if state["config"].get("auto") != "off" else "不拦截"))
        print("  · 每轮注入目标约束 (新需求先入队、别跑偏)")
        print("  · 自动归集会话 todo: {}".format("开" if state["config"].get("harvest", True) else "关"))
        print("切换: mode passive (恢复为只显示)")
    return 0


def cmd_auto(args):
    state = load_state()
    if args.switch in ("on", "off", "smart"):
        state["config"]["auto"] = args.switch
        state["auto_continues"] = 0
        save_state(state)
    if passive(state) and state["config"].get("auto", "off") != "off":
        print("提示: 当前是被动模式, auto 设置已保存但不会生效 (插件不拦截对话)。")
        print("      要让它生效需显式运行: {} mode active".format(self_cmd()))
        print()
    m = auto_mode(state)
    if m == "on":
        print("自动推进模式: 开 — 队列非空时持续执行到清空 (max_auto={} 兜底)".format(
            state["config"]["max_auto"]))
    elif m == "smart":
        print("自动推进模式: 智能 — 只在'同批次且定义清晰'时自动接下一个, 以下情况主动停下交回用户:")
        print("  · 已连续自动推进 {} 个任务 (smart_max_auto)".format(
            state["config"].get("smart_max_auto", 3)))
        print("  · 下一个任务没有验收标准 (完成的定义不清晰)")
        print("  · 下一个任务优先级比刚完成的低 2 级以上 (这批紧急任务已收尾)")
        print("  · 上一个任务是被取消/迁移而非正常完成 (节奏已被打断)")
    else:
        print("自动推进模式: 关")
    return 0


def cmd_status(args):
    state = load_state()
    counts = {}
    for t in state["tasks"]:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    ft = focus_task(state)
    print("todo-queue @ {}".format(queue_path()))
    print("完成度: {}".format(progress_bar(state)))
    print("进行中: {}".format("{} {}".format(ft["id"], ft["title"]) if ft else "无"))
    print("待办 {} | 暂停 {} | 已完成 {} | 已取消 {} | 已迁移 {}".format(
        counts.get("queued", 0), counts.get("paused", 0), counts.get("done", 0),
        counts.get("dropped", 0), counts.get("migrated", 0)))
    print("自动推进: {}".format(AUTO_LABEL[auto_mode(state)]))
    parts, total = disk_usage()
    print("占用: {} = {}  (每日自动 GC, 上次: {})".format(
        " + ".join("{} {}".format(l, fmt_bytes(s)) for l, s in parts) or "0",
        fmt_bytes(total), state.get("last_gc") or "未运行"))
    return 0


def cmd_path(args):
    print(queue_path())
    return 0


def cmd_setup_check(args):
    """检查各可选配置项状态, 供 /todo-queue:setup 引导使用。"""
    settings_path = os.path.expanduser("~/.claude/settings.json")
    sl_cmd = ""
    try:
        with open(settings_path, encoding="utf-8") as f:
            sl_cmd = ((json.load(f).get("statusLine") or {}).get("command")) or ""
    except (OSError, json.JSONDecodeError):
        pass
    if "tq.py" in sl_cmd and "statusline" in sl_cmd:
        sl_state = "已配置 (todo-queue)"
    elif "tq-statusline-wrapper" in sl_cmd:
        sl_state = "已配置 (合并 wrapper)"
    elif sl_cmd:
        sl_state = "已被其它命令占用, 需 wrapper 合并: {}".format(sl_cmd[:80])
    else:
        sl_state = "未配置"
    state = load_state()
    g = state["config"]["gc"]
    print("statusline: {}".format(sl_state))
    print("statusline 命令: {} statusline".format(self_cmd()))
    print("auto 自动推进: {} (on=拦截到队列清空; smart=按批次/验收标准判断是否继续)".format(
        AUTO_LABEL[auto_mode(state)]))
    print("归集 harvest: {} (默认开)".format("开" if state["config"].get("harvest", True) else "关"))
    print("自动 GC: 每日一次, done_keep={} closed_days={} fork_days={} archive_kb={}".format(
        g["done_keep"], g["closed_days"], g["fork_days"], g["archive_kb"]))
    print("队列文件: {} ({})".format(
        queue_path(), "已初始化" if os.path.exists(queue_path()) else "首个任务入队时创建"))
    print("tmux: {}".format("当前在 tmux 中, UI 面板可分屏常驻" if os.environ.get("TMUX")
                            else "不在 tmux 中, UI 面板走新终端窗口"))
    if args.mark:
        try:
            os.makedirs(os.path.dirname(setup_flag_path()), exist_ok=True)
            with open(setup_flag_path(), "w", encoding="utf-8") as f:
                f.write(now())
            print("setup 提示标志: 已写入 (新会话不再提示)")
        except OSError:
            pass
    return 0


# ---------- hooks ----------

def read_hook_input():
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def record_session(data, event):
    """记录会话信息, 供 tq_ui.py 关联 Claude Code 原生任务 (~/.claude/tasks/session-*)。"""
    sid = data.get("session_id")
    if not sid:
        return
    try:
        path = os.path.join(project_dir(), ".claude", "todo-queue-session.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "session_id": sid,
                "transcript_path": data.get("transcript_path", ""),
                "last_event": event,
                "ts": now(),
            }, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def hook_output(event, context):
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": event, "additionalContext": context}
    }, ensure_ascii=False))


def prev_session_summary(state):
    """上一个 (非当前) 会话的完成情况摘要, 无则返回空串。"""
    cur = (current_session_id() or "")[:8]
    prev = None
    for e in reversed(state["log"]):
        s = e.get("session")
        if s and s != cur:
            prev = s
            break
    if not prev:
        return ""
    done = {e["task"] for e in state["log"] if e.get("session") == prev and e["event"] == "done"}
    touched = {e["task"] for e in state["log"] if e.get("session") == prev and e.get("task")}
    return "上个会话 {}: 完成 {} 个 / 触达 {} 个任务。".format(prev, len(done), len(touched))


def setup_flag_path():
    return os.path.expanduser("~/.claude/todo-queue-setup-prompted")


def hook_session_start(data):
    state = load_state()
    maybe_auto_gc(state)
    if state["auto_continues"]:
        state["auto_continues"] = 0
        save_state(state)
    first_time = not os.path.exists(setup_flag_path())
    open_tasks = [t for t in state["tasks"] if t["status"] in OPEN_STATUSES]
    if not open_tasks and not first_time:
        return 0
    lines = []
    if first_time:
        lines.append(
            "todo-queue 插件已启用: 自动归集/目标约束/动态绑定/每日 GC 均已默认开启, 无需配置。"
            "建议本次向用户提示一次: 运行 /todo-queue:setup 可完成 3 项可选配置"
            "(statusline 底部常驻显示、auto 自动推进、UI 面板), 不运行也不影响核心功能。")
        try:
            os.makedirs(os.path.dirname(setup_flag_path()), exist_ok=True)
            with open(setup_flag_path(), "w", encoding="utf-8") as f:
                f.write(now())
        except OSError:
            pass
    if open_tasks:
        ft = focus_task(state)
        q = queued(state)
        paused = paused_tasks(state)
        lines.append("本项目存在持久化 todo 队列 (todo-queue 插件, {}):".format(queue_path()))
        lines.append("完成度: {}".format(progress_bar(state)))
        prev = prev_session_summary(state)
        if prev:
            lines.append(prev)
        lines.append("进行中: {}".format("{}「{}」(上会话遗留, 可继续或 pause)".format(ft["id"], ft["title"]) if ft else "无"))
        if paused:
            lines.append("暂停中 {} 个 (resume <id> 可恢复): {}".format(
                len(paused), ", ".join("{}「{}」".format(t["id"], t["title"]) for t in paused[:3])))
        if q:
            lines.append("待办 {} 个, 靠前的:".format(len(q)))
            for t in q[:5]:
                lines.append("  {} P{} {}".format(t["id"], t.get("priority", 3), t["title"]))
        lines.append("命令: /todo-queue:list 查看, /todo-queue:next 开始, /todo-queue:history 历史; CLI: {}".format(self_cmd()))
    hook_output("SessionStart", "\n".join(lines))
    return 0


def hook_user_prompt(data):
    state = load_state()
    if state["auto_continues"]:
        state["auto_continues"] = 0
        save_state(state)
    ft = focus_task(state)
    q = queued(state)
    if passive(state):
        # 被动模式: 只报状态, 不下任何指令 —— 用户没要求就不该影响这一轮的做法
        if ft:
            hook_output("UserPromptSubmit",
                        "<todo-queue-status>队列当前目标: {}「{}」; 另有 {} 个待办。"
                        "仅供参考, 用户本轮的请求优先; 除非用户提到待办/队列, 否则不必理会本条。"
                        "</todo-queue-status>".format(ft["id"], ft["title"], len(q)))
        return 0
    if ft:
        lines = ["<todo-queue>"]
        lines.append("当前目标任务: {}「{}」(P{})".format(ft["id"], ft["title"], ft.get("priority", 3)))
        if ft.get("acceptance"):
            lines.append("验收标准: {}".format(ft["acceptance"]))
        tags = fmt_binding(ft)
        if tags:
            lines.append("绑定: {}".format(tags))
        if q:
            lines.append("队列中还有 {} 个待办。".format(len(q)))
        lines.append(
            "约束: 保持在当前目标任务范围内工作。用户消息中若包含与当前任务无关的新需求/新想法, "
            '先运行 {} add "<标题>" 将其入队并告知用户已记录, 完成当前任务后再处理; '
            "当前任务完成并验证后运行 {} done。".format(self_cmd(), self_cmd()))
        lines.append("</todo-queue>")
        hook_output("UserPromptSubmit", "\n".join(lines))
    elif q:
        hook_output("UserPromptSubmit",
                    "<todo-queue>队列中有 {} 个待办任务, 当前无进行中任务。"
                    "若用户的请求对应新任务可先入队; 用 /todo-queue:next 可开始下一个。</todo-queue>".format(len(q)))
    return 0


def hook_post_tool(data):
    state = load_state()
    if passive(state) or not state["config"].get("harvest", True):
        return 0   # 被动模式: 不自动改写队列, 归集交给 /todo-queue:collect
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    changed = False
    if tool == "TodoWrite":
        for todo in ti.get("todos", []):
            content = (todo.get("content") or "").strip()
            if not content:
                continue
            existing = find_by_title(state, content)
            if todo.get("status") == "completed":
                # 只自动关闭会话来源的任务, 用户手动入队的任务须显式 done
                if existing and existing["status"] in ("queued", "active") \
                        and existing.get("source") == "session":
                    close_task(state, existing, "done", note="会话 todo 完成, 自动归集")
                    changed = True
            else:
                if not existing:
                    add_task(state, content, source="session", detail="自动归集自会话 todo")
                    changed = True
    elif tool == "TaskCreate":
        subject = (ti.get("subject") or ti.get("content") or "").strip()
        if subject and not find_by_title(state, subject):
            add_task(state, subject, source="session",
                     detail=(ti.get("description") or "自动归集自会话任务")[:200])
            changed = True
    elif tool == "TaskUpdate":
        if ti.get("status") == "completed":
            resp = data.get("tool_response") or {}
            if not isinstance(resp, dict):
                resp = {}
            subject = ((resp.get("task") or {}).get("subject")
                       or resp.get("subject") or "").strip()
            existing = find_by_title(state, subject) if subject else None
            if existing and existing["status"] in ("queued", "active") \
                    and existing.get("source") == "session":
                close_task(state, existing, "done", note="会话任务完成, 自动归集")
                changed = True
    elif tool in ("Task", "Agent"):
        # 子 agent 启动时, 动态绑定到当前目标任务
        ft = focus_task(state)
        if ft:
            agent = ti.get("subagent_type") or "agent"
            desc = (ti.get("description") or "").strip()
            ft.setdefault("binding", {})["agent"] = (agent + (": " + desc if desc else ""))[:60]
            log_event(state, "bind", ft, "agent=" + agent)
            changed = True
    elif tool == "Workflow":
        ft = focus_task(state)
        if ft:
            blob = json.dumps(data.get("tool_response") or {}, ensure_ascii=False)
            m = re.search(r"wf_[a-z0-9-]{6,}", blob)
            wf = m.group(0) if m else (ti.get("name") or "workflow")
            ft.setdefault("binding", {})["workflow"] = wf
            log_event(state, "bind", ft, "workflow=" + wf)
            changed = True
    if changed:
        save_state(state)
    return 0


def hook_stop(data):
    state = load_state()
    cfg = state["config"]
    mode = auto_mode(state)
    if mode == "off":
        return 0
    if state["auto_continues"] >= cfg.get("max_auto", 10):
        print("todo-queue: 本轮自动推进已达 max_auto={} 次, 放行停止。"
              "队列仍有未完成任务, 可手动 /todo-queue:next 继续。".format(cfg.get("max_auto", 10)),
              file=sys.stderr)
        return 0
    ft = focus_task(state)
    if ft:
        reason = ("[todo-queue 自动推进] 目标任务 {}「{}」尚未标记完成。"
                  "请继续完成它; 确认完成并验证后运行 `{} done`。"
                  "若确实无法继续, 运行 `{} auto off` 关闭自动模式并向用户说明原因; "
                  "若任务需要等待外部条件, 运行 `{} pause` 暂停它。").format(
                      ft["id"], ft["title"], self_cmd(), self_cmd(), self_cmd())
    else:
        q = queued(state)
        if not q:
            return 0  # 队列清空 (暂停任务不自动推进), 自然停止
        task = q[0]
        if mode == "smart":
            go, why = smart_decision(state, task)
            if not go:
                print("todo-queue (smart): 放行停止 — {}".format(why), file=sys.stderr)
                state["auto_continues"] = 0
                save_state(state)
                return 0
            header = "▶ 智能推进 ({}), 开始下一个任务".format(why)
        else:
            header = "▶ 自动推进, 开始下一个任务"
        activate(state, task)
        reason = "[todo-queue 自动推进] 队列尚未清空, 继续下一个任务。\n" + activation_block(
            state, task, header=header)
    state["auto_continues"] += 1
    save_state(state)
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


def cmd_hook(args):
    data = read_hook_input()
    handlers = {
        "session-start": hook_session_start,
        "user-prompt": hook_user_prompt,
        "post-tool": hook_post_tool,
        "stop": hook_stop,
    }
    handler = handlers.get(args.event)
    if handler is None:
        print("未知 hook 事件: {}".format(args.event), file=sys.stderr)
        return 1
    try:
        record_session(data, args.event)
        return handler(data)
    except Exception as e:  # hook 失败不应阻塞 Claude Code 主流程
        print("todo-queue hook 错误: {}".format(e), file=sys.stderr)
        return 0


# ---------- statusline ----------

def _sl_clip(s, n):
    """按显示宽度截断 (CJK 占 2 列)。"""
    import unicodedata
    out, w = "", 0
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in "FW" else 1
        if w + cw > n:
            return out + "…"
        out += ch
        w += cw
    return out


def cmd_statusline(args):
    """Claude Code 状态栏: 读 stdin 的 statusline JSON, 输出摘要。

    --rich 输出多行任务列表。statusline 是唯一能在 Claude Code 同一窗体内
    渲染队列的位置 —— 它不开放侧边栏 API, 整个终端渲染区归其 TUI 所有。
    """
    data = read_hook_input()
    ws = data.get("workspace") or {}
    proj = ws.get("project_dir") or ws.get("current_dir")
    if proj:
        os.environ["CLAUDE_PROJECT_DIR"] = proj
    state = load_state()
    ft = focus_task(state)
    q = queued(state)
    paused = paused_tasks(state)
    done_n, total, pct = progress(state)

    if getattr(args, "rich", False):
        C = {"focus": "\033[38;5;73m", "dim": "\033[38;5;245m", "accent": "\033[38;5;109m",
             "warn": "\033[38;5;179m", "r": "\033[0m"}
        if os.environ.get("NO_COLOR"):
            C = dict.fromkeys(C, "")
        lines = []
        if ft:
            lines.append("{}▸ {} {}{}  {}{}{}".format(
                C["focus"], ft["id"], _sl_clip(ft["title"], 40), C["r"],
                C["dim"], progress_bar(state, width=6), C["r"]))
        # 待办压成一行, 放不下的用 (+N) 收尾
        if q:
            shown, w, cap = [], 0, 62
            for t in q:
                piece = "{} {}".format(t["id"], _sl_clip(t["title"], 20))
                if w + len(piece) + 3 > cap:
                    break
                shown.append(piece)
                w += len(piece) + 3
            tail = " (+{})".format(len(q) - len(shown)) if len(q) > len(shown) else ""
            prefix = "待办 " if ft else "{}▸{} 待办 ".format(C["dim"], C["r"])
            lines.append("{}{}{}{}{}".format(
                C["dim"], prefix, " · ".join(shown), tail, C["r"]))
        if paused:
            lines.append("{}⏸ 暂停 {} 个{}".format(C["warn"], len(paused), C["r"]))
        if lines:                      # 队列为空时不输出任何行, 不占地方
            print("\n".join(lines[:args.lines]))
        return 0

    parts = []
    if ft:
        parts.append("🎯 {} {}".format(ft["id"], _sl_clip(ft["title"], 24)))
    parts.append("待办{} ✔{}{}".format(len(q), done_n, " {}%".format(pct) if total else ""))
    if paused:
        parts.append("⏸{}".format(len(paused)))
    m = auto_mode(state)
    if m != "off":
        parts.append("auto" + AUTO_LABEL[m])
    model = (data.get("model") or {}).get("display_name")
    if model:
        parts.append(model)
    cost = (data.get("cost") or {}).get("total_cost_usd")
    if isinstance(cost, (int, float)):
        parts.append("${:.2f}".format(cost))
    print(" │ ".join(parts))
    return 0


# ---------- 入口 ----------

def main():
    parser = argparse.ArgumentParser(prog="tq", description="todo-queue 持久化任务队列")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("add", help="添加任务")
    p.add_argument("title", nargs="+", help="任务标题")
    p.add_argument("-p", "--priority", type=int, default=3, choices=range(1, 6),
                   help="优先级 1(最高)-5, 默认 3")
    p.add_argument("-d", "--detail", default="", help="详情")
    p.add_argument("-a", "--acceptance", default="", help="验收标准")
    p.add_argument("--source", default="user", choices=["user", "session", "code", "collect"])
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="查看队列")
    p.add_argument("--all", action="store_true", help="包含全部已完成/已取消/已迁移")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("next", help="激活下一个任务")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("done", help="标记完成: done [id] [备注...]")
    p.add_argument("words", nargs="*")
    p.set_defaults(func=cmd_done)

    p = sub.add_parser("pause", help="暂停任务: pause [id] [备注...] (默认当前目标)")
    p.add_argument("words", nargs="*")
    p.set_defaults(func=cmd_pause)

    p = sub.add_parser("resume", help="恢复暂停的任务")
    p.add_argument("id")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("focus", help="切换目标任务")
    p.add_argument("id")
    p.set_defaults(func=cmd_focus)

    p = sub.add_parser("drop", aliases=["cancel"], help="取消任务")
    p.add_argument("id")
    p.add_argument("note", nargs="*")
    p.set_defaults(func=cmd_drop)

    p = sub.add_parser("bind", help="绑定 agent/worktree/workflow/session")
    p.add_argument("id")
    p.add_argument("--agent", help="agent 名称或描述")
    p.add_argument("--worktree", help="worktree 路径")
    p.add_argument("--workflow", help="workflow 运行 ID (wf_...)")
    p.add_argument("--session", help="会话 ID")
    p.add_argument("--clear", action="store_true", help="清空绑定")
    p.set_defaults(func=cmd_bind)

    p = sub.add_parser("fork", help="多选任务迁移到新 session: fork tq-1 tq-3 [--worktree] [--launch]")
    p.add_argument("ids", nargs="+", help="要迁出的任务 ID")
    p.add_argument("--name", help="fork 名称 (默认时间戳)")
    p.add_argument("--worktree", action="store_true", help="创建 git worktree 承载新 session")
    p.add_argument("--launch", action="store_true", help="自动在新终端启动 claude")
    p.set_defaults(func=cmd_fork)

    p = sub.add_parser("history", help="会话历史 + 完成度")
    p.add_argument("--current", action="store_true", help="仅当前会话")
    p.add_argument("--session", help="指定会话 ID 前缀")
    p.add_argument("--limit", type=int, default=30, help="事件条数, 默认 30")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("gc", help="清理: 归档旧任务, 回收 fork 队列 (每日也会自动运行)")
    p.add_argument("--dry-run", action="store_true", help="只预览, 不实际改动")
    p.set_defaults(func=cmd_gc)

    p = sub.add_parser("setup-check", help="检查可选配置项状态")
    p.add_argument("--mark", action="store_true", help="写入已提示标志")
    p.set_defaults(func=cmd_setup_check)

    p = sub.add_parser("mode", help="passive(默认,只显示) | active(介入对话流程)")
    p.add_argument("mode", nargs="?", choices=["passive", "active"])
    p.set_defaults(func=cmd_mode)

    p = sub.add_parser("auto", help="自动推进模式: off | on | smart (仅 active 模式生效)")
    p.add_argument("switch", nargs="?", choices=["on", "off", "smart"])
    p.set_defaults(func=cmd_auto)

    p = sub.add_parser("status", help="统计概览")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("path", help="打印队列文件路径")
    p.set_defaults(func=cmd_path)

    p = sub.add_parser("hook", help="hooks 入口 (读 stdin JSON)")
    p.add_argument("event", choices=["session-start", "user-prompt", "post-tool", "stop"])
    p.set_defaults(func=cmd_hook)

    p = sub.add_parser("statusline", help="Claude Code 状态栏输出 (读 stdin JSON)")
    p.add_argument("--rich", action="store_true", help="多行任务列表 (同窗体内显示队列)")
    p.add_argument("--lines", type=int, default=4, help="--rich 时最多输出几行, 默认 4")
    p.set_defaults(func=cmd_statusline)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
