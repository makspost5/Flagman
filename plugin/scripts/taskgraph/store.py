"""Finding the task folder, locking, atomic update of taskgraph.js."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from . import model
from .model import GraphError

FILE = "taskgraph.js"
LOCK_SUFFIX = ".lock"

LOCK_TIMEOUT = 5.0     # seconds to wait for the lock
LOCK_RETRY = 0.05      # pause between lock attempts
LOCK_STALE = 30.0      # a lock older than this is removed
REPLACE_ATTEMPTS = 20  # os.replace tries (the browser may hold the file open)
REPLACE_RETRY = 0.05


def _has_graph(folder: Path) -> bool:
    return (folder / FILE).is_file()


def resolve_task(arg: str, cwd: str, root: str | None = None,
                 need_graph: bool = True) -> Path:
    candidates: list[Path] = []
    direct = Path(arg)
    if direct.is_dir():
        candidates.append(direct)
    start = Path(cwd).resolve()
    for anc in [start, *start.parents]:
        if anc.name == arg:
            candidates.append(anc)
        under = anc / ".tasks" / arg
        if under.is_dir():
            candidates.append(under)
    if root and not root.startswith("${user_config."):
        candidates.append(Path(root) / arg)
    for cand in candidates:
        if not cand.is_dir():
            continue
        if need_graph and not _has_graph(cand):
            continue
        return cand
    raise GraphError("task %s not found; pass the task folder path or --root" % arg)


def find_graph_upwards(path: str, max_up: int = 8) -> Path | None:
    p = Path(path).resolve()
    cur = p if p.is_dir() else p.parent
    for _ in range(max_up + 1):
        if _has_graph(cur):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def load(folder: Path) -> dict:
    path = Path(folder) / FILE
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
    except OSError as exc:
        raise GraphError("cannot read %s: %s" % (path, exc)) from None
    return model.parse(text)


def _acquire(lock: Path) -> None:
    deadline = time.monotonic() + LOCK_TIMEOUT
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except FileExistsError:
            pass
        except PermissionError:
            pass  # on Windows a lock being deleted reports this; retry
        try:
            if time.time() - lock.stat().st_mtime > LOCK_STALE:
                lock.unlink()
                continue
        except OSError:
            pass  # vanished (or unreadable) meanwhile: retry after the check below
        if time.monotonic() >= deadline:
            raise GraphError("%s is locked by another process; try again" % lock.name)
        time.sleep(LOCK_RETRY)


def _release(lock: Path) -> None:
    try:
        lock.unlink()
    except OSError:
        pass


def _write(path: Path, text: str) -> None:
    tmp = path.with_name("%s.tmp-%d" % (path.name, os.getpid()))
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(str(tmp), str(path))
                return
            except PermissionError as exc:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise GraphError("cannot replace %s (file in use?): %s"
                                     % (path.name, exc)) from None
                time.sleep(REPLACE_RETRY)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def update(folder: Path, change: Callable[[dict], str],
           create: dict | None = None) -> tuple[dict, str]:
    folder = Path(folder)
    path = folder / FILE
    lock = folder / (FILE + LOCK_SUFFIX)
    _acquire(lock)
    try:
        if path.exists():
            graph = load(folder)
        elif create is not None:
            graph = create
        else:
            raise GraphError("no %s in %s" % (FILE, folder))
        msg = change(graph)
        problems = model.validate(graph)
        if problems:
            raise GraphError("; ".join(problems))
        task = graph.setdefault("task", {})
        task["rev"] = int(task.get("rev") or 0) + 1
        task["updated"] = time.strftime("%Y-%m-%dT%H:%M")
        _write(path, model.dump(graph))
        return graph, msg
    finally:
        _release(lock)
