"""The eval suite in plugin/evals stays in step with what fm writes.

Each case's scaffold is run, the commands a correct session would run are played with the real
fm, and every grader that reads the graph file must match the result. A change to the file format
or to fm that would make a correct session fail its eval fails here first, without a model.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT, find_bash

EVALS = ROOT / "plugin" / "evals"
FM = ROOT / "plugin" / "bin" / "fm"

IMPORT_JSON = (
    '{"version":1,"lang":"en","task":{"key":"SHOP","title":"Online shop"},'
    '"stages":["plan","code","review","PR","merged","done"],'
    '"sessions":[{"id":"01","name":"backend"},{"id":"02","name":"mail"}],'
    '"items":[{"id":"A1","title":"Cart","session":"01","stage":"done","status":"done"},'
    '{"id":"A2","title":"Checkout","session":"01","stage":"code","status":"review","deps":[{"id":"A1"}]},'
    '{"id":"A3","title":"Order emails","session":"02","stage":-1,"status":"todo",'
    '"deps":[{"id":"A2","stage":"merged"}]}]}')

# What a correct session runs in each case (after `fm SHOP`).
EXPECTED = {
    "01-create-graph": [["init", "Online shop"], ["session", "01", "name=shop"],
                        ["add", "A1", "Cart", "session=01"],
                        ["add", "A2", "Checkout", "session=01", "after=A1@code"],
                        ["add", "A3", "Order emails", "session=01", "after=A2"],
                        ["session", "01", "queue=A1,A2,A3"]],
    "02-mark-finished": [["done", "A1"]],
    "03-ask-user": [["ask", "A2", "Which payment provider should checkout use?"]],
    "04-import-running": [["import", "plan.json"]],
    "05-stage-semantics": [["next", "A1", "status=review"], ["start", "A2"]],
}


def file_graders(case_yaml: Path) -> list[tuple[str, str, str]]:
    """(name, pattern, flags) of the regex graders on the graph file. The case files keep one
    simple layout (see CONTRIBUTING.md), so no YAML library is needed."""
    out = []
    for block in case_yaml.read_text(encoding="utf-8").split("\n  - name: ")[1:]:
        target = re.search(r"\n    target: (.*)", block)
        pattern = re.search(r"\n    pattern: '(.*)'", block)
        if target and pattern and "taskgraph.js" in target.group(1):
            flags = re.search(r"\n    flags: (\w+)", block)
            out.append((block.split("\n", 1)[0], pattern.group(1).replace("''", "'"),
                        flags.group(1) if flags else ""))
    return out


class EvalSuiteTests(unittest.TestCase):
    def _run(self, ws: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([find_bash(), *args], cwd=ws, capture_output=True, text=True,
                              encoding="utf-8")

    def test_every_case_is_covered(self):
        cases = sorted(p.parent.name for p in EVALS.glob("*/case.yaml"))
        self.assertEqual(cases, sorted(EXPECTED))

    def test_graders_match_a_correct_session(self):
        for name, commands in EXPECTED.items():
            with self.subTest(case=name):
                ws = Path(tempfile.mkdtemp(prefix="fm-eval-"))
                self.addCleanup(shutil.rmtree, ws, True)
                scaffold = self._run(ws, str(EVALS / name / "scaffold.sh"))
                self.assertEqual(scaffold.returncode, 0, scaffold.stderr)
                graph = ws / ".tasks" / "SHOP" / "taskgraph.js"
                before = graph.read_text(encoding="utf-8") if graph.exists() else ""
                if name == "04-import-running":
                    (ws / "plan.json").write_text(IMPORT_JSON, encoding="utf-8")
                for cmd in commands:
                    r = self._run(ws, str(FM), "SHOP", *cmd)
                    self.assertEqual(r.returncode, 0, (cmd, r.stderr))
                check = self._run(ws, str(FM), "SHOP", "check")
                self.assertEqual(check.stdout.strip(), "ok", check.stderr)
                after = graph.read_text(encoding="utf-8")
                graders = file_graders(EVALS / name / "case.yaml")
                self.assertTrue(graders)
                changed = False
                for gname, pattern, flags in graders:
                    f = (re.M if "m" in flags else 0) | (re.I if "i" in flags else 0)
                    self.assertRegex(after, re.compile(pattern, f), gname)
                    changed |= re.search(pattern, before, f) is None
                # the graders must notice when the session did nothing
                self.assertTrue(changed, "every file grader already passes on the scaffold")


if __name__ == "__main__":
    unittest.main()
