"""Tests for the fm command (taskgraph.cli) and its launchers."""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import helpers
from tests.helpers import find_bash, make_graph, make_task
from taskgraph import cli, model, store


def run(argv, cwd=None):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, cwd=cwd, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def task(self, lang="en"):
        self.folder = make_task(self.tmp, make_graph(lang))
        return str(self.folder)

    def graph(self):
        return store.load(self.folder)

    def item(self, iid):
        return next(i for i in self.graph()["items"] if i["id"] == iid)

    def raw(self):
        return (self.folder / "taskgraph.js").read_bytes()


class InitTests(CliTestCase):
    def test_init_then_show(self):
        folder = self.tmp / "T-9"
        folder.mkdir()
        code, out, err = run([str(folder), "init", "Demo", "lang=en", "due=2026-12-01",
                              "link=Doc|https://x/y"])
        self.assertEqual((code, err), (0, ""), out)
        self.assertTrue(out.startswith("ok:"))
        g = store.load(folder)
        self.assertEqual(g["stages"], model.DEFAULT_STAGES["en"])
        self.assertEqual(g["task"]["key"], "T-9")
        self.assertEqual(g["task"]["title"], "Demo")
        self.assertEqual(g["task"]["due"], "2026-12-01")
        self.assertEqual(g["task"]["links"], [{"label": "Doc", "href": "https://x/y"}])
        code, out, _ = run([str(folder), "show"])
        self.assertEqual(code, 0)
        self.assertIn("no items yet", out)

    def test_init_default_lang_is_en(self):
        for extra in ([], ["lang="], ["lang=${user_config.lang}"]):
            with self.subTest(extra=extra):
                folder = self.tmp / ("L-%d" % len(list(self.tmp.iterdir())))
                folder.mkdir()
                code, out, err = run([str(folder), "init", "T"] + extra)
                self.assertEqual((code, err), (0, ""), out)
                g = store.load(folder)
                self.assertEqual(g["lang"], "en")
                self.assertEqual(g["stages"], model.DEFAULT_STAGES["en"])

    def test_init_lang_ru_on_request(self):
        folder = self.tmp / "R-1"
        folder.mkdir()
        code, out, err = run([str(folder), "init", "T", "lang=ru"])
        self.assertEqual((code, err), (0, ""), out)
        g = store.load(folder)
        self.assertEqual((g["lang"], g["stages"]), ("ru", model.DEFAULT_STAGES["ru"]))

    def test_init_rejects_unknown_lang(self):
        folder = self.tmp / "X-1"
        folder.mkdir()
        code, _, err = run([str(folder), "init", "T", "lang=de"])
        self.assertEqual(code, 1)
        self.assertIn("unknown lang 'de'", err)
        self.assertFalse((folder / "taskgraph.js").exists())

    def test_show_empty_graph(self):
        folder = self.tmp / "T-8"
        folder.mkdir()
        run([str(folder), "init", "Empty"])
        code, out, _ = run([str(folder), "show"])
        self.assertEqual(code, 0)
        self.assertIn("no items yet", out)

    def test_init_refuses_existing_and_missing_folder(self):
        arg = self.task()
        before = self.raw()
        code, _, err = run([arg, "init", "Again"])
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("error:"))
        self.assertEqual(self.raw(), before)
        code, _, err = run([str(self.tmp / "nope"), "init", "X"])
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("error:"))


class EditTests(CliTestCase):
    def test_set_stage_status(self):
        arg = self.task()
        code, out, err = run([arg, "set", "3", "stage=code", "status=doing"])
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith("ok:"))
        for word in ("3", "code", "doing", "rev"):
            self.assertIn(word, out)
        self.assertEqual(out.count("\n"), 1)
        it = self.item("3")
        self.assertEqual((it["stage"], it["status"]), (1, "doing"))

    def test_set_done_rules(self):
        arg = self.task()
        run([arg, "set", "3", "status=done"])
        self.assertEqual(self.item("3")["stage"], 5)
        run([arg, "set", "2", "status=todo"])
        self.assertEqual(self.item("2")["wait"], "")
        # reset: item 2 back to wait-me, then status=doing clears wait
        run([arg, "set", "2", "status=wait-me", "wait=decide"])
        self.assertEqual(self.item("2")["wait"], "decide")
        run([arg, "set", "2", "status=doing"])
        self.assertEqual(self.item("2")["wait"], "")
        run([arg, "set", "4", "stage=done"])
        self.assertEqual(self.item("4")["status"], "done")
        run([arg, "set", "2", "status=wait-me", "wait=again"])
        run([arg, "set", "2", "stage=done"])
        it = self.item("2")
        self.assertEqual((it["status"], it["wait"]), ("done", ""))

    def test_set_status_review(self):
        arg = self.task()
        run([arg, "set", "2", "status=wait-me", "wait=decide"])
        code, out, err = run([arg, "set", "2", "status=review"])
        self.assertEqual((code, err), (0, ""))
        it = self.item("2")
        self.assertEqual((it["status"], it["wait"]), ("review", ""))

    def test_add_with_deps_and_lists(self):
        arg = self.task()
        code, out, err = run([arg, "add", "5", "New", "after=3,2@review:part",
                              "detail=a", "detail=b", "file=x.md",
                              "link=PR|https://x", "group=G", "session=01"])
        self.assertEqual((code, err), (0, ""), out)
        it = self.item("5")
        self.assertEqual(it["title"], "New")
        self.assertEqual(len(it["deps"]), 2)
        self.assertEqual(it["deps"][0]["id"], "3")
        self.assertEqual(it["deps"][1]["id"], "2")
        self.assertEqual(it["deps"][1]["stage"], 2)
        self.assertEqual(it["deps"][1]["kind"], "part")
        self.assertEqual(it["details"], ["a", "b"])
        self.assertEqual(it["files"], ["x.md"])
        self.assertEqual(it["links"], [{"label": "PR", "href": "https://x"}])
        self.assertEqual((it["stage"], it["status"]), (-1, "todo"))

    def test_rm_refused_when_referenced(self):
        arg = self.task()
        before = self.raw()
        code, _, err = run([arg, "rm", "1"])
        self.assertEqual(code, 1)
        self.assertIn("3", err)
        self.assertEqual(self.raw(), before)
        code, out, _ = run([arg, "rm", "4"])
        self.assertEqual(code, 0, out)
        self.assertEqual([i["id"] for i in self.graph()["items"]], ["1", "2", "3"])

    def test_dep_add_remove_note(self):
        arg = self.task()
        code, out, err = run([arg, "dep", "4", "+1", "-3", "note=why"])
        self.assertEqual((code, err), (0, ""), out)
        deps = self.item("4")["deps"]
        self.assertEqual([d["id"] for d in deps], ["2", "1"])
        self.assertEqual(deps[1]["note"], "why")

    def test_session_group_conflict(self):
        arg = self.task()
        code, _, err = run([arg, "session", "03", "name=03-n", "dir=sessions/03",
                            "queue=3,4"])
        self.assertEqual((code, err), (0, ""))
        s = next(x for x in self.graph()["sessions"] if x["id"] == "03")
        self.assertEqual(s["queue"], ["3", "4"])
        self.assertEqual(s["state"], "todo")
        code, _, err = run([arg, "session", "03", "state=doing", "note=hi"])
        self.assertEqual((code, err), (0, ""))
        s = next(x for x in self.graph()["sessions"] if x["id"] == "03")
        self.assertEqual((s["state"], s["note"], s["queue"]), ("doing", "hi", ["3", "4"]))
        code, _, err = run([arg, "group", "H", "title=Hh", "estimate=2d"])
        self.assertEqual((code, err), (0, ""))
        g = next(x for x in self.graph()["groups"] if x["id"] == "H")
        self.assertEqual((g["title"], g["estimate"]), ("Hh", "2d"))
        code, _, err = run([arg, "conflict", "3", "4", "same file"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.graph()["conflicts"],
                         [{"a": "3", "b": "4", "why": "same file"}])
        code, _, err = run([arg, "conflict", "3", "4", "-"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.graph()["conflicts"], [])

    def test_check(self):
        arg = self.task()
        code, out, _ = run([arg, "check"])
        self.assertEqual((code, out.strip()), (0, "ok"))


class ErrorTests(CliTestCase):
    def test_errors(self):
        arg = self.task()
        before = self.raw()
        code, out, err = run([arg, "set", "99", "stage=code"])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("error: unknown item", err)
        code, _, err = run([arg, "set", "3", "stage=nope"])
        self.assertEqual(code, 1)
        self.assertIn("plan, code, review", err)
        code, _, err = run([arg, "set", "3", "status=weird"])
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("error:"))
        code, _, err = run([arg, "frobnicate"])
        self.assertEqual(code, 2)
        self.assertIn("usage", err.lower())
        code, _, err = run([arg])
        self.assertEqual(code, 2)
        code, _, err = run([])
        self.assertEqual(code, 2)
        code, _, err = run([arg, "set", "3", "bogus=1"])
        self.assertEqual(code, 2)
        self.assertEqual(self.raw(), before)

    def test_unknown_task(self):
        code, _, err = run(["nope-task", "show"], cwd=str(self.tmp))
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("error:"))

    def test_root_option(self):
        self.task()
        code, out, _ = run(["--root", str(self.tmp / ".tasks"), "K-1", "show"],
                           cwd=str(self.tmp / "elsewhere"))
        self.assertEqual(code, 0, out)
        self.assertIn("K-1", out)


class ImportTests(CliTestCase):
    def test_import(self):
        arg = self.task()
        rev0 = self.graph()["task"]["rev"]
        new = model.new_graph("K-1", "Imported", "en")
        new["items"] = [{"id": "X", "title": "x", "group": None, "session": None,
                         "stage": -1, "status": "todo", "wait": "", "deps": [],
                         "summary": "", "details": [], "links": [], "files": []}]
        src = self.tmp / "in.json"
        src.write_text(json.dumps(new), encoding="utf-8")
        code, out, err = run([arg, "import", str(src)])
        self.assertEqual((code, err), (0, ""), out)
        g = self.graph()
        self.assertEqual([i["id"] for i in g["items"]], ["X"])
        self.assertGreater(g["task"]["rev"], rev0)
        before = self.raw()
        bad = self.tmp / "bad.json"
        bad.write_text("{nope", encoding="utf-8")
        code, _, err = run([arg, "import", str(bad)])
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("error:"))
        code, _, err = run([arg, "import", str(self.tmp / "missing.json")])
        self.assertEqual(code, 1)
        self.assertEqual(self.raw(), before)


class OpenTests(CliTestCase):
    def test_open_copies_page(self):
        self.task()
        code, out, err = run([str(self.folder), "open", "--no-browser"])
        self.assertEqual((code, err), (0, ""), out)
        page = self.folder / "taskgraph.html"
        template = helpers.ROOT / "plugin" / "page" / "taskgraph.html"
        self.assertEqual(page.read_bytes(), template.read_bytes())
        self.assertIn(str(page), out)


class ImportCreateTests(CliTestCase):
    def test_import_creates_graph_in_empty_folder(self):
        folder = self.tmp / "NEW-1"
        folder.mkdir()
        src = self.tmp / "in.json"
        src.write_text(json.dumps(model.new_graph("NEW-1", "Fresh", "en")),
                       encoding="utf-8")
        code, out, err = run([str(folder), "import", str(src)])
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(store.load(folder)["task"]["rev"], 1)
        self.assertEqual(store.load(folder)["task"]["title"], "Fresh")

    def test_import_into_missing_folder(self):
        src = self.tmp / "in.json"
        src.write_text(json.dumps(model.new_graph("N", "x", "en")), encoding="utf-8")
        code, _, err = run([str(self.tmp / "nope"), "import", str(src)])
        self.assertEqual(code, 1)
        self.assertIn("not found", err)
        self.assertFalse((self.tmp / "nope").exists())


class SessionDirTests(CliTestCase):
    def test_new_session_gets_default_dir(self):
        arg = self.task()
        run([arg, "session", "05", "name=api"])
        run([arg, "session", "06"])
        run([arg, "session", "07", "name=x", "dir=custom/x"])
        by_id = {s["id"]: s for s in self.graph()["sessions"]}
        self.assertEqual(by_id["05"]["dir"], "sessions/api")
        self.assertEqual(by_id["06"]["dir"], "sessions/06")
        self.assertEqual(by_id["07"]["dir"], "custom/x")
        run([arg, "session", "05", "name=renamed"])
        self.assertEqual(
            {s["id"]: s for s in self.graph()["sessions"]}["05"]["dir"],
            "sessions/api")


class IdAndStageTests(CliTestCase):
    def write(self, data):
        src = self.tmp / "in.json"
        src.write_text(json.dumps(data), encoding="utf-8")
        return str(src)

    def test_import_requires_stages(self):
        arg = self.task()
        before = self.raw()
        new = model.new_graph("K-1", "T", "en")
        del new["stages"]
        code, _, err = run([arg, "import", self.write(new)])
        self.assertEqual(code, 1)
        self.assertIn("stages", err)
        self.assertEqual(self.raw(), before)

    def test_import_converts_numeric_ids(self):
        arg = self.task()
        new = model.new_graph("K-1", "T", "en")
        new["groups"] = [{"id": 7, "title": "g"}]
        new["sessions"] = [{"id": 1, "name": "n", "dir": "sessions/n", "state": "todo",
                            "note": "", "queue": [1, 2]}]
        item = {"title": "x", "group": 7, "session": 1, "stage": -1, "status": "todo",
                "wait": "", "summary": "", "details": [], "links": [], "files": []}
        new["items"] = [dict(item, id=1, deps=[]),
                        dict(item, id=2, deps=[{"id": 1, "note": ""}])]
        new["conflicts"] = [{"a": 1, "b": 2, "why": "w"}]
        code, out, err = run([arg, "import", self.write(new)])
        self.assertEqual((code, err), (0, ""), out)
        g = self.graph()
        self.assertEqual([i["id"] for i in g["items"]], ["1", "2"])
        self.assertEqual(g["items"][1]["deps"][0]["id"], "1")
        self.assertEqual((g["items"][0]["group"], g["items"][0]["session"]), ("7", "1"))
        self.assertEqual(g["sessions"][0]["queue"], ["1", "2"])
        self.assertEqual((g["conflicts"][0]["a"], g["conflicts"][0]["b"]), ("1", "2"))
        code, out, err = run([arg, "set", "1", "status=doing"])
        self.assertEqual((code, err), (0, ""), out)


class RobustnessTests(CliTestCase):
    def test_hand_edited_file_gives_one_line_error(self):
        arg = self.task()
        g = make_graph()
        g["items"][2]["deps"] = ["1"]
        make_task(self.tmp, g)
        code, out, err = run([arg, "set", "3", "status=doing"])
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error:"), err)
        self.assertEqual(err.count(chr(10)), 1, err)

    def test_store_oserror_gives_one_line_error(self):
        arg = self.task()
        real = store.update

        def boom(*a, **k):
            raise OSError("disk is read-only")
        store.update = boom
        try:
            code, _, err = run([arg, "set", "3", "status=doing"])
        finally:
            store.update = real
        self.assertEqual(code, 1)
        self.assertIn("read-only", err)


class UnknownKeyTests(CliTestCase):
    def test_unknown_key_one_line(self):
        arg = self.task()
        before = self.raw()
        for args in (["set", "3", "stat=doing"],
                     ["set", "3", "status=doing", "note=x"]):
            code, out, err = run([arg] + args)
            self.assertEqual((code, out), (2, ""))
            self.assertTrue(err.startswith("error: unknown key '"), err)
            self.assertIn("for set (allowed: ", err)
            self.assertIn("status", err)
            self.assertEqual(err.count(chr(10)), 1, err)
            self.assertNotIn("usage", err.lower())
        self.assertEqual(self.raw(), before)

    def test_key_like_titles_still_work(self):
        arg = self.task()
        code, out, err = run([arg, "add", "5", "a=b"])
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.item("5")["title"], "a=b")
        code, out, err = run([arg, "add", "x=1", "Title"])
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.item("x=1")["title"], "Title")
        folder = self.tmp / "T-7"
        folder.mkdir()
        code, out, err = run([str(folder), "init", "a=b"])
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(store.load(folder)["task"]["title"], "a=b")


class LauncherTests(CliTestCase):
    def test_cli_bash_launcher_cyrillic(self):
        g = make_graph("ru")
        g["items"].append({"id": "Я1", "title": "Я", "group": "G", "session": "02",
                           "stage": -1, "status": "todo", "wait": "", "deps": [],
                           "summary": "", "details": [], "links": [], "files": []})
        self.folder = make_task(self.tmp, g)
        res = subprocess.run(
            [find_bash(), str(helpers.ROOT / "plugin" / "bin" / "fm"), str(self.folder),
             "set", "Я1", "stage=код", "status=wait-me", "wait=решить"],
            capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace"))
        text = res.stdout.decode("utf-8")
        self.assertIn("Я1", text)
        self.assertIn("код", text)
        self.assertIn('"wait": "решить"',
                      (self.folder / "taskgraph.js").read_text(encoding="utf-8"))

    def test_launcher_path_with_spaces(self):
        self.task()
        dst = self.tmp / "dir with space" / "plugin"
        shutil.copytree(helpers.ROOT / "plugin", dst)
        res = subprocess.run([find_bash(), str(dst / "bin" / "fm"), str(self.folder),
                              "show"], capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace"))
        self.assertIn("K-1", res.stdout.decode("utf-8"))

    def test_usage_names_fm(self):
        code, out, err = run([])
        self.assertIn("usage: fm ", out + err)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(__import__("os").name == "nt", "the .cmd launcher is for Windows")
class CmdLauncherTests(CliTestCase):
    """bin/fm.cmd: what PowerShell and cmd run for `fm` (an extensionless file would open the
    Windows "choose an app" dialog there)."""

    CMD = helpers.ROOT / "plugin" / "bin" / "fm.cmd"

    def _run_cmd(self, launcher, *args):
        return subprocess.run([str(launcher), *args], capture_output=True)

    def test_cmd_launcher_cyrillic_and_spaces(self):
        g = make_graph("ru")
        g["items"].append({"id": "Я1", "title": "x", "stage": -1, "status": "todo",
                           "session": "02"})
        folder = make_task(self.tmp, g)
        r = self._run_cmd(self.CMD, str(folder), "set", "Я1", "stage=код",
                          "status=wait-me", "wait=решить а=б")
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        self.assertIn("Я1", r.stdout.decode("utf-8"))
        item = next(i for i in store.load(folder)["items"] if i["id"] == "Я1")
        self.assertEqual((item["stage"], item["status"], item["wait"]), (1, "wait-me", "решить а=б"))

    def test_cmd_launcher_exit_code_and_path_with_spaces(self):
        dst = self.tmp / "dir with space" / "plugin"
        shutil.copytree(helpers.ROOT / "plugin", dst)
        self.task()
        r = self._run_cmd(dst / "bin" / "fm.cmd", str(self.folder), "show")
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        r = self._run_cmd(dst / "bin" / "fm.cmd", str(self.folder), "set", "nope", "status=doing")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown item", r.stderr.decode("utf-8"))

    def test_cmd_launcher_is_crlf(self):
        data = self.CMD.read_bytes()
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), self.CMD.name)
