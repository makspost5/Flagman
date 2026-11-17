"""Tests for the reminder hook (taskgraph.hook and scripts/hook)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from tests import helpers
from taskgraph import autograph, hook

ROOT = helpers.ROOT
HOOK_PY = ROOT / "plugin" / "scripts" / "hook.py"
HOOK_SH = ROOT / "plugin" / "scripts" / "hook"
TG = "C:/x/plugin/bin/fm"


def py_cmd() -> list:
    return ["py", "-3"] if os.name == "nt" else [sys.executable]


class HookCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.task = helpers.make_task(self.tmp, helpers.make_graph())
        self.sess_dir = self.task / "sessions" / "02-x"
        self.sess_dir.mkdir(parents=True)
        self.sess_file = self.sess_dir / "status.md"
        self.sess_file.write_text("x", encoding="utf-8")
        self.root_file = self.task / "status.md"
        self.root_file.write_text("x", encoding="utf-8")
        self.state = self.tmp / "state"
        self.state.mkdir()
        # a watch_files setting of the Claude Code session running the tests must not leak in
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(hook.WATCH_ENV, None)
        for name in (autograph.MODE_ENV, autograph.MIN_ENV, hook.TASKS_DIR_ENV):
            os.environ.pop(name, None)

    def post(self, path, sid="s1"):
        return hook.handle_post_tool(
            {"session_id": sid, "tool_input": {"file_path": str(path)}},
            self.state, TG)


class PostToolTests(HookCase):
    def test_post_tool_ignores_other_files(self):
        other = self.task / "notes.md"
        other.write_text("x", encoding="utf-8")
        self.assertIsNone(self.post(other))
        self.assertEqual(list(self.state.iterdir()), [])

    def test_post_tool_no_graph(self):
        d = self.tmp / "plain"
        d.mkdir()
        f = d / "status.md"
        f.write_text("x", encoding="utf-8")
        self.assertIsNone(self.post(f))

    def test_post_tool_session_reminder(self):
        text = self.post(self.sess_file)
        self.assertTrue(text.startswith("Task graph K-1, session 02 items:"), text)
        self.assertIn("2 ", text)
        self.assertIn("4 ", text)
        self.assertIn("2 code/wait-me", text)
        self.assertIn("4 -/todo", text)
        self.assertIn(TG, text)
        # the hook prints the resolved folder (no 8.3 short names, no symlinks)
        task = str(self.task.resolve())
        self.assertIn(task, text)
        self.assertLessEqual(len(text), 600 + len(task))

    def test_post_tool_session_reminder_names_shortcuts(self):
        text = self.post(self.sess_file)
        for word in ("start|next|done <id>", 'ask <id> "', "status=review", "set <id>"):
            self.assertIn(word, text)

    def test_post_tool_once_per_prompt(self):
        self.assertIsNotNone(self.post(self.sess_file))
        self.assertIsNone(self.post(self.sess_file))
        hook.handle_prompt({"session_id": "s1"}, self.state)
        self.assertIsNotNone(self.post(self.sess_file))

    def test_prompt_only_clears_own_session(self):
        self.post(self.sess_file, "s1")
        self.post(self.sess_file, "s2")
        hook.handle_prompt({"session_id": "s1"}, self.state)
        self.assertIsNotNone(self.post(self.sess_file, "s1"))
        self.assertIsNone(self.post(self.sess_file, "s2"))

    def test_post_tool_root_uses_remembered_session(self):
        self.post(self.sess_file)
        hook.handle_prompt({"session_id": "s1"}, self.state)
        text = self.post(self.root_file)
        self.assertTrue(text.startswith("Task graph K-1, session 02 items:"), text)

    def test_post_tool_root_unknown_session_neutral(self):
        text = self.post(self.root_file, "fresh")
        self.assertTrue(text.startswith("Task graph K-1 exists."), text)
        self.assertNotIn("you are", text)
        self.assertIn(TG, text)

    def test_post_tool_items_capped(self):
        g = helpers.make_graph()
        base = g["items"][1]
        for i in range(10, 22):
            it = dict(base, id=str(i), status="todo", stage=-1, wait="")
            g["items"].append(it)
        helpers.make_task(self.tmp, g)
        text = self.post(self.sess_file)
        self.assertIn("+6 more", text)

    @unittest.skipUnless(os.name == "nt", "Windows path variants")
    def test_post_tool_windows_path_variants(self):
        p = str(self.sess_file)
        variants = (p.replace("\\", "/"), p[0].lower() + p[1:],
                    p[0].upper() + p[1:].replace("\\", "/"))
        for n, variant in enumerate(variants):
            state = self.tmp / ("wstate%d" % n)
            state.mkdir()
            text = hook.handle_post_tool(
                {"session_id": "w%d" % n, "tool_input": {"file_path": variant}},
                state, TG)
            self.assertTrue(text.startswith("Task graph K-1, session 02"), variant)

    def test_post_tool_session_through_symlink(self):
        # the task folder is reached through a link (macOS /var -> /private/var, a linked
        # projects folder): the session must still be found
        link = self.tmp / "linked"
        try:
            os.symlink(str(self.tmp / ".tasks"), str(link), target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("cannot create a symlink here: %s" % exc)
        text = self.post(link / "K-1" / "sessions" / "02-x" / "status.md")
        self.assertTrue(text.startswith("Task graph K-1, session 02 items:"), text)

    def test_post_tool_session_without_dir_uses_default(self):
        g = helpers.make_graph()
        g["sessions"][1]["dir"] = ""
        helpers.make_task(self.tmp, g)
        text = self.post(self.sess_file)
        self.assertTrue(text.startswith("Task graph K-1, session 02 items:"), text)
        # no name either: the folder is sessions/<id>
        g["sessions"][1].update(dir="", name="")
        helpers.make_task(self.tmp, g)
        other = self.task / "sessions" / "02" / "plan.md"
        other.parent.mkdir(parents=True)
        other.write_text("x", encoding="utf-8")
        text = self.post(other, "s9")
        self.assertTrue(text.startswith("Task graph K-1, session 02 items:"), text)

    def test_post_tool_broken_graph_silent(self):
        (self.task / "taskgraph.js").write_text("garbage", encoding="utf-8")
        self.assertIsNone(self.post(self.sess_file))


class MainTests(HookCase):
    def run_main(self, payload):
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(self.state),
                   PYTHONIOENCODING="utf-8")
        return subprocess.run(py_cmd() + [str(HOOK_PY), "post-tool"],
                              input=json.dumps(payload).encode("utf-8"),
                              capture_output=True, env=env)

    def test_main_outputs_json(self):
        r = self.run_main({"session_id": "m",
                           "tool_input": {"file_path": str(self.sess_file)}})
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.decode("utf-8"))
        h = out["hookSpecificOutput"]
        self.assertEqual(h["hookEventName"], "PostToolUse")
        self.assertIn("Task graph K-1", h["additionalContext"])
        if os.name == "nt":
            # plain `fm` on PATH: PowerShell runs bin/fm.cmd, Git Bash runs bin/fm; `bash` in
            # PowerShell is WSL, and an extensionless file opens the "choose an app" dialog
            self.assertIn(' set <id> ', h["additionalContext"])
            self.assertIn('run: fm "', h["additionalContext"])
            self.assertNotIn("bash ", h["additionalContext"])
        else:
            # run through bash: a checkout made on Windows has no exec bit on bin/fm
            fm_path = (ROOT / "plugin" / "bin" / "fm").as_posix()
            self.assertIn('bash "%s"' % fm_path, h["additionalContext"])
        other = self.task / "notes.md"
        r = self.run_main({"session_id": "m2",
                           "tool_input": {"file_path": str(other)}})
        self.assertEqual((r.returncode, r.stdout), (0, b""))

    def test_main_bad_stdin_logs_and_is_silent(self):
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(self.state))
        r = subprocess.run(py_cmd() + [str(HOOK_PY), "post-tool"],
                           input=b"not json", capture_output=True, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, b""))
        self.assertTrue((self.state / "hook-errors.log").exists())


class ScriptTests(HookCase):
    def run_sh(self, script, mode, payload, env_extra=None):
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(self.state))
        env.update(env_extra or {})
        return subprocess.run([helpers.find_bash(), Path(script).as_posix(), mode],
                              input=json.dumps(payload).encode("utf-8"),
                              capture_output=True, env=env)

    def test_hook_script_path_with_spaces(self):
        dst = self.tmp / "dir with space" / "plugin"
        shutil.copytree(ROOT / "plugin", dst)
        script = dst / "scripts" / "hook"
        r = self.run_sh(script, "post-tool",
                        {"session_id": "sp",
                         "tool_input": {"file_path": str(self.sess_file)}})
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.decode("utf-8"))
        self.assertIn("Task graph K-1", out["hookSpecificOutput"]["additionalContext"])
        r = self.run_sh(script, "post-tool",
                        {"session_id": "sp2",
                         "tool_input": {"file_path": str(self.task / "notes.md")}})
        self.assertEqual((r.returncode, r.stdout), (0, b""))

    def test_prompt_mode_silent_and_clears(self):
        self.post(self.sess_file, "pm")
        r = self.run_sh(HOOK_SH, "prompt", {"session_id": "pm", "prompt": "hi"})
        self.assertEqual((r.returncode, r.stdout), (0, b""))
        self.assertIsNotNone(self.post(self.sess_file, "pm"))

    def test_fast_path_does_not_start_python(self):
        # a fake python that would leave a marker; PATH puts it first
        fake = self.tmp / "fakebin"
        fake.mkdir()
        marker = self.tmp / "started"
        for name in ("py", "python3", "python"):
            helpers.write_script(fake / name,
                                 "#!/bin/bash\ntouch '%s'\nexit 1\n" % marker.as_posix())
        env_extra = {"PATH": fake.as_posix() + os.pathsep + os.environ["PATH"]}
        r = self.run_sh(HOOK_SH, "post-tool",
                        {"session_id": "f",
                         "tool_input": {"file_path": "/x/notes.md"}}, env_extra)
        self.assertEqual((r.returncode, r.stdout), (0, b""))
        self.assertFalse(marker.exists())

    def fake_python_env(self):
        fake = self.tmp / "fakebin2"
        fake.mkdir()
        for name in ("py", "python3", "python"):
            helpers.write_script(fake / name, "#!/bin/bash\nexit 1\n")
        return {"PATH": fake.as_posix() + os.pathsep + os.environ["PATH"]}

    def test_no_python_is_silent(self):
        env = self.fake_python_env()
        r = self.run_sh(HOOK_SH, "post-tool",
                        {"session_id": "n",
                         "tool_input": {"file_path": str(self.sess_file)}}, env)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
        r = self.run_sh(HOOK_SH, "prompt", {"session_id": "n"}, env)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))

    def test_prompt_removes_only_own_markers_without_python(self):
        self.post(self.sess_file, "pa")
        self.post(self.sess_file, "pb")
        self.assertEqual(len(list(self.state.glob("reminded-*"))), 2)
        r = self.run_sh(HOOK_SH, "prompt", {"session_id": "pa", "prompt": "x"},
                        self.fake_python_env())
        self.assertEqual((r.returncode, r.stdout), (0, b""))
        left = [f.name for f in self.state.glob("reminded-*")]
        self.assertEqual(len(left), 1)
        self.assertTrue(left[0].startswith("reminded-pb-"))

    def test_prompt_sanitizes_session_id_like_python(self):
        sid = "a b/c:d"
        self.post(self.sess_file, sid)
        names = [f.name for f in self.state.glob("reminded-*")]
        self.assertTrue(names[0].startswith("reminded-a_b_c_d-"), names)
        self.run_sh(HOOK_SH, "prompt", {"session_id": sid})
        self.assertEqual(list(self.state.glob("reminded-*")), [])

    def test_script_can_be_sourced(self):
        payload = json.dumps({"session_id": "src",
                              "tool_input": {"file_path": str(self.sess_file)}})
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(self.state))
        cmd = '. "%s" post-tool' % HOOK_SH.as_posix()
        r = subprocess.run([helpers.find_bash(), "-c", cmd],
                           input=payload.encode("utf-8"), capture_output=True,
                           env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.decode("utf-8"))
        self.assertIn("Task graph K-1", out["hookSpecificOutput"]["additionalContext"])
        r = subprocess.run([helpers.find_bash(), "-c",
                            '. "%s" prompt; echo after' % HOOK_SH.as_posix()],
                           input=b'{"session_id":"src"}', capture_output=True,
                           env=env)
        self.assertEqual((r.returncode, r.stdout), (0, b""))
        self.assertEqual(list(self.state.glob("reminded-*")), [])


def _dash() -> str | None:
    found = shutil.which("dash")
    if found:
        return found
    cand = r"C:\Program Files\Git\usr\bin\dash.exe"
    return cand if Path(cand).exists() else None


class ShellFormTests(HookCase):
    """The hooks.json command strings, run the way Claude Code runs them."""

    def commands(self):
        data = json.loads((ROOT / "plugin" / "hooks" / "hooks.json")
                          .read_text(encoding="utf-8"))
        post = data["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        prompt = data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        return post, prompt

    def run_shell(self, shell, command, payload):
        bash_dir = str(Path(helpers.find_bash()).parent)
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(self.state),
                   CLAUDE_PLUGIN_ROOT=(ROOT / "plugin").as_posix(),
                   PATH=bash_dir + os.pathsep + os.environ["PATH"])
        return subprocess.run([shell, "-c", command],
                              input=json.dumps(payload).encode("utf-8"),
                              capture_output=True, env=env)

    def check_shell(self, shell):
        post, prompt = self.commands()
        r = self.run_shell(shell, post, {
            "session_id": "sh", "tool_input": {"file_path": str(self.sess_file)}})
        self.assertEqual((r.returncode, r.stderr), (0, b""), r.stdout)
        out = json.loads(r.stdout.decode("utf-8"))
        self.assertIn("Task graph K-1",
                      out["hookSpecificOutput"]["additionalContext"])
        r = self.run_shell(shell, prompt, {"session_id": "sh", "prompt": "hi"})
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
        self.assertEqual(list(self.state.glob("reminded-*")), [])

    def test_hooks_json_under_bash(self):
        self.check_shell(helpers.find_bash())

    @unittest.skipIf(_dash() is None, "dash not available")
    def test_hooks_json_under_dash(self):
        self.check_shell(_dash())


class LargeInputTests(HookCase):
    """Big PostToolUse payloads (Edit's originalFile, Write's content) stay fast."""

    def run_sh(self, mode, raw):
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(self.state))
        start = time.monotonic()
        r = subprocess.run([helpers.find_bash(), HOOK_SH.as_posix(), mode],
                           input=raw, capture_output=True, env=env)
        return r, time.monotonic() - start

    def test_large_unrelated_edit_is_fast(self):
        raw = json.dumps({"session_id": "big", "tool_input": {
            "file_path": "/x/notes.md", "old_string": "a" * 1000000,
            "new_string": "b"}, "tool_response": {"originalFile": "c" * 1000000}}
        ).encode("utf-8")
        r, secs = self.run_sh("post-tool", raw)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
        self.assertLess(secs, 4, secs)

    def test_large_prompt_is_fast(self):
        self.post(self.sess_file, "bigp")
        raw = json.dumps({"session_id": "bigp", "prompt": "x" * 1000000}
                         ).encode("utf-8")
        r, secs = self.run_sh("prompt", raw)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
        self.assertLess(secs, 4, secs)
        self.assertEqual(list(self.state.glob("reminded-bigp-*")), [])

    def test_relevant_path_after_long_old_string(self):
        raw = json.dumps({"session_id": "late", "tool_input": {
            "old_string": "a" * 200000, "new_string": "b",
            "file_path": str(self.sess_file)}}).encode("utf-8")
        r, secs = self.run_sh("post-tool", raw)
        self.assertEqual((r.returncode, r.stderr), (0, b""), r.stdout)
        out = json.loads(r.stdout.decode("utf-8"))
        self.assertIn("Task graph K-1",
                      out["hookSpecificOutput"]["additionalContext"])
        self.assertLess(secs, 4, secs)

    def test_relevant_path_first_with_big_content(self):
        raw = json.dumps({"session_id": "first", "tool_input": {
            "file_path": str(self.sess_file), "content": "z" * 300000}}
        ).encode("utf-8")
        r, secs = self.run_sh("post-tool", raw)
        self.assertEqual((r.returncode, r.stderr), (0, b""), r.stdout)
        self.assertIn("Task graph K-1", r.stdout.decode("utf-8"))
        self.assertLess(secs, 4, secs)


class FilterTests(HookCase):
    def fake_env(self):
        fake = self.tmp / "fakebin3"
        fake.mkdir()
        self.started = self.tmp / "started3"
        self.rm_called = self.tmp / "rm3"
        for name in ("py", "python3", "python"):
            helpers.write_script(
                fake / name, "#!/bin/bash\ntouch '%s'\nexit 1\n" % self.started.as_posix())
        # a function shadows the external rm (BASH_ENV is read by non-interactive bash)
        rc = self.tmp / "bashenv"
        helpers.write_script(rc, "rm() { touch '%s'; command rm \"$@\"; }\n"
                             % self.rm_called.as_posix())
        return dict(os.environ, CLAUDE_PLUGIN_DATA=str(self.state),
                    BASH_ENV=rc.as_posix(), PATH=fake.as_posix() + os.pathsep + os.environ["PATH"])

    def run_hook(self, mode, payload, env):
        return subprocess.run([helpers.find_bash(), HOOK_SH.as_posix(), mode],
                              input=json.dumps(payload).encode("utf-8"),
                              capture_output=True, env=env)

    def test_impl_plan_md_takes_fast_path(self):
        env = self.fake_env()
        env[autograph.MODE_ENV] = "off"  # with auto graph on, a *plan*.md goes to Python
        for name in ("impl-plan.md", "my-status.md"):
            r = self.run_hook("post-tool", {"session_id": "f", "tool_input": {
                "file_path": "/x/" + name}}, env)
            self.assertEqual((r.returncode, r.stdout), (0, b""))
        self.assertFalse(self.started.exists())
        for path in ("/x/plan.md", "C:" + chr(92) + "x" + chr(92) + "status.md"):
            self.run_hook("post-tool", {"session_id": "f", "tool_input": {
                "file_path": path}}, env)
            self.assertTrue(self.started.exists(), path)
            self.started.unlink()

    def test_prompt_forks_rm_only_when_markers_exist(self):
        env = self.fake_env()
        r = self.run_hook("prompt", {"session_id": "nomark"}, env)
        self.assertEqual((r.returncode, r.stdout), (0, b""))
        self.assertFalse(self.rm_called.exists())
        (self.state / "reminded-nomark-abcd1234").write_text("", encoding="utf-8")
        self.run_hook("prompt", {"session_id": "nomark"}, env)
        self.assertTrue(self.rm_called.exists())


class WatchFilesTests(HookCase):
    def test_patterns(self):
        default = ["status.md", "plan.md"]
        for value in ("", " ", ",", " , ", "${user_config.watch_files}"):
            with self.subTest(value=value):
                self.assertEqual(hook.watch_patterns(value), default)
        self.assertEqual(hook.watch_patterns(" PROGRESS.md , *.status.md,"),
                         ["progress.md", "*.status.md"])
        self.assertEqual(hook.watch_patterns(), default)
        os.environ[hook.WATCH_ENV] = "notes.md"
        self.assertEqual(hook.watch_patterns(), ["notes.md"])

    def test_is_watched(self):
        pats = hook.watch_patterns("PROGRESS.md,*.status.md")
        for path in ("/x/PROGRESS.md", "/x/progress.md", "C:" + chr(92) + "x" + chr(92) + "Progress.MD",
                     "/x/api.status.md"):
            with self.subTest(path=path):
                self.assertTrue(hook.is_watched(path, pats))
        for path in ("/x/status.md", "/x/plan.md", "/x/PROGRESS.md.bak", "/PROGRESS.md/x.txt"):
            with self.subTest(path=path):
                self.assertFalse(hook.is_watched(path, pats))

    def test_custom_name_reminds(self):
        progress = self.sess_dir / "PROGRESS.md"
        progress.write_text("x", encoding="utf-8")
        self.assertIsNone(self.post(progress))
        os.environ[hook.WATCH_ENV] = "PROGRESS.md"
        text = self.post(progress, "s2")
        self.assertTrue(text.startswith("Task graph K-1, session 02 items:"), text)
        self.assertIsNone(self.post(self.sess_file, "s3"))


class WatchFilesScriptTests(HookCase):
    def run_hook(self, path, watch=None, sid="w"):
        fake = self.tmp / "fakebin-w"
        fake.mkdir(exist_ok=True)
        self.started = self.tmp / "started-w"
        for name in ("py", "python3", "python"):
            helpers.write_script(
                fake / name, "#!/bin/bash\ntouch '%s'\nexit 1\n" % self.started.as_posix())
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(self.state),
                   PATH=fake.as_posix() + os.pathsep + os.environ["PATH"])
        if watch is not None:
            env[hook.WATCH_ENV] = watch
        env[autograph.MODE_ENV] = "off"  # only watch_files decides here
        r = subprocess.run([helpers.find_bash(), HOOK_SH.as_posix(), "post-tool"],
                           input=json.dumps({"session_id": sid,
                                             "tool_input": {"file_path": path}}).encode("utf-8"),
                           capture_output=True, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, b""))
        hit = self.started.exists()
        if hit:
            self.started.unlink()
        return hit

    def test_prefilter_follows_setting(self):
        win = "C:" + chr(92) + "x" + chr(92)
        cases = [
            (None, "/x/status.md", True), (None, "/x/plan.md", True),
            (None, "/x/PROGRESS.md", False), (None, "/x/my-status.md", False),
            ("", "/x/plan.md", True), (" , ", "/x/status.md", True),
            ("PROGRESS.md", "/x/PROGRESS.md", True), ("PROGRESS.md", "/x/progress.md", True),
            ("PROGRESS.md", win + "PROGRESS.md", True), ("PROGRESS.md", "/x/status.md", False),
            ("notes.md, *.status.md", "/x/api.status.md", True),
            ("notes.md, *.status.md", "/x/NOTES.md", True),
            ("notes.md, *.status.md", "/x/plan.md", False),
            ("${user_config.watch_files}", "/x/plan.md", True),
        ]
        for watch, path, expected in cases:
            with self.subTest(watch=watch, path=path):
                self.assertEqual(self.run_hook(path, watch), expected)

    def test_end_to_end_custom_name(self):
        progress = self.sess_dir / "PROGRESS.md"
        progress.write_text("x", encoding="utf-8")
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(self.state))
        env[hook.WATCH_ENV] = "PROGRESS.md"
        r = subprocess.run([helpers.find_bash(), HOOK_SH.as_posix(), "post-tool"],
                           input=json.dumps({"session_id": "e2e", "tool_input": {
                               "file_path": str(progress)}}).encode("utf-8"),
                           capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.decode("utf-8"))
        self.assertIn("session 02", out["hookSpecificOutput"]["additionalContext"])


class AutoGraphTests(HookCase):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()

    def plan(self, rel, n, fmt="- item %d\n"):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Plan\n" + "".join(fmt % i for i in range(1, n + 1)), encoding="utf-8")
        return path

    def auto(self, payload, mode="ask", n=6, sid="s1"):
        payload = dict(payload)
        payload.setdefault("session_id", sid)
        payload.setdefault("cwd", str(self.repo))
        return hook.handle_post_tool(payload, self.state, TG, auto=mode, auto_min=n)

    def edit(self, path, **kw):
        return self.auto({"tool_name": "Write", "tool_input": {"file_path": str(path)}}, **kw)

    def test_plan_file_without_graph_reminds_once(self):
        path = self.plan("plan.md", 6)
        text = self.edit(path)
        self.assertIn("6 items", text)
        self.assertIn("Ask the user", text)
        self.assertIn("plan.md", text)
        self.assertIsNone(self.edit(path))
        hook.handle_prompt({"session_id": "s1"}, self.state)
        self.assertIsNone(self.edit(path))
        self.assertIsNotNone(self.edit(path, sid="s2"))

    def test_below_threshold_silent(self):
        self.assertIsNone(self.edit(self.plan("plan.md", 5)))

    def test_off_silent(self):
        self.assertIsNone(self.edit(self.plan("plan.md", 9), mode="off"))

    def test_on_mode_text(self):
        self.assertIn("Create the task graph now", self.edit(self.plan("plan.md", 6), mode="on"))

    def test_superpowers_plan_path(self):
        path = self.plan("docs/superpowers/plans/2026-11-17-x.md", 6,
                         "### Task %d: x\n- [ ] **Step 1**\n")
        self.assertIn("6 items", self.edit(path))

    def test_other_markdown_silent(self):
        self.assertIsNone(self.edit(self.plan("README.md", 9)))

    def test_plan_in_graph_folder_gets_update_reminder(self):
        path = self.task / "plan.md"
        path.write_text("".join("- %d\n" % i for i in range(9)), encoding="utf-8")
        text = self.auto({"tool_name": "Write", "tool_input": {"file_path": str(path)}},
                         n=6)
        self.assertIn("Task graph K-1", text)
        self.assertNotIn("no Flagman task graph", text)

    def test_todowrite_counts_todos(self):
        todo = {"tool_name": "TodoWrite", "tool_input": {"todos": [{"content": "x"}] * 5}}
        self.assertIsNone(self.auto(todo))
        todo["tool_input"] = {"todos": [{"content": "x"}] * 6}
        self.assertIn("todo list", self.auto(todo))

    def test_taskcreate_counts_per_session(self):
        made = {"tool_name": "TaskCreate", "tool_input": {"subject": "x"}}
        out = [self.auto(made, sid="a") for _ in range(6)]
        self.assertEqual([o is None for o in out], [True] * 5 + [False])
        self.assertTrue(all(self.auto(made, sid="b") is None for _ in range(5)))

    def test_cwd_inside_task_folder_silent(self):
        todo = {"tool_name": "TodoWrite", "cwd": str(self.task),
                "tool_input": {"todos": [{}] * 9}}
        self.assertIsNone(self.auto(todo))

    def test_unreadable_plan_silent(self):
        self.assertIsNone(self.edit(self.repo / "plan.md"))

    def test_huge_plan_silent(self):
        path = self.repo / "plan.md"
        path.write_text("- x\n" * (autograph.MAX_BYTES // 4 + 10), encoding="utf-8")
        self.assertIsNone(self.edit(path))

    def test_folder_hint(self):
        text = self.edit(self.plan("plan.md", 6))
        self.assertIn(self.repo.resolve().as_posix() + "/.tasks/<KEY>", text)
        os.environ[hook.TASKS_DIR_ENV] = str(self.tmp / "T")
        text = self.edit(self.plan("plan.md", 6), sid="s9")
        self.assertIn((self.tmp / "T").resolve().as_posix() + "/<KEY>", text)

    def test_settings_from_env(self):
        os.environ[autograph.MODE_ENV] = "off"
        path = self.plan("plan.md", 9)
        payload = {"session_id": "e", "cwd": str(self.repo), "tool_name": "Write",
                   "tool_input": {"file_path": str(path)}}
        self.assertIsNone(hook.handle_post_tool(payload, self.state, TG))
        os.environ[autograph.MODE_ENV] = "on"
        os.environ[autograph.MIN_ENV] = "10"
        self.assertIsNone(hook.handle_post_tool(payload, self.state, TG))
        os.environ[autograph.MIN_ENV] = "9"
        self.assertIn("now", hook.handle_post_tool(payload, self.state, TG))

    def test_hooks_json_matcher(self):
        data = json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(data["hooks"]["PostToolUse"][0]["matcher"],
                         "Edit|Write|MultiEdit|TodoWrite|TaskCreate")


class AutoGraphScriptTests(FilterTests):
    def started_for(self, payload, mode=None):
        if not hasattr(self, "_env"):
            self._env = self.fake_env()
        env = dict(self._env)
        if mode is not None:
            env[autograph.MODE_ENV] = mode
        r = self.run_hook("post-tool", dict(payload, session_id="g"), env)
        self.assertEqual((r.returncode, r.stdout), (0, b""))
        return self.started.exists()

    def edit(self, path):
        return {"tool_name": "Write", "tool_input": {"file_path": path}}

    def test_prefilter_passes_plans_folder(self):
        self.assertTrue(self.started_for(self.edit("/r/docs/superpowers/plans/2026-x.md")))

    def test_prefilter_passes_plans_folder_windows(self):
        bs = chr(92)
        self.assertTrue(self.started_for(self.edit("C:" + bs + "r" + bs + "Plans" + bs + "x.md")))

    def test_prefilter_passes_named_plan(self):
        self.assertTrue(self.started_for(self.edit("/r/Release-Plan.MD")))

    def test_prefilter_off_keeps_fast_path(self):
        self.assertFalse(self.started_for(self.edit("/r/docs/plans/x.md"), mode="off"))

    def test_prefilter_unsubstituted_setting_is_ask(self):
        self.assertTrue(self.started_for(self.edit("/r/plans/x.md"),
                                         mode="${user_config.auto_graph}"))

    def test_prefilter_todo_tools(self):
        for tool in ("TodoWrite", "TaskCreate"):
            self.assertTrue(self.started_for({"tool_name": tool, "tool_input": {}}), tool)
            self.started.unlink()
            self.assertFalse(self.started_for({"tool_name": tool, "tool_input": {}}, "off"))

    def test_prefilter_readme_fast_path(self):
        self.assertFalse(self.started_for(self.edit("/r/README.md")))
        self.assertFalse(self.started_for(self.edit("/r/plans.py")))
        self.assertFalse(self.started_for(self.edit("/r/planning/README.md")))


class AutoGraphEndToEndTests(HookCase):
    def test_end_to_end_plan_reminds(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        plan = repo / "plan.md"
        plan.write_text("".join("- step %d" % i + chr(10) for i in range(6)), encoding="utf-8")
        payload = {"session_id": "e2e", "cwd": str(repo), "tool_name": "Write",
                   "tool_input": {"file_path": str(plan)}}
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(self.state))
        r = subprocess.run([helpers.find_bash(), HOOK_SH.as_posix(), "post-tool"],
                           input=json.dumps(payload).encode("utf-8"), capture_output=True,
                           env=env)
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout.decode("utf-8"))
        self.assertIn("6 items", out["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":
    unittest.main()
