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
from pathlib import Path

from tests import helpers
from taskgraph import hook

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
        self.assertIn(str(self.task), text)
        self.assertLessEqual(len(text), 600 + len(str(self.task)))

    def test_post_tool_session_reminder_lists_review(self):
        self.assertIn("todo|doing|wait-me|review|done", self.post(self.sess_file))

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
            f = fake / name
            f.write_text("#!/bin/bash\ntouch '%s'\nexit 1\n" % marker.as_posix(),
                         encoding="utf-8", newline="\n")
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
            (fake / name).write_text("#!/bin/bash\nexit 1\n", encoding="utf-8",
                                     newline="\n")
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
            (fake / name).write_text(
                "#!/bin/bash\ntouch '%s'\nexit 1\n" % self.started.as_posix(),
                encoding="utf-8", newline="\n")
        # a function shadows the external rm (BASH_ENV is read by non-interactive bash)
        rc = self.tmp / "bashenv"
        rc.write_text("rm() { touch '%s'; command rm \"$@\"; }\n"
                      % self.rm_called.as_posix(), encoding="utf-8", newline="\n")
        return dict(os.environ, CLAUDE_PLUGIN_DATA=str(self.state),
                    BASH_ENV=rc.as_posix(), PATH=fake.as_posix() + os.pathsep + os.environ["PATH"])

    def run_hook(self, mode, payload, env):
        return subprocess.run([helpers.find_bash(), HOOK_SH.as_posix(), mode],
                              input=json.dumps(payload).encode("utf-8"),
                              capture_output=True, env=env)

    def test_impl_plan_md_takes_fast_path(self):
        env = self.fake_env()
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


if __name__ == "__main__":
    unittest.main()
