"""The `fm` command: one short command per graph update, one short line of output."""
from __future__ import annotations

import json
import re
import shutil
import sys
import webbrowser
from pathlib import Path

from . import model, store
from .model import GraphError

USAGE = """\
usage: fm [--root DIR] TASK COMMAND [ARGS]   (arguments are key=value)
       fm --version
  init TITLE [lang=en|ru] [due=YYYY-MM-DD] [link=LABEL|HREF]...
  import FILE.json
  start ID | done ID | ask ID QUESTION | next ID [status=]   [summary=] on each
         start: status=doing; done: status=done; ask: status=wait-me with the question;
         next: the next stage is finished, status=doing (done at the last stage)
  set ID [stage=] [status=] [wait=] [summary=] [title=] [group=] [session=]
  add ID TITLE [group= session= stage= status= after=DEP,DEP summary= wait=]
         [detail=TEXT]... [file=PATH]... [link=LABEL|HREF]...
  rm ID
  dep ID (+DEP | -DEPID)... [note=TEXT]      DEP is ID[@STAGE][:part]
  group ID [title=] [estimate=]
  session ID [name= dir= note= queue=a,b,c]
  conflict A B WHY      add;  conflict A B -   remove
  show | check
  log [n=20]              the last changes, oldest first
  open [--no-browser]     copy the page next to taskgraph.js and open it
"""

_KEY = re.compile(r"^([a-z]+)=(.*)$", re.DOTALL)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class UsageError(Exception):
    """Bad command line: print usage, exit 2 (one line only if usage is False)."""

    def __init__(self, message: str, usage: bool = True) -> None:
        super().__init__(message)
        self.usage = usage


def _unknown_key(cmd: str, key: str, allowed: set[str]) -> UsageError:
    return UsageError("unknown key '%s' for %s (allowed: %s)"
                      % (key, cmd, ", ".join(sorted(allowed)) or "none"), usage=False)


def _parse_args(args: list[str], allowed: set[str], repeat: set[str] = frozenset(),
                min_pos: int = 0, max_pos: int | None = None, cmd: str = "this command"):
    pos: list[str] = []
    opts: dict[str, list[str]] = {}
    for a in args:
        m = _KEY.match(a)
        if m and m.group(1) in allowed:
            opts.setdefault(m.group(1), []).append(m.group(2))
        else:  # also a title or text that merely looks like key=value
            pos.append(a)
    for k, vals in opts.items():
        if len(vals) > 1 and k not in repeat:
            raise UsageError("'%s=' given more than once" % k)
    if max_pos is not None and len(pos) > max_pos:
        # a key=word is a typo only when no free positional slot is left for it
        for a in reversed(pos):
            m = _KEY.match(a)
            if m:
                raise _unknown_key(cmd, m.group(1), allowed)
    if len(pos) < min_pos or (max_pos is not None and len(pos) > max_pos):
        raise UsageError("wrong number of arguments")
    return pos, opts


def _one(opts: dict[str, list[str]], key: str):
    return opts[key][0] if key in opts else None


def _split_list(text: str) -> list[str]:
    return [p.strip() for p in text.split(",") if p.strip()]


def _link(text: str) -> dict:
    label, sep, href = text.partition("|")
    if not sep:
        return {"label": text, "href": text}
    return {"label": label.strip(), "href": href.strip()}


def _find_item(graph: dict, iid: str) -> dict:
    for it in graph.get("items") or []:
        if it.get("id") == iid:
            return it
    raise GraphError("unknown item '%s'" % iid)


def _last(graph: dict) -> int:
    return len(graph.get("stages") or []) - 1


def _check_status(value: str) -> str:
    if value not in model.STATUSES:
        raise GraphError("unknown status '%s'; statuses: %s"
                         % (value, ", ".join(model.STATUSES)))
    return value


def _apply_stage_status(graph: dict, it: dict, stage, status, wait) -> list[str]:
    """Shared by `set` and `add`; returns "key=value" words for the message."""
    old_status = it.get("status")
    words: list[str] = []
    if stage is not None:
        it["stage"] = model.parse_stage(graph, stage)
        words.append("stage=%s" % stage)
        if it["stage"] == _last(graph) and status is None:
            it["status"] = "done"
    if status is not None:
        it["status"] = _check_status(status)
        words.append("status=%s" % status)
        if status == "done":
            it["stage"] = _last(graph)
    elif it.get("status") == "done" and stage is not None:
        words.append("status=done")
    if wait is not None:
        it["wait"] = wait
        words.append("wait=%s" % wait)
    elif old_status == "wait-me" and it.get("status") != "wait-me":
        it["wait"] = ""
    return words


# ---------------------------------------------------------------- commands

def _cmd_init(folder: Path, args: list[str]):
    pos, o = _parse_args(args, {"lang", "due", "link"}, {"link"}, 1, 1, "init")
    lang = _one(o, "lang")
    # Empty, or the skill's ${user_config.lang} left unsubstituted: use the default.
    if not lang or lang.startswith("${user_config."):
        lang = model.DEFAULT_LANG
    if lang not in model.LANGS:
        raise GraphError("unknown lang '%s' (expected one of %s)"
                         % (lang, ", ".join(model.LANGS)))
    due = _one(o, "due")
    if due is not None and not _DATE.match(due):
        raise GraphError("bad due '%s'; expected YYYY-MM-DD" % due)
    if (folder / store.FILE).exists():
        raise GraphError("%s already exists in %s" % (store.FILE, folder))
    key = folder.resolve().name
    graph = model.new_graph(key, pos[0], lang)
    graph["task"]["due"] = due
    graph["task"]["links"] = [_link(x) for x in o.get("link", [])]

    def change(_g: dict) -> str:
        return "created %s (%s)" % (store.FILE, ", ".join(graph["stages"]))

    return store.update(folder, change, create=graph)


def _cmd_import(folder: Path, args: list[str]):
    pos, _ = _parse_args(args, set(), min_pos=1, max_pos=1, cmd="import")
    try:
        with open(pos[0], "r", encoding="utf-8-sig") as fh:
            new = json.load(fh)
    except OSError as exc:
        raise GraphError("cannot read %s: %s" % (pos[0], exc)) from None
    except ValueError as exc:
        raise GraphError("invalid JSON in %s: %s" % (pos[0], exc)) from None
    if not isinstance(new, dict):
        raise GraphError("%s: top-level value is not an object" % pos[0])
    has_graph = (folder / store.FILE).exists()
    old = store.load(folder) if has_graph else {}
    rev = int((old.get("task") or {}).get("rev") or 0)
    past = model.history(old) if has_graph else None  # the history goes on across an import
    task = new.get("task")
    if task is not None and not isinstance(task, dict):
        raise GraphError("%s: 'task' is not an object" % pos[0])

    def change(graph: dict) -> str:
        graph.clear()
        graph.update(new)
        model.stringify_ids(graph)
        model.normalize_import(graph)
        graph.setdefault("task", {})["rev"] = rev
        if past is not None:
            graph["history"] = past
        return "imported %d items" % len(graph.get("items") or [])

    try:
        return store.update(folder, change, create=None if has_graph else {})
    except (AttributeError, TypeError, KeyError) as exc:
        raise GraphError("%s: malformed graph (%s)" % (pos[0], exc)) from None


def _cmd_set(folder: Path, args: list[str]):
    pos, o = _parse_args(args, {"stage", "status", "wait", "summary", "title",
                                "group", "session"}, min_pos=1, max_pos=1, cmd="set")
    if not o:
        raise UsageError("set needs at least one key=value")

    def change(graph: dict) -> str:
        it = _find_item(graph, pos[0])
        words = _apply_stage_status(graph, it, _one(o, "stage"), _one(o, "status"),
                                    _one(o, "wait"))
        for key in ("summary", "title"):
            if key in o:
                it[key] = o[key][0]
                words.append("%s=%s" % (key, o[key][0]))
        for key in ("group", "session"):
            if key in o:
                it[key] = o[key][0] or None
                words.append("%s=%s" % (key, o[key][0]))
        return "set %s %s" % (pos[0], " ".join(words))

    return store.update(folder, change)


def _shortcut(name: str, folder: Path, args: list[str]):
    """start / done / ask / next: common `set` updates without stage names or indexes."""
    allowed = {"summary"} | ({"status"} if name == "next" else set())
    npos = 2 if name == "ask" else 1
    pos, o = _parse_args(args, allowed, min_pos=npos, max_pos=npos, cmd=name)

    def change(graph: dict) -> str:
        it = _find_item(graph, pos[0])
        stage = status = wait = None
        if name == "start":
            status = "doing"
        elif name == "done":
            status = "done"
        elif name == "ask":
            if not pos[1].strip():
                raise UsageError("ask needs a question", usage=False)
            status, wait = "wait-me", pos[1]
        else:  # next
            cur = it.get("stage", -1)
            cur = cur if isinstance(cur, int) else -1
            if cur >= _last(graph):
                raise GraphError("item '%s' is already at the last stage" % pos[0])
            stage = graph["stages"][cur + 1]
            status = _one(o, "status")
            if status is None and cur + 1 < _last(graph):
                status = "doing"
        words = _apply_stage_status(graph, it, stage, status, wait)
        if "summary" in o:
            it["summary"] = o["summary"][0]
            words.append("summary=%s" % o["summary"][0])
        return "%s %s %s" % (name, pos[0], " ".join(words))

    return store.update(folder, change)


def _cmd_add(folder: Path, args: list[str]):
    pos, o = _parse_args(args, {"group", "session", "stage", "status", "after", "summary",
                                "wait", "detail", "file", "link"},
                         {"detail", "file", "link"}, 2, 2, "add")

    def change(graph: dict) -> str:
        it = {"id": pos[0], "title": pos[1], "group": _one(o, "group") or None,
              "session": _one(o, "session") or None, "stage": -1, "status": "todo",
              "wait": "", "deps": [], "summary": _one(o, "summary") or "",
              "details": list(o.get("detail", [])),
              "links": [_link(x) for x in o.get("link", [])],
              "files": list(o.get("file", []))}
        _apply_stage_status(graph, it, _one(o, "stage"), _one(o, "status"),
                            _one(o, "wait"))
        for spec in _split_list(_one(o, "after") or ""):
            dep = model.parse_dep(graph, spec)
            dep["note"] = ""
            it["deps"].append(dep)
        graph.setdefault("items", []).append(it)
        return "added %s '%s'" % (pos[0], pos[1])

    return store.update(folder, change)


def _cmd_rm(folder: Path, args: list[str]):
    pos, _ = _parse_args(args, set(), min_pos=1, max_pos=1, cmd="rm")

    def change(graph: dict) -> str:
        it = _find_item(graph, pos[0])
        refs: list[str] = []
        users = [o["id"] for o in graph["items"]
                 if any(d.get("id") == pos[0] for d in o.get("deps") or [])]
        if users:
            refs.append("dependency of " + ", ".join(users))
        queues = [s["id"] for s in graph.get("sessions") or []
                  if pos[0] in (s.get("queue") or [])]
        if queues:
            refs.append("in queue of session " + ", ".join(queues))
        confl = [c["b"] if c.get("a") == pos[0] else c["a"]
                 for c in graph.get("conflicts") or [] if pos[0] in (c.get("a"), c.get("b"))]
        if confl:
            refs.append("conflicts with " + ", ".join(confl))
        if refs:
            raise GraphError("cannot remove %s: %s; remove those first"
                             % (pos[0], "; ".join(refs)))
        graph["items"].remove(it)
        return "removed %s" % pos[0]

    return store.update(folder, change)


def _cmd_dep(folder: Path, args: list[str]):
    pos, o = _parse_args(args, {"note"}, min_pos=2, cmd="dep")
    iid, specs = pos[0], pos[1:]
    for s in specs:
        m = _KEY.match(s)
        if m:
            raise _unknown_key("dep", m.group(1), {"note"})
        if s[:1] not in ("+", "-") or len(s) < 2:
            raise UsageError("dependency '%s' must start with + or -" % s)

    def change(graph: dict) -> str:
        it = _find_item(graph, iid)
        deps = it.setdefault("deps", [])
        words = []
        for s in specs:
            if s[0] == "-":
                before = len(deps)
                deps[:] = [d for d in deps if d.get("id") != s[1:]]
                if len(deps) == before:
                    raise GraphError("item '%s' has no dependency on '%s'" % (iid, s[1:]))
            else:
                dep = model.parse_dep(graph, s[1:])
                dep["note"] = _one(o, "note") or ""
                deps[:] = [d for d in deps if d.get("id") != dep["id"]]
                deps.append(dep)
            words.append(s)
        return "dep %s %s" % (iid, " ".join(words))

    return store.update(folder, change)


def _cmd_group(folder: Path, args: list[str]):
    pos, o = _parse_args(args, {"title", "estimate"}, min_pos=1, max_pos=1, cmd="group")

    def change(graph: dict) -> str:
        groups = graph.setdefault("groups", [])
        grp = next((g for g in groups if g.get("id") == pos[0]), None)
        verb = "updated"
        if grp is None:
            grp = {"id": pos[0], "title": pos[0]}
            groups.append(grp)
            verb = "created"
        for key in ("title", "estimate"):
            if key in o:
                grp[key] = o[key][0]
        return "%s group %s" % (verb, pos[0])

    return store.update(folder, change)


def _cmd_session(folder: Path, args: list[str]):
    if any(a.startswith("state=") for a in args):
        raise GraphError("session state is computed from its items; drop 'state='")
    pos, o = _parse_args(args, {"name", "dir", "note", "queue"},
                         min_pos=1, max_pos=1, cmd="session")

    def change(graph: dict) -> str:
        sessions = graph.setdefault("sessions", [])
        ses = next((s for s in sessions if s.get("id") == pos[0]), None)
        verb = "updated"
        if ses is None:
            ses = {"id": pos[0], "name": pos[0], "dir": "", "note": "", "queue": []}
            sessions.append(ses)
            verb = "created"
        for key in ("name", "dir", "note"):
            if key in o:
                ses[key] = o[key][0]
        ses.pop("state", None)  # no longer stored: computed from the items
        if "queue" in o:
            ses["queue"] = _split_list(o["queue"][0])
        if verb == "created" and not ses["dir"]:
            ses["dir"] = "sessions/%s" % (ses["name"] or ses["id"])
        return "%s session %s" % (verb, pos[0])

    return store.update(folder, change)


def _cmd_conflict(folder: Path, args: list[str]):
    pos, _ = _parse_args(args, set(), min_pos=3, max_pos=3, cmd="conflict")
    a, b, why = pos

    def change(graph: dict) -> str:
        conflicts = graph.setdefault("conflicts", [])
        same = [c for c in conflicts if {c.get("a"), c.get("b")} == {a, b}]
        if why == "-":
            if not same:
                raise GraphError("no conflict between '%s' and '%s'" % (a, b))
            conflicts[:] = [c for c in conflicts if c not in same]
            return "conflict %s %s removed" % (a, b)
        if same:
            same[0]["why"] = why
        else:
            conflicts.append({"a": a, "b": b, "why": why})
        return "conflict %s %s: %s" % (a, b, why)

    return store.update(folder, change)


_UPDATE_COMMANDS = {"import": _cmd_import, "set": _cmd_set, "add": _cmd_add,
                    "rm": _cmd_rm, "dep": _cmd_dep, "group": _cmd_group,
                    "session": _cmd_session, "conflict": _cmd_conflict,
                    **{n: (lambda f, a, n=n: _shortcut(n, f, a))
                       for n in ("start", "done", "ask", "next")}}
_COMMANDS = {"init", "show", "check", "log", "open", *_UPDATE_COMMANDS}


PAGE_TEMPLATE = Path(__file__).resolve().parent.parent.parent / "page" / "taskgraph.html"
PLUGIN_JSON = Path(__file__).resolve().parent.parent.parent / ".claude-plugin" / "plugin.json"


def _version() -> str:
    """The plugin version from plugin.json, the one place a release sets it."""
    try:
        version = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise GraphError("cannot read the version from %s: %s" % (PLUGIN_JSON, exc)) from exc
    return "flagman %s" % version


def _cmd_open(folder: Path, args: list[str], out) -> int:
    if any(a != "--no-browser" for a in args):
        raise UsageError("open takes only --no-browser")
    if not PAGE_TEMPLATE.is_file():
        raise GraphError("page template not found: %s" % PAGE_TEMPLATE)
    target = folder / "taskgraph.html"
    try:
        shutil.copyfile(PAGE_TEMPLATE, target)
    except OSError as exc:
        raise GraphError("cannot write %s: %s" % (target, exc)) from None
    out.write("%s\n" % target)
    if "--no-browser" not in args:
        webbrowser.open(target.resolve().as_uri())
    return 0


def _refresh_page(folder: Path) -> None:
    """Replace a page copy left by an older plugin, so an update shows on the current page.

    Only a copy `fm open` made is refreshed; a failure (the file in use, read-only) leaves the old copy
    and never fails the update that already succeeded.
    """
    target = folder / "taskgraph.html"
    try:
        if not target.is_file() or target.read_bytes() == PAGE_TEMPLATE.read_bytes():
            return
        shutil.copyfile(PAGE_TEMPLATE, target)
    except OSError:
        pass


def _run(argv: list[str], cwd: str, out, err) -> int:
    args = list(argv)
    root = None
    while args and (args[0] == "--root" or args[0].startswith("--root=")):
        if args[0] == "--root":
            if len(args) < 2:
                raise UsageError("--root needs a directory")
            root = args[1]
            del args[:2]
        else:
            root = args[0][len("--root="):]
            del args[:1]
    if args in (["--version"], ["version"]):
        out.write(_version() + "\n")
        return 0
    if len(args) < 2:
        raise UsageError("need TASK and COMMAND")
    task, command, rest = args[0], args[1], args[2:]
    if command not in _COMMANDS:
        raise UsageError("unknown command '%s'" % command)
    folder = store.resolve_task(task, cwd, root, need_graph=command not in ("init", "import"))
    if command == "open":
        return _cmd_open(folder, rest, out)
    if command == "show":
        _parse_args(rest, set(), max_pos=0, cmd="show")
        out.write("\n".join(model.summary_lines(store.load(folder))) + "\n")
        return 0
    if command == "log":
        _, o = _parse_args(rest, {"n"}, max_pos=0, cmd="log")
        n = _one(o, "n")
        if n is not None and not (n.isdigit() and int(n) > 0):
            raise UsageError("n must be a positive number", usage=False)
        out.write("\n".join(model.history_lines(store.load(folder), int(n or 20))) + "\n")
        return 0
    if command == "check":
        _parse_args(rest, set(), max_pos=0, cmd="check")
        problems = model.validate(store.load(folder))
        if not problems:
            out.write("ok\n")
            return 0
        err.write("\n".join(problems) + "\n")
        return 1
    handler = _cmd_init if command == "init" else _UPDATE_COMMANDS[command]
    graph, msg = handler(folder, rest)
    _refresh_page(folder)
    out.write("ok: %s (rev %d)\n" % (msg, graph["task"]["rev"]))
    return 0


def main(argv: list[str], cwd: str | None = None, out=None, err=None) -> int:
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    cwd = cwd if cwd is not None else str(Path.cwd())
    try:
        return _run(argv, cwd, out, err)
    except UsageError as exc:
        err.write("error: %s\n%s" % (exc, USAGE if exc.usage else ""))
        return 2
    except GraphError as exc:
        err.write("error: %s\n" % exc)
        return 1
    except Exception as exc:  # hand-edited file, disk trouble: one line, no traceback
        err.write("error: %s\n" % (str(exc) or type(exc).__name__))
        return 1
