from __future__ import annotations

import copy
import subprocess
import unittest

from tests.helpers import ROOT, find_bash, make_graph
from taskgraph import model
from taskgraph.model import GraphError


class ModelTests(unittest.TestCase):
    def test_dump_parse_roundtrip(self):
        g = make_graph()
        g["items"][0]["title"] = "Я1"
        text = model.dump(g)
        self.assertIn("Я1", text)
        self.assertNotIn("\\u042f", text)
        self.assertTrue(text.startswith("// Task graph data."))
        self.assertEqual(model.parse(text), g)

    def test_parse_rejects_garbage(self):
        for bad in ("var x = 1;", "window.TASKGRAPH = {;"):
            with self.assertRaises(GraphError):
                model.parse(bad)

    def test_validate_ok(self):
        self.assertEqual(model.validate(make_graph()), [])

    def test_validate_format_version(self):
        g = make_graph()
        g["version"] = 2
        self.assertEqual(model.validate(g),
                         ["format version 2 is newer than this fm reads (1); update the plugin"])
        for bad in (None, 0, "1", True):
            g["version"] = bad
            self.assertTrue(any("unknown format version" in p for p in model.validate(g)), bad)

    def test_validate_stages_required(self):
        for bad in (None, [], ["plan"], ["a", "a"], ["a", ""], ["a", 3], "ab"):
            g = make_graph()
            if bad is None:
                del g["stages"]
            else:
                g["stages"] = bad
            problems = model.validate(g)
            self.assertTrue(any("stages" in p for p in problems), (bad, problems))

    def test_validate_ids_must_be_strings(self):
        g = make_graph()
        g["items"][0]["id"] = 1
        problems = model.validate(g)
        self.assertTrue(any("id" in p and "string" in p for p in problems), problems)
        g = make_graph()
        g["items"][0]["id"] = ""
        self.assertTrue(any("id" in p for p in model.validate(g)))

    def _one_problem(self, mutate, needle):
        g = make_graph()
        mutate(g)
        problems = model.validate(g)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(needle, problems[0])

    def test_validate_problems(self):
        def dup(g):
            g["items"].append(copy.deepcopy(g["items"][0]))
        self._one_problem(dup, "1")

        def unknown_dep(g):
            g["items"][2]["deps"] = [{"id": "77"}]
        self._one_problem(unknown_dep, "77")

        def self_dep(g):
            g["items"][2]["deps"] = [{"id": "3"}]
        self._one_problem(self_dep, "3")

        def cycle(g):
            g["items"][2]["deps"] = [{"id": "4"}]
        g = make_graph()
        cycle(g)
        problems = model.validate(g)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("cycle", problems[0])
        self.assertIn("3", problems[0])
        self.assertIn("4", problems[0])

        def bad_stage(g):
            g["items"][2]["stage"] = 9
        self._one_problem(bad_stage, "3")

        def bad_status(g):
            g["items"][2]["status"] = "wip"
        self._one_problem(bad_status, "wip")

        def bad_session(g):
            g["items"][2]["session"] = "99"
        self._one_problem(bad_session, "99")

        def bad_group(g):
            g["items"][2]["group"] = "ZZ"
        self._one_problem(bad_group, "ZZ")

        def bad_queue(g):
            g["sessions"][0]["queue"] = ["55"]
        self._one_problem(bad_queue, "55")

        def bad_conflict(g):
            g["conflicts"] = [{"a": "1", "b": "66", "why": "x"}]
        self._one_problem(bad_conflict, "66")

        def same_conflict(g):
            g["conflicts"] = [{"a": "1", "b": "1", "why": "x"}]
        self._one_problem(same_conflict, "1")

        def bad_lang(g):
            g["lang"] = "de"
        self._one_problem(bad_lang, "de")

    def test_parse_stage(self):
        g = make_graph("ru")
        self.assertEqual(model.parse_stage(g, "Код"), 1)
        self.assertEqual(model.parse_stage(g, "3"), 3)
        self.assertEqual(model.parse_stage(g, "-"), -1)
        self.assertEqual(model.parse_stage(g, "none"), -1)
        with self.assertRaises(GraphError) as cm:
            model.parse_stage(g, "deploy")
        for name in g["stages"]:
            self.assertIn(name, str(cm.exception))

    def test_parse_dep(self):
        g = make_graph("ru")
        self.assertEqual(model.parse_dep(g, "2"), {"id": "2"})
        self.assertEqual(model.parse_dep(g, "2@ревью"), {"id": "2", "stage": 2})
        self.assertEqual(model.parse_dep(g, "3:part"), {"id": "3", "kind": "part"})
        self.assertEqual(model.parse_dep(g, "2@4:part"),
                         {"id": "2", "stage": 4, "kind": "part"})

    def test_parse_dep_rejects_unstarted_stage(self):
        g = make_graph("ru")
        with self.assertRaises(GraphError) as cm:
            model.parse_dep(g, "2@-")
        self.assertIn("real stage", str(cm.exception))

    def test_validate_item_without_id(self):
        g = make_graph()
        g["items"].append({"title": "broken", "deps": [{"id": "1"}]})
        problems = model.validate(g)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("no id", problems[0])
        model.item_states(g)
        model.summary_lines(g)

    def test_item_states(self):
        g = make_graph()
        self.assertEqual(model.item_states(g),
                         {"1": "done", "2": "wait-me", "3": "ready", "4": "blocked"})
        g["items"][1]["stage"] = 2
        self.assertEqual(model.item_states(g)["4"], "ready")

    def test_review_status(self):
        g = make_graph()
        g["items"][3]["status"] = "review"  # item 4 has an unmet dependency
        self.assertEqual(model.item_states(g)["4"], "review")
        self.assertEqual(model.validate(g), [])
        self.assertIn("in review: 4", model.summary_lines(g))
        g["items"][2]["status"] = "wip"
        self.assertTrue(model.validate(g))

    def test_summary_lines(self):
        g = make_graph()
        g["task"]["rev"] = 7
        lines = model.summary_lines(g)
        self.assertIn("K-1", lines[0])
        self.assertIn("Sample task", lines[0])
        self.assertIn("rev", lines[0])
        self.assertIn("done 1/4", lines)
        waiting = [ln for ln in lines if ln.startswith("waiting on user:")]
        self.assertEqual(len(waiting), 1)
        self.assertIn("2", waiting[0])
        big = make_graph()
        template = big["items"][2]
        for n in range(10, 50):
            it = copy.deepcopy(template)
            it["id"] = str(n)
            big["items"].append(it)
        self.assertLessEqual(len(model.summary_lines(big)), 15)

    def test_session_states(self):
        g = make_graph()
        # 01: items 1 (done), 3 (ready); 02: items 2 (wait-me), 4 (blocked)
        self.assertEqual(model.session_states(g), {"01": "todo", "02": "wait-me"})
        g["items"][2]["status"] = "doing"
        self.assertEqual(model.session_states(g)["01"], "doing")
        g["items"][2]["status"] = "review"
        self.assertEqual(model.session_states(g)["01"], "review")
        g["items"][2]["status"] = "done"
        self.assertEqual(model.session_states(g)["01"], "done")
        g["items"][1]["status"] = "doing"  # 02: doing + blocked
        self.assertEqual(model.session_states(g)["02"], "doing")
        g["items"][1]["status"] = "done"   # 02: done + ready
        self.assertEqual(model.session_states(g)["02"], "todo")

    def test_session_state_ignores_stored_field(self):
        g = make_graph()
        g["sessions"][0]["state"] = "stuck"  # older files carry a hand-set value
        self.assertEqual(model.validate(g), [])
        self.assertEqual(model.session_states(g)["01"], "todo")

    def test_session_state_counts_queue_and_empty(self):
        g = make_graph()
        g["sessions"].append({"id": "03", "name": "03", "dir": "", "note": "",
                              "queue": ["2"]})
        g["sessions"].append({"id": "04", "name": "04", "dir": "", "note": "", "queue": []})
        states = model.session_states(g)
        self.assertEqual((states["03"], states["04"]), ("wait-me", "todo"))
        self.assertIn("sessions: 01-a todo, 02-x wait-me, 03 wait-me, 04 todo",
                      model.summary_lines(g))

    def test_show_empty_graph(self):
        lines = model.summary_lines(model.new_graph("K", "T"))
        self.assertTrue(any("no items yet" in ln for ln in lines), lines)

    def test_pick_python(self):
        out = subprocess.run(
            [find_bash(), "-c",
             '. plugin/scripts/pick-python.sh; "${PY[@]}" -c "print(1)"'],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), "1", out.stderr)


if __name__ == "__main__":
    unittest.main()
