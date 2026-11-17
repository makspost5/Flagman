"""Auto graph: when a task is split into many items, the hook offers a graph (#40)."""
from __future__ import annotations

import json
import unittest

from tests import helpers  # noqa: F401  (puts plugin/scripts on sys.path)
from taskgraph import autograph


class SettingsTests(unittest.TestCase):
    def test_mode_defaults(self):
        self.assertEqual(autograph.mode(""), "ask")
        self.assertEqual(autograph.mode("${user_config.auto_graph}"), "ask")
        self.assertEqual(autograph.mode("ON"), "on")
        self.assertEqual(autograph.mode(" off "), "off")
        self.assertEqual(autograph.mode("maybe"), "ask")

    def test_min_items(self):
        self.assertEqual(autograph.min_items(""), 6)
        self.assertEqual(autograph.min_items("10"), 10)
        self.assertEqual(autograph.min_items("1"), 6)
        self.assertEqual(autograph.min_items("x"), 6)
        self.assertEqual(autograph.min_items("${user_config.auto_graph_min}"), 6)


class PlanFileTests(unittest.TestCase):
    def test_is_plan_file(self):
        w = ["status.md", "plan.md"]
        self.assertTrue(autograph.is_plan_file("/r/plan.md", w))
        self.assertTrue(autograph.is_plan_file("/r/docs/superpowers/plans/2026-11-17-x.md", w))
        self.assertTrue(autograph.is_plan_file("C:\\r\\Release-Plan.MD", w))
        self.assertTrue(autograph.is_plan_file("C:\\r\\plans\\x.md", w))
        self.assertTrue(autograph.is_plan_file("/r/PROGRESS.txt", ["progress.txt"]))
        self.assertFalse(autograph.is_plan_file("/r/README.md", w))
        self.assertFalse(autograph.is_plan_file("/r/planner.py", w))


class CountTests(unittest.TestCase):
    def test_count_list_items(self):
        text = "# T\n- a\n- b\n  - nested\n1. c\n2) d\n- [ ] e\n* f\ntext\n"
        self.assertEqual(autograph.count_items(text), 6)

    def test_count_task_headings_win_over_steps(self):
        text = "".join("### Task %d: x\n- [ ] **Step 1**\n- [ ] **Step 2**\n" % i
                       for i in range(1, 4))
        self.assertEqual(autograph.count_items(text), 3)
        self.assertEqual(autograph.count_items("## 1. a\n## 2. b\n### Задача 3\n"), 3)

    def test_count_skips_code_blocks(self):
        self.assertEqual(autograph.count_items("- a\n```\n- b\n- c\n```\n- d\n"), 2)
        self.assertEqual(autograph.count_items("~~~\n### Task 1\n~~~\n- a\n"), 1)

    def test_count_crlf(self):
        self.assertEqual(autograph.count_items("- a\r\n- b\r\n"), 2)


class ReminderTests(unittest.TestCase):
    def test_reminder_texts(self):
        ask = autograph.reminder("ask", 7, "plan.md", "/r/.tasks/<KEY>", "fm")
        on = autograph.reminder("on", 7, "plan.md", "/r/.tasks/<KEY>", "fm")
        for t in (ask, on):
            self.assertIn("7 items", t)
            self.assertIn("flagman:graph", t)
            self.assertIn("/r/.tasks/<KEY>", t)
            self.assertIn("already has a graph", t)
        self.assertIn("Ask the user", ask)
        self.assertNotIn("Ask the user", on)
        self.assertIn("Create the task graph now", on)


class PluginJsonTests(unittest.TestCase):
    def test_plugin_json_auto_graph_settings(self):
        path = helpers.ROOT / "plugin" / ".claude-plugin" / "plugin.json"
        config = json.loads(path.read_text(encoding="utf-8"))["userConfig"]
        self.assertEqual(config["auto_graph"]["default"], "ask")
        self.assertEqual(config["auto_graph_min"]["default"], "6")


if __name__ == "__main__":
    unittest.main()
