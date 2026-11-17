"""Auto graph: notice that a task was split into many items and has no graph yet.

The hook calls this when a plan file is saved or the session's todo list grows. It never
builds a graph: it only tells the session to ask the user (auto_graph=ask) or to create one
with the flagman:graph skill (auto_graph=on). auto_graph=off keeps the hook silent.
"""
from __future__ import annotations

import fnmatch
import os
import re

MODES = ("off", "ask", "on")
DEFAULT_MODE = "ask"
DEFAULT_MIN = 6
MAX_BYTES = 1_000_000  # a bigger "plan" is not read
MODE_ENV = "CLAUDE_PLUGIN_OPTION_AUTO_GRAPH"
MIN_ENV = "CLAUDE_PLUGIN_OPTION_AUTO_GRAPH_MIN"

# "## 1. Title", "### Task 3: Title", "### Задача 2"; not "## 2026-11-17", not steps
_TASK_HEADING = re.compile(r"^#{2,4}\s+(?:(?:task|задача|этап)\s+)?\d+(?:[.:)]|\s|$)",
                           re.IGNORECASE)
# a list item without indent: "- x", "* x", "+ x", "1. x", "2) x", "- [ ] x"
_LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+\S")


def _setting(value: str | None, env: str) -> str:
    if value is None:
        value = os.environ.get(env, "")
    value = value.strip().lower()
    return "" if value.startswith("${user_config.") else value


def mode(value: str | None = None) -> str:
    """off, ask or on; anything else is the default (ask)."""
    v = _setting(value, MODE_ENV)
    return v if v in MODES else DEFAULT_MODE


def min_items(value: str | None = None) -> int:
    """How many items make a task big; below 2 or not a number is the default (6)."""
    try:
        n = int(_setting(value, MIN_ENV))
    except ValueError:
        return DEFAULT_MIN
    return n if n >= 2 else DEFAULT_MIN


def is_plan_file(path: str, watch: list[str]) -> bool:
    """A watched file, or a Markdown file with "plan" in its name or in a plans/ folder."""
    parts = path.replace("\\", "/").lower().split("/")
    name = parts[-1]
    if any(fnmatch.fnmatchcase(name, p) for p in watch):
        return True
    if not name.endswith(".md"):
        return False
    return "plan" in name or "plans" in parts[:-1]


def count_items(text: str) -> int:
    """Task headings if there are two or more, else list items without indent; code skipped."""
    headings = items = 0
    in_code = False
    for line in text.splitlines():
        if line.startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code:
            continue
        if _TASK_HEADING.match(line):
            headings += 1
        elif _LIST_ITEM.match(line):
            items += 1
    return headings if headings >= 2 else items


def reminder(mode: str, n: int, source: str, folder_hint: str, fm_cmd: str,
             nearby: list[str] | None = None) -> str:
    build = ("create the folder %s, then build the graph from the plan with %s import "
             "(or init and add)" % (folder_hint, fm_cmd))
    text = "This task is split into %d items (%s) and has no Flagman task graph yet. " % (n, source)
    if mode == "on":
        text += ("Create the task graph now with the flagman:graph skill: %s, "
                 "and tell the user in one line. " % build)
    else:
        text += ("Ask the user in one line whether to keep a task graph for it. If yes, "
                 "use the flagman:graph skill: %s. " % build)
    if nearby:
        text += ("Graphs that already exist nearby: %s. If this task is one of them, use it "
                 "instead of creating a new one. " % ", ".join(nearby))
    return text + "If the task already has a graph, ignore this."
