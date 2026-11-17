"""The commands in docs/workflow.md build the graph the guide says they build."""
from __future__ import annotations

import io
import re
import shlex
import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401  (puts plugin/scripts on sys.path)
from taskgraph import cli

GUIDE = Path(__file__).resolve().parent.parent / "docs" / "workflow.md"


def fenced_blocks(text: str) -> list[str]:
    return re.findall(r"^```[a-z]*\n(.*?)^```", text, flags=re.M | re.S)


class WorkflowGuideTests(unittest.TestCase):
    def test_architect_commands_build_the_documented_graph(self):
        text = GUIDE.read_text(encoding="utf-8")
        setup = text.split("\n## 3.", 1)[0]
        blocks = fenced_blocks(setup)
        commands = [line for b in blocks for line in b.splitlines()
                    if line.startswith("fm SHOP-1 ") and not line.endswith((" open", " show"))]
        self.assertGreater(len(commands), 20)
        expected_show = next(b for b in blocks if b.startswith("SHOP-1 - "))

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".tasks" / "SHOP-1").mkdir(parents=True)
            for line in commands:
                out, err = io.StringIO(), io.StringIO()
                code = cli.main(shlex.split(line)[1:], cwd=Path(tmp), out=out, err=err)
                self.assertEqual(code, 0, f"{line}\n{err.getvalue()}")
            out = io.StringIO()
            self.assertEqual(cli.main(["SHOP-1", "show"], cwd=Path(tmp), out=out, err=io.StringIO()), 0)
        self.assertEqual(out.getvalue().strip(), expected_show.strip())


if __name__ == "__main__":
    unittest.main()
