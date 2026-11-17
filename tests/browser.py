"""Headless Chromium helpers for page tests: find a browser, dump a page's DOM."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

BROWSER_NAMES = ("msedge", "google-chrome", "chromium", "chrome")
TIMEOUT_S = 90


def _edge_paths() -> list[Path]:
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
             r"C:\Program Files", r"C:\Program Files (x86)"]
    paths: list[Path] = []
    for root in roots:
        if root:
            p = Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p not in paths:
                paths.append(p)
    return paths


def find_browser() -> str | None:
    """TASKGRAPH_BROWSER, then Edge under Program Files, then PATH. None if nothing found."""
    env = os.environ.get("TASKGRAPH_BROWSER")
    if env:
        return shutil.which(env) or env
    for p in _edge_paths():
        if p.is_file():
            return str(p)
    for name in BROWSER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def _remove_tree(path: str) -> None:
    # Browser child processes may hold profile files for a moment after the main one exits.
    for _ in range(20):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.25)
    shutil.rmtree(path, ignore_errors=True)


def run_headless(args: list[str]) -> subprocess.CompletedProcess:
    """Run the browser headless with a fresh temporary profile, then delete the profile."""
    browser = find_browser()
    if browser is None:
        raise RuntimeError("no Chromium-based browser found; set TASKGRAPH_BROWSER")
    profile = tempfile.mkdtemp(prefix="fm-browser-")
    try:
        cmd = [browser, "--headless=new", "--disable-gpu", "--user-data-dir=" + profile] + args
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=TIMEOUT_S)
    finally:
        _remove_tree(profile)


def dump_dom(page: Path, query: str = "", budget_ms: int = 2000) -> str:
    """The page's DOM after budget_ms of virtual time; query is appended to the file URI."""
    uri = Path(page).resolve().as_uri() + query
    res = run_headless(["--virtual-time-budget=%d" % budget_ms, "--dump-dom", uri])
    out = res.stdout.decode("utf-8", errors="replace")
    if not out.strip():
        raise RuntimeError("browser printed no DOM (exit %s): %s"
                           % (res.returncode, res.stderr.decode("utf-8", "replace")[-2000:]))
    return out
