"""Entry point of the `fm` command."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from taskgraph import cli  # noqa: E402


def _utf8(stream) -> None:
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


if __name__ == "__main__":
    _utf8(sys.stdout)
    _utf8(sys.stderr)
    sys.exit(cli.main(sys.argv[1:]))
