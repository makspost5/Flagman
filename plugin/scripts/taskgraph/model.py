"""Task graph file format, validation, stage/dep parsing, item states, summary."""
from __future__ import annotations

import json

STATUSES = ("todo", "doing", "wait-me", "review", "done")
LANGS = ("ru", "en")
DEFAULT_STAGES = {
    "ru": ["план", "код", "ревью", "PR", "влито", "готово"],
    "en": ["plan", "code", "review", "PR", "merged", "done"],
}
HEADER = "// Task graph data. Written by fm (Flagman); do not edit by hand.\n"
PREFIX = "window.TASKGRAPH = "
MAX_SUMMARY_LINES = 15
MAX_IDS_PER_LINE = 10
HISTORY_MAX = 100      # entries kept in `history`; older ones are dropped
HISTORY_MSG_MAX = 200  # characters of one entry's message


VERSION = 1  # taskgraph.js format; 1.x releases read it, new fields stay optional


class GraphError(Exception):
    """Invalid graph file or invalid user input."""


DEFAULT_LANG = "en"


def new_graph(key: str, title: str, lang: str = DEFAULT_LANG) -> dict:
    return {
        "version": VERSION,
        "lang": lang,
        "task": {"key": key, "title": title, "links": [], "due": None,
                 "updated": None, "rev": 0},
        "stages": list(DEFAULT_STAGES.get(lang, DEFAULT_STAGES["en"])),
        "groups": [],
        "sessions": [],
        "items": [],
        "conflicts": [],
    }


def parse(text: str) -> dict:
    lines = text.lstrip("﻿").splitlines()
    while lines and lines[0].lstrip().startswith("//"):
        lines.pop(0)
    body = "\n".join(lines).strip()
    if not body.startswith(PREFIX.strip()):
        raise GraphError("not a taskgraph file: missing 'window.TASKGRAPH =' wrapper")
    body = body[len(PREFIX.strip()):].strip()
    if not body.endswith(";"):
        raise GraphError("not a taskgraph file: missing closing ';'")
    try:
        data = json.loads(body[:-1])
    except ValueError as exc:
        raise GraphError("not a taskgraph file: invalid JSON (%s)" % exc) from None
    if not isinstance(data, dict):
        raise GraphError("not a taskgraph file: top-level value is not an object")
    return data


def dump(graph: dict) -> str:
    return HEADER + PREFIX + json.dumps(graph, ensure_ascii=False, indent=1) + ";\n"


def _find_cycles(graph: dict) -> list[list[str]]:
    deps: dict[str, list[str]] = {}
    for it in graph.get("items") or []:
        if it.get("id") is None:
            continue
        deps.setdefault(it["id"], [])
        for d in it.get("deps") or []:
            if d.get("id") != it["id"]:
                deps[it["id"]].append(d.get("id"))
    cycles: list[list[str]] = []
    state: dict[str, int] = {}  # 1 = on stack, 2 = finished
    stack: list[str] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in deps.get(node, []):
            if nxt not in deps:
                continue
            if state.get(nxt) == 1:
                cycles.append(stack[stack.index(nxt):] + [nxt])
            elif state.get(nxt) is None:
                visit(nxt)
        stack.pop()
        state[node] = 2

    for node in list(deps):
        if state.get(node) is None:
            visit(node)
    return cycles


def _is_id(value) -> bool:
    return isinstance(value, str) and value != ""


def validate(graph: dict) -> list[str]:
    problems: list[str] = []
    version = graph.get("version")
    is_int = isinstance(version, int) and not isinstance(version, bool)
    if not (is_int and version == VERSION):
        if is_int and version > VERSION:
            problems.append("format version %d is newer than this fm reads (%d); "
                            "update the plugin" % (version, VERSION))
        else:
            problems.append("unknown format version %r (expected %d)" % (version, VERSION))
    lang = graph.get("lang")
    if lang not in LANGS:
        problems.append("unknown lang '%s' (expected one of %s)" % (lang, ", ".join(LANGS)))
    stages = graph.get("stages")
    if not (isinstance(stages, list) and len(stages) >= 2
            and all(isinstance(x, str) and x for x in stages)
            and len(set(stages)) == len(stages)):
        problems.append("stages must be a list of at least 2 unique non-empty strings")
        stages = stages if isinstance(stages, list) else []
    items = graph.get("items") or []
    seen: set[str] = set()
    for n, it in enumerate(items, 1):
        iid = it.get("id")
        if iid is None:
            problems.append("item #%d has no id" % n)
            continue
        if not _is_id(iid):
            problems.append("item #%d: id must be a non-empty string (got %r)" % (n, iid))
            continue
        if iid in seen:
            problems.append("duplicate item id '%s'" % iid)
        seen.add(iid)
    for kind, rows in (("group", graph.get("groups")), ("session", graph.get("sessions"))):
        for n, row in enumerate(rows or [], 1):
            if not _is_id(row.get("id")):
                problems.append("%s #%d: id must be a non-empty string (got %r)"
                                % (kind, n, row.get("id")))
    group_ids = {g.get("id") for g in graph.get("groups") or [] if _is_id(g.get("id"))}
    session_ids = {s.get("id") for s in graph.get("sessions") or [] if _is_id(s.get("id"))}
    for it in items:
        iid = it.get("id")
        if not _is_id(iid):
            continue
        stage = it.get("stage")
        if isinstance(stage, str):
            problems.append("item '%s': unknown stage '%s' (stages: %s)"
                            % (iid, stage, ", ".join(stages)))
        elif not isinstance(stage, int) or isinstance(stage, bool) \
                or not -1 <= stage < len(stages):
            problems.append("item '%s': stage %r out of range (-1..%d)"
                            % (iid, stage, len(stages) - 1))
        if it.get("status") not in STATUSES:
            problems.append("item '%s': unknown status '%s'" % (iid, it.get("status")))
        if it.get("session") is not None and it["session"] not in session_ids:
            problems.append("item '%s': unknown session '%s'" % (iid, it["session"]))
        if it.get("group") is not None and it["group"] not in group_ids:
            problems.append("item '%s': unknown group '%s'" % (iid, it["group"]))
        for d in it.get("deps") or []:
            did = d.get("id")
            if did == iid:
                problems.append("item '%s': depends on itself" % iid)
            elif did not in seen:
                problems.append("item '%s': dependency on unknown item '%s'" % (iid, did))
            else:
                dstage = d.get("stage")
                if isinstance(dstage, str):
                    problems.append("item '%s': dependency on '%s' has unknown stage '%s'"
                                    " (stages: %s)" % (iid, did, dstage, ", ".join(stages)))
                elif dstage is not None and (not isinstance(dstage, int)
                                           or not 0 <= dstage < len(stages)):
                    problems.append("item '%s': dependency on '%s' has stage %r out of range"
                                    % (iid, did, dstage))
    for s in graph.get("sessions") or []:
        for qid in s.get("queue") or []:
            if qid not in seen:
                problems.append("session '%s': queue has unknown item '%s'"
                                % (s.get("id"), qid))
    for c in graph.get("conflicts") or []:
        a, b = c.get("a"), c.get("b")
        for x in (a, b):
            if x not in seen:
                problems.append("conflict %s/%s: unknown item '%s'" % (a, b, x))
        if a == b:
            problems.append("conflict: item '%s' conflicts with itself" % a)
    for cyc in _find_cycles(graph):
        problems.append("dependency cycle: " + " -> ".join(cyc))
    return problems


def stringify_ids(graph: dict) -> None:
    """Turn numeric ids (and references to them) into strings, in place."""
    def conv(value):
        is_num = isinstance(value, int) and not isinstance(value, bool)
        return str(value) if is_num else value

    def fix(row, *keys):
        if isinstance(row, dict):
            for k in keys:
                if k in row:
                    row[k] = conv(row[k])

    def rows(key):
        value = graph.get(key)
        return value if isinstance(value, list) else []

    for g in rows("groups"):
        fix(g, "id")
    for s in rows("sessions"):
        fix(s, "id")
        if isinstance(s, dict) and isinstance(s.get("queue"), list):
            s["queue"] = [conv(q) for q in s["queue"]]
    for it in rows("items"):
        fix(it, "id", "group", "session")
        if isinstance(it, dict) and isinstance(it.get("deps"), list):
            for d in it["deps"]:
                fix(d, "id")
    for c in rows("conflicts"):
        fix(c, "a", "b")


def normalize_import(graph: dict) -> None:
    """Fill in what imported JSON may leave out, in place: stage names in
    items[].stage and deps[].stage become indexes, a missing version is the
    current one, a session `state` (no longer
    stored) is dropped. Values that do not resolve are left for validate()."""
    def stage(value):
        if isinstance(value, str):
            try:
                return parse_stage(graph, value)
            except GraphError:
                pass
        return value

    graph.setdefault("version", VERSION)
    for it in graph.get("items") or []:
        if not isinstance(it, dict):
            continue
        if "stage" in it:
            it["stage"] = stage(it["stage"])
        for d in it.get("deps") or []:
            if isinstance(d, dict) and d.get("stage") is not None:
                d["stage"] = stage(d["stage"])
    for s in graph.get("sessions") or []:
        if isinstance(s, dict):
            s.pop("state", None)


def history(graph: dict) -> list[dict]:
    """The well-formed entries of `history`, oldest first; a missing or hand-broken one is empty."""
    rows = graph.get("history")
    if not isinstance(rows, list):
        return []
    return [h for h in rows if isinstance(h, dict) and isinstance(h.get("msg"), str)]


def add_history(graph: dict, rev: int, at: str, msg: str) -> None:
    """Append one update to `history`, keeping the last HISTORY_MAX entries."""
    if len(msg) > HISTORY_MSG_MAX:
        msg = msg[:HISTORY_MSG_MAX - 1] + "…"
    rows = history(graph)
    rows.append({"rev": rev, "at": at, "msg": msg})
    graph["history"] = rows[-HISTORY_MAX:]


def history_lines(graph: dict, n: int) -> list[str]:
    rows = history(graph)[-n:]
    if not rows:
        return ["no history yet: it starts with the next change"]
    return ["rev %s  %s  %s" % (h.get("rev", "?"), str(h.get("at") or "").replace("T", " "),
                                h["msg"]) for h in rows]


def parse_stage(graph: dict, value: str) -> int:
    stages = graph.get("stages") or []
    v = str(value).strip()
    if v == "-" or v.lower() == "none":
        return -1
    for i, name in enumerate(stages):
        if name.casefold() == v.casefold():
            return i
    try:
        n = int(v)
    except ValueError:
        n = None
    if n is not None and 0 <= n < len(stages):
        return n
    raise GraphError("unknown stage '%s'; stages: %s (or a number 0-%d, or '-')"
                     % (value, ", ".join(stages), len(stages) - 1))


def parse_dep(graph: dict, spec: str) -> dict:
    rest = spec.strip()
    kind = None
    head, sep, tail = rest.rpartition(":")
    if sep:
        if tail != "part":
            raise GraphError("bad dependency '%s': only ':part' is allowed after ':'" % spec)
        kind = "part"
        rest = head
    iid, at, stage_text = rest.partition("@")
    if not iid:
        raise GraphError("bad dependency '%s': empty item id" % spec)
    dep: dict = {"id": iid}
    if at:
        dep["stage"] = parse_stage(graph, stage_text)
        if dep["stage"] < 0:
            raise GraphError("bad dependency '%s': dependency stage must be a real stage: %s"
                             % (spec, ", ".join(graph.get("stages") or [])))
    if kind:
        dep["kind"] = kind
    return dep


def _dep_met(by_id: dict, last: int, dep: dict) -> bool:
    target = by_id.get(dep.get("id"))
    if target is None:
        return False
    need = last if dep.get("stage") is None else dep["stage"]
    return target.get("status") == "done" or target.get("stage", -1) >= need


def item_states(graph: dict) -> dict[str, str]:
    items = [it for it in graph.get("items") or [] if it.get("id") is not None]
    by_id = {it["id"]: it for it in items}
    last = len(graph.get("stages") or []) - 1
    states: dict[str, str] = {}
    for it in items:
        status = it.get("status")
        if status in ("done", "wait-me", "doing", "review"):
            states[it["id"]] = status
            continue
        hard = [d for d in it.get("deps") or [] if d.get("kind") != "part"]
        met = all(_dep_met(by_id, last, d) for d in hard)
        states[it["id"]] = "ready" if met else "blocked"
    return states


def session_states(graph: dict) -> dict[str, str]:
    """A session's state follows its items (assigned by `session` or listed in its queue):
    any waiting on the user -> wait-me, any in progress -> doing, all done -> done,
    any in review -> review, otherwise (or no items) todo. A stored `state` field is ignored."""
    states = item_states(graph)
    result: dict[str, str] = {}
    for s in graph.get("sessions") or []:
        sid = s.get("id")
        mine = [it["id"] for it in graph.get("items") or []
                if it.get("id") is not None and it.get("session") == sid]
        mine += [q for q in s.get("queue") or [] if q in states and q not in mine]
        got = [states[i] for i in mine]
        if "wait-me" in got:
            state = "wait-me"
        elif "doing" in got:
            state = "doing"
        elif got and all(x == "done" for x in got):
            state = "done"
        elif "review" in got:
            state = "review"
        else:
            state = "todo"
        result[sid] = state
    return result


def _ids(ids: list[str]) -> str:
    shown = ids[:MAX_IDS_PER_LINE]
    text = ", ".join(shown)
    if len(ids) > len(shown):
        text += " (+%d more)" % (len(ids) - len(shown))
    return text


def summary_lines(graph: dict) -> list[str]:
    task = graph.get("task", {})
    lines = ["%s - %s (rev %s)" % (task.get("key"), task.get("title"), task.get("rev", 0))]
    items = [it for it in graph.get("items") or [] if it.get("id") is not None]
    if not items:
        lines.append("no items yet")
        return lines
    states = item_states(graph)
    lines.append("done %d/%d" % (sum(1 for s in states.values() if s == "done"), len(items)))
    order = [it["id"] for it in items]

    def with_state(name: str) -> list[str]:
        return [i for i in order if states[i] == name]

    for label, name in (("waiting on user", "wait-me"), ("in progress", "doing"),
                        ("in review", "review"), ("ready to start", "ready")):
        ids = with_state(name)
        if ids:
            lines.append("%s: %s" % (label, _ids(ids)))
    blocked = with_state("blocked")
    if blocked:
        by_id = {it["id"]: it for it in items}
        last = len(graph.get("stages") or []) - 1
        parts = []
        for bid in blocked[:MAX_IDS_PER_LINE]:
            missing = [d["id"] for d in by_id[bid].get("deps") or []
                       if d.get("kind") != "part" and not _dep_met(by_id, last, d)]
            parts.append("%s (needs %s)" % (bid, ", ".join(missing)))
        extra = len(blocked) - len(parts)
        lines.append("blocked: " + ", ".join(parts)
                     + (" (+%d more)" % extra if extra > 0 else ""))
    sessions = [s for s in graph.get("sessions") or [] if s.get("id") is not None]
    if sessions:
        ses_states = session_states(graph)
        lines.append("sessions: " + _ids(["%s %s" % (s.get("name") or s["id"], ses_states[s["id"]])
                                          for s in sessions]))
    return lines[:MAX_SUMMARY_LINES]
