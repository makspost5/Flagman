"""PostToolUse / UserPromptSubmit logic of the reminder hook."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from . import autograph, model, store

DEFAULT_WATCH = "status.md,plan.md"
WATCH_ENV = "CLAUDE_PLUGIN_OPTION_WATCH_FILES"  # the plugin's watch_files setting
TASKS_DIR_ENV = "CLAUDE_PLUGIN_OPTION_TASKS_DIR"
TODO_TOOLS = ("TodoWrite", "TaskCreate")
MAX_ITEMS = 8


def watch_patterns(value: str | None = None) -> list[str]:
    """File names or globs from the watch_files setting; empty means the default."""
    if value is None:
        value = os.environ.get(WATCH_ENV, "")
    pats = [p.strip().lower() for p in value.split(",")]
    pats = [p for p in pats if p and not p.startswith("${user_config.")]
    return pats or DEFAULT_WATCH.split(",")


def is_watched(file_path: str, patterns: list[str]) -> bool:
    name = os.path.basename(file_path.replace("\\", "/")).lower()
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def _norm(path) -> str:
    # realpath, not abspath: the task folder comes from Path.resolve(), so the edited file's
    # path must resolve the same symlinks (/var -> /private/var on macOS) and Windows 8.3
    # short names (RUNNER~1), or the session folder never matches.
    return os.path.normcase(os.path.realpath(str(path)))


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(name or "none"))[:80]


def _marker(state_dir: Path, sid: str, task: Path) -> Path:
    digest = hashlib.sha1(_norm(task).encode("utf-8")).hexdigest()[:8]
    return state_dir / ("reminded-%s-%s" % (_safe(sid), digest))


def _map_path(state_dir: Path, sid: str) -> Path:
    return state_dir / ("map-%s.json" % _safe(sid))


def _read_map(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _items_text(graph: dict, sid: str) -> str:
    stages = graph.get("stages") or []
    parts = []
    for it in graph.get("items", []):
        if it.get("session") != sid:
            continue
        st = it.get("stage", -1)
        name = stages[st] if isinstance(st, int) and 0 <= st < len(stages) else "-"
        parts.append("%s %s/%s" % (it.get("id"), name, it.get("status")))
    shown = parts[:MAX_ITEMS]
    if len(parts) > MAX_ITEMS:
        shown.append("+%d more" % (len(parts) - MAX_ITEMS))
    return ", ".join(shown) if shown else "none"


def _session_text(graph: dict, sid: str, task: Path, cmd: str) -> str:
    return ('Task graph %s, session %s items: %s. If a stage or status changed, run: '
            '%s "%s" start|next|done <id>, or ask <id> "<what you need from the user>" '
            '(next = the next stage is finished; add status=review when it now waits on others; '
            'anything else: set <id> stage= status=). '
            'Otherwise ignore this.'
            % (graph["task"]["key"], sid, _items_text(graph, sid), cmd, task))


def _neutral_text(graph: dict, task: Path, cmd: str) -> str:
    return ('Task graph %s exists. If an item\'s stage or status changed, run: '
            '%s "%s" start|next|done <id>, or ask <id> "<question>" '
            '(anything else: set <id> stage= status=). Items, deps and '
            'sessions belong to the architect (fm add/dep/session). '
            'Summary: %s "%s" show.'
            % (graph["task"]["key"], cmd, task, cmd, task))


def _auto_marker(state_dir: Path, sid: str) -> Path:
    # not "reminded-": a new prompt must not clear it, the offer comes once per session
    return Path(state_dir) / ("autograph-%s" % _safe(sid))


def _bump_counter(state_dir: Path, sid: str) -> int:
    path = Path(state_dir) / ("tasks-%s" % _safe(sid))
    try:
        n = int(path.read_text(encoding="utf-8") or 0) + 1
    except (OSError, ValueError):
        n = 1
    path.write_text(str(n), encoding="utf-8")
    return n


def _folder_hint(root: str) -> str:
    tasks_dir = os.environ.get(TASKS_DIR_ENV, "").strip()
    if not tasks_dir or tasks_dir.startswith("${user_config."):
        tasks_dir = str(Path(root) / ".tasks")
    return Path(tasks_dir).resolve().as_posix() + "/<KEY>"


def _auto_graph(payload: dict, state_dir: Path, fm_cmd: str, patterns: list[str],
                auto: str, auto_min: int) -> str | None:
    """The auto graph offer, or None. Only for a task without a graph nearby."""
    if auto == "off":
        return None
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    sid = str(payload.get("session_id") or "")
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else ""
    file_path = tool_input.get("file_path")
    if tool == "TodoWrite":
        todos = tool_input.get("todos")
        n, source = (len(todos) if isinstance(todos, list) else 0), "todo list"
    elif tool == "TaskCreate":
        Path(state_dir).mkdir(parents=True, exist_ok=True)
        n, source = _bump_counter(state_dir, sid), "task list"
    elif isinstance(file_path, str) and file_path and autograph.is_plan_file(file_path, patterns):
        try:
            if os.path.getsize(file_path) > autograph.MAX_BYTES:
                return None
            with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                n = autograph.count_items(fh.read())
        except OSError:
            return None
        source = os.path.basename(file_path.replace("\\", "/"))
        cwd = cwd or os.path.dirname(file_path)
    else:
        return None
    if n < auto_min or not cwd or store.find_graph_upwards(cwd) is not None:
        return None
    marker = _auto_marker(state_dir, sid)
    if marker.exists():
        return None
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8")
    return autograph.reminder(auto, n, source, _folder_hint(cwd), fm_cmd)


def handle_post_tool(payload: dict, state_dir: Path, fm_cmd: str,
                     patterns: list[str] | None = None, auto: str | None = None,
                     auto_min: int | None = None) -> str | None:
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if patterns is None:
        patterns = watch_patterns()
    task = None
    if isinstance(file_path, str) and file_path and payload.get("tool_name") not in TODO_TOOLS:
        if not (is_watched(file_path, patterns) or autograph.is_plan_file(file_path, patterns)):
            return None
        task = store.find_graph_upwards(file_path)
    if task is None:
        return _auto_graph(payload, state_dir, fm_cmd, patterns,
                           auto if auto is not None else autograph.mode(),
                           auto_min if auto_min is not None else autograph.min_items())
    if not is_watched(file_path, patterns):
        return None
    try:
        graph = store.load(task)
        graph["task"]["key"]
        sessions = graph.get("sessions") or []
    except (model.GraphError, KeyError, TypeError, AttributeError):
        return None
    state_dir = Path(state_dir)
    sid = str(payload.get("session_id") or "")
    state_dir.mkdir(parents=True, exist_ok=True)
    here = _norm(file_path)
    task_key = _norm(task)
    found = None
    for s in sessions:
        d = s.get("dir") or "sessions/%s" % (s.get("name") or s.get("id") or "")
        if not (s.get("dir") or s.get("name") or s.get("id")):
            continue
        folder = _norm(Path(task) / d)
        if here == folder or here.startswith(folder + os.sep):
            found = s.get("id")
            break
    mp = _map_path(state_dir, sid)
    if found is not None:
        data = _read_map(mp)
        data[task_key] = found
        mp.write_text(json.dumps(data), encoding="utf-8")
    else:
        found = _read_map(mp).get(task_key)
        if found is not None and not any(s.get("id") == found for s in sessions):
            found = None
    marker = _marker(state_dir, sid, task)
    if marker.exists():
        return None
    marker.write_text("", encoding="utf-8")
    if found is not None:
        return _session_text(graph, found, task, fm_cmd)
    return _neutral_text(graph, task, fm_cmd)


def handle_prompt(payload: dict, state_dir: Path) -> None:
    prefix = "reminded-%s-" % _safe(str(payload.get("session_id") or ""))
    try:
        for f in Path(state_dir).iterdir():
            if f.name.startswith(prefix):
                try:
                    f.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def _state_dir() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_DATA")
    return Path(env) if env else Path.home() / ".flagman"


def _log_error(state_dir: Path, exc: BaseException) -> None:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / "hook-errors.log", "a", encoding="utf-8") as fh:
            fh.write("%s %s: %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"),
                                      type(exc).__name__, exc))
    except OSError:
        pass


def main(argv: list[str]) -> int:
    state_dir = _state_dir()
    try:
        mode = argv[1] if len(argv) > 1 else ""
        raw = sys.stdin.buffer.read().decode("utf-8-sig")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        if mode == "post-tool":
            if os.name == "nt":
                # plain `fm` from the plugin's bin/ on PATH: PowerShell runs fm.cmd, Git Bash
                # runs fm. `bash` in PowerShell is WSL, and an extensionless path opens the
                # Windows "choose an app" dialog.
                fm_cmd = "fm"
            else:
                # run through bash: a checkout made on Windows has no exec bit on bin/fm
                fm_cmd = 'bash "%s"' % (Path(__file__).resolve().parent.parent.parent
                                        / "bin" / "fm").as_posix()
            text = handle_post_tool(payload, state_dir, fm_cmd)
            if text:
                out = {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                              "additionalContext": text}}
                sys.stdout.buffer.write(json.dumps(out).encode("utf-8"))
                sys.stdout.buffer.flush()
        elif mode == "prompt":
            handle_prompt(payload, state_dir)
    except Exception as exc:  # the hook must never disturb the session
        _log_error(state_dir, exc)
    return 0
