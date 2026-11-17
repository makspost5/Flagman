"""Shared test helpers: sys.path setup and sample graphs."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugin" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from taskgraph import model  # noqa: E402


def make_graph(lang: str = "en") -> dict:
    """A valid 4-item graph: 1 done, 2 wait-me, 3 ready, 4 blocked."""
    g = model.new_graph("K-1", "Sample task", lang)
    g["groups"] = [{"id": "G", "title": "Group"}]
    g["sessions"] = [
        {"id": "01", "name": "01-a", "dir": "sessions/01-a", "state": "doing",
         "note": "", "queue": []},
        {"id": "02", "name": "02-x", "dir": "sessions/02-x", "state": "wait-me",
         "note": "", "queue": []},
    ]

    def item(iid: str, session: str, stage: int, status: str, deps: list) -> dict:
        return {"id": iid, "title": "Item " + iid, "group": "G", "session": session,
                "stage": stage, "status": status, "wait": "", "deps": deps,
                "summary": "", "details": [], "links": [], "files": []}

    two = item("2", "02", 1, "wait-me", [])
    two["wait"] = "decide"
    g["items"] = [
        item("1", "01", 5, "done", []),
        two,
        item("3", "01", -1, "todo", [{"id": "1", "note": ""}]),
        item("4", "02", -1, "todo", [{"id": "2", "stage": 2, "note": ""},
                                     {"id": "3", "kind": "part", "note": ""}]),
    ]
    return g


def make_task(tmp: Path, graph: dict) -> Path:
    """Write <tmp>/.tasks/K-1/taskgraph.js and return the task folder."""
    graph["task"]["key"] = "K-1"
    folder = Path(tmp) / ".tasks" / "K-1"
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "taskgraph.js", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(model.dump(graph))
    return folder


def find_bash() -> str:
    """Git Bash first (plain `bash` on Windows may be WSL), then PATH."""
    for cand in (r"C:\Program Files\Git\bin\bash.exe",
                 r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if Path(cand).exists():
            return cand
    return shutil.which("bash") or "bash"
