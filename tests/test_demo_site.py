"""The live demo site (tools/demo_site.py): the scenario replays on the real page."""
from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401  (puts plugin/scripts on sys.path)
from tests.browser import dump_dom, find_browser
from taskgraph import model

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("demo_site", ROOT / "tools" / "demo_site.py")
demo_site = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo_site)


class ScenarioTests(unittest.TestCase):
    def test_parse_scenario(self):
        steps = demo_site.parse_scenario("# note\n> first\n> second\nfm K start A\nfm K done A\n")
        self.assertEqual(steps, [("first", []), ("second", ["fm K start A", "fm K done A"])])

    def test_parse_scenario_rejects_stray_lines(self):
        with self.assertRaises(ValueError):
            demo_site.parse_scenario("> step\nrm -rf /\n")
        with self.assertRaises(ValueError):
            demo_site.parse_scenario("# only comments\n")

    def test_failing_command_stops_the_build(self):
        with self.assertRaisesRegex(RuntimeError, "NOPE"):
            demo_site.record("> step\nfm SHOP-1 start NOPE\n")

    def test_demo_scenario_plays_from_the_demo_to_all_done(self):
        frames = demo_site.record((ROOT / "examples" / "demo" / "scenario.txt").read_text(encoding="utf-8"))
        self.assertGreater(len(frames), 5)
        demo = model.parse((ROOT / "examples" / "demo" / "taskgraph.js").read_text(encoding="utf-8"))
        self.assertEqual(frames[0]["graph"]["items"], demo["items"])
        self.assertEqual(set(model.item_states(frames[-1]["graph"]).values()), {"done"})
        states = [set(model.item_states(f["graph"]).values()) for f in frames]
        self.assertTrue(any("wait-me" in s for s in states[1:]), "the demo should show a new question")
        for f in frames:
            self.assertTrue(f["caption"])
            self.assertEqual(model.validate(f["graph"]), [])

    def test_build_writes_the_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = demo_site.build(Path(tmp))
            page = (Path(tmp) / "index.html").read_text(encoding="utf-8")
            data = (Path(tmp) / "taskgraph.js").read_text(encoding="utf-8")
        self.assertIn('<script src="taskgraph.js"></script>', page)
        self.assertNotIn("</script", data)
        steps = json.loads(re.search(r"var STEPS = (.*);\n", data).group(1).replace("<\\/", "</"))
        self.assertEqual(steps, frames)


@unittest.skipUnless(find_browser(), "no Chromium-based browser found")
class DemoPageTests(unittest.TestCase):
    def test_page_plays_the_scenario(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = demo_site.build(Path(tmp))
            first = dump_dom(Path(tmp) / "index.html", budget_ms=1000)
            later = dump_dom(Path(tmp) / "index.html", budget_ms=3 * demo_site.STEP_MS + 2000)
        n = len(frames)
        self.assertIn(f"step 1 of {n}", first)
        self.assertIn(frames[0]["caption"], first)
        self.assertRegex(later, rf"step [3-9] of {n}")
        self.assertNotIn(f"step 1 of {n}", later)
        for dom in (first, later):
            self.assertRegex(dom, r'id="err"[^>]*>\s*<')


if __name__ == "__main__":
    unittest.main()
