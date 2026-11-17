from __future__ import annotations

import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import make_graph, make_task
from taskgraph import model, store
from taskgraph.model import GraphError


def _worker(folder: str, tag: str, count: int) -> None:
    """Module-level so that spawned processes can import it."""
    for n in range(count):
        def change(graph: dict, n: int = n) -> str:
            item = [i for i in graph["items"] if i["id"] == "1"][0]
            item["details"].append("%s-%d" % (tag, n))
            return "ok"
        store.update(Path(folder), change)


def _noop(graph: dict) -> str:
    return "noop"


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()

    def task(self) -> Path:
        return make_task(self.tmp, make_graph())

    def test_resolve_by_path_and_key(self):
        folder = self.task()
        self.assertEqual(store.resolve_task(str(folder), str(self.tmp)), folder)
        sub = self.tmp / "proj" / "sub"
        sub.mkdir(parents=True)
        self.assertEqual(store.resolve_task("K-1", str(sub)), folder)
        deep = folder / "worktrees" / "x"
        deep.mkdir(parents=True)
        self.assertEqual(store.resolve_task("K-1", str(deep)), folder)
        other = self.tmp / "elsewhere"
        other.mkdir()
        # an unrelated cwd is not under tmp/.tasks; use a separate tree
        with tempfile.TemporaryDirectory() as unrelated:
            self.assertEqual(
                store.resolve_task("K-1", unrelated, root=str(self.tmp / ".tasks")),
                folder)
            with self.assertRaises(GraphError) as cm:
                store.resolve_task("K-1", unrelated, root="${user_config.tasks_dir}")
            self.assertIn("task K-1 not found", str(cm.exception))
            with self.assertRaises(GraphError):
                store.resolve_task("K-1", unrelated)

    def test_resolve_need_graph(self):
        empty = self.tmp / ".tasks" / "K-2"
        empty.mkdir(parents=True)
        with self.assertRaises(GraphError):
            store.resolve_task(str(empty), str(self.tmp))
        self.assertEqual(
            store.resolve_task(str(empty), str(self.tmp), need_graph=False), empty)

    def test_find_graph_upwards(self):
        folder = self.task()
        f = folder / "sessions" / "02-x" / "status.md"
        f.parent.mkdir(parents=True)
        f.write_text("x", encoding="utf-8")
        self.assertEqual(store.find_graph_upwards(str(f)), folder)
        with tempfile.TemporaryDirectory() as unrelated:
            p = Path(unrelated) / "a.txt"
            p.write_text("x", encoding="utf-8")
            self.assertIsNone(store.find_graph_upwards(str(p)))

    def test_update_bumps_rev_and_time(self):
        folder = self.task()
        g1, msg = store.update(folder, _noop)
        self.assertEqual(msg, "noop")
        self.assertEqual(g1["task"]["rev"], 1)
        g2, _ = store.update(folder, _noop)
        self.assertEqual(g2["task"]["rev"], 2)
        self.assertRegex(g2["task"]["updated"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d$")
        self.assertEqual(store.load(folder)["task"]["rev"], 2)

    def test_update_create(self):
        folder = self.tmp / ".tasks" / "N-1"
        folder.mkdir(parents=True)
        with self.assertRaises(GraphError):
            store.update(folder, _noop)
        g, _ = store.update(folder, _noop, create=model.new_graph("N-1", "T"))
        self.assertEqual(g["task"]["rev"], 1)
        self.assertTrue((folder / store.FILE).exists())

    def test_update_refuses_invalid(self):
        folder = self.task()
        path = folder / store.FILE
        before = path.read_bytes()

        def bad(graph: dict) -> str:
            graph["items"][2]["deps"].append({"id": "nope"})
            return "x"

        with self.assertRaises(GraphError) as cm:
            store.update(folder, bad)
        self.assertIn("unknown item 'nope'", str(cm.exception))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(store.load(folder)["task"]["rev"], 0)

    def test_update_refuses_broken_file(self):
        folder = self.task()
        path = folder / store.FILE
        path.write_text("garbage", encoding="utf-8")
        with self.assertRaises(GraphError) as cm:
            store.update(folder, _noop)
        self.assertIn("not a taskgraph file", str(cm.exception))
        self.assertEqual(path.read_text(encoding="utf-8"), "garbage")

    def test_parallel_updates_not_lost(self):
        folder = self.task()
        initial = store.load(folder)["task"]["rev"]
        ctx = multiprocessing.get_context("spawn")
        procs = [ctx.Process(target=_worker, args=(str(folder), t, 20))
                 for t in ("a", "b")]
        for p in procs:
            p.start()
        for p in procs:
            p.join(120)
            self.assertEqual(p.exitcode, 0)
        g = store.load(folder)
        item = [i for i in g["items"] if i["id"] == "1"][0]
        self.assertEqual(len(item["details"]), 40)
        self.assertEqual(len(set(item["details"])), 40)
        self.assertEqual(g["task"]["rev"], initial + 40)
        self.assertFalse((folder / (store.FILE + ".lock")).exists())

    def test_stale_lock_removed(self):
        folder = self.task()
        lock = folder / (store.FILE + ".lock")
        lock.write_text("", encoding="utf-8")
        old = time.time() - 60
        os.utime(lock, (old, old))
        store.update(folder, _noop)
        self.assertFalse(lock.exists())

    def test_fresh_lock_times_out(self):
        folder = self.task()
        lock = folder / (store.FILE + ".lock")
        lock.write_text("", encoding="utf-8")
        with mock.patch.object(store, "LOCK_TIMEOUT", 0.2), \
                mock.patch.object(store, "LOCK_RETRY", 0.02):
            with self.assertRaises(GraphError) as cm:
                store.update(folder, _noop)
        self.assertIn("locked", str(cm.exception))
        self.assertTrue(lock.exists())

    def test_replace_retries_permission_error(self):
        folder = self.task()
        real = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError("held open")
            return real(src, dst)

        with mock.patch.object(store, "REPLACE_RETRY", 0.001), \
                mock.patch.object(store.os, "replace", flaky):
            g, _ = store.update(folder, _noop)
        self.assertEqual(g["task"]["rev"], 1)
        self.assertEqual(calls["n"], 3)

        path = folder / store.FILE
        before = path.read_bytes()

        def always(src, dst):
            raise PermissionError("held open")

        with mock.patch.object(store, "REPLACE_RETRY", 0.001), \
                mock.patch.object(store.os, "replace", always):
            with self.assertRaises(GraphError):
                store.update(folder, _noop)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual([p.name for p in folder.glob("*.tmp-*")], [])
        self.assertFalse((folder / (store.FILE + ".lock")).exists())


if __name__ == "__main__":
    unittest.main()
