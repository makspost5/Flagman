# Contributing to Flagman

Bug reports, ideas and pull requests are welcome. For a bug or an idea, open an issue first
with one of the templates. For a vulnerability, do not open an issue: see [SECURITY.md](SECURITY.md).

## What is where

| Path | What it is |
|---|---|
| `plugin/bin/fm`, `plugin/bin/fm.cmd` | The `fm` command: thin launchers for bash and for PowerShell/cmd |
| `plugin/scripts/taskgraph/` | The Python package behind `fm` and the hook: `model.py` (rules), `store.py` (reading and writing `taskgraph.js`), `cli.py` (commands), `hook.py` (the reminder) |
| `plugin/scripts/hook` | The hook launcher |
| `plugin/hooks/hooks.json` | When the hook runs |
| `plugin/skills/graph/` | The skill that tells a session how to use `fm` |
| `plugin/page/taskgraph.html` | The page: one HTML file with inline CSS and JavaScript, no build step |
| `tests/` | Tests for all of the above |
| `examples/demo/` | The demo graph and `scenario.txt`, the steps the live demo replays |
| `tools/demo_site.py`, `tools/demo_gif.py` | Build the live demo site and record `docs/demo.gif` |

## Run the tests

```
python -m unittest discover -s tests -t . -v
```

On Windows use `py -3` instead of `python` if `python` is not on PATH.

The page tests open the page in headless Edge or Chrome. Set `TASKGRAPH_BROWSER` to the
browser's path to pick one. When no browser is found they are skipped; with
`TASKGRAPH_REQUIRE_BROWSER=1` a missing browser is a failure.

CI (`.github/workflows/tests.yml`) runs the same command on Ubuntu 24.04, macOS and Windows
with Python 3.9 and 3.13, with `TASKGRAPH_REQUIRE_BROWSER=1`. A pull request needs a green
matrix. Changes to Markdown files and `docs/` alone do not start CI.

## Try the plugin locally

Run `fm` straight from the checkout, with no install:

```
bash plugin/bin/fm "<task folder>" show
```

To try the whole plugin (skill, hook, page) in Claude Code, add your checkout as a
marketplace instead of the GitHub one:

```
/plugin marketplace add <path to your checkout>
/plugin install flagman@flagman
```

After a change, run `/plugin marketplace update flagman` and `/reload-plugins`. If you
installed the GitHub version before, uninstall it first: both use the name `flagman`.

## The live demo

`python tools/demo_site.py` builds the site into `_site/`: the page as `index.html` and a
`taskgraph.js` that replays `examples/demo/scenario.txt`. Each step runs its `fm` commands on a
copy of `examples/demo/taskgraph.js`, so a scenario that no longer matches the CLI fails the
build (and the tests). The `demo` workflow publishes `_site/` to GitHub Pages on every push to
`main` that touches the page, the CLI, the demo or the tools.

After changing the page or the scenario, record the README GIF again and commit it:
`python tools/demo_gif.py` (needs Pillow and Edge or Chrome).

## Releasing

1. Add what changed to `CHANGELOG.md` as you merge: each pull request that changes behavior
   adds a line, with its issue number, to the top entry that has no date yet
   (`## [Unreleased]`, or `## [X.Y.Z] - Unreleased` once the version is known).
2. Pick the version by [Semantic Versioning](https://semver.org/) and the promise under
   [Compatibility](README.md#compatibility): a fix is a patch, a new command or field a minor
   version, a breaking change waits for 2.0.
3. In one pull request: set `version` in `plugin/.claude-plugin/plugin.json`, give the
   entry its heading `[X.Y.Z] - YYYY-MM-DD`, and add the `[X.Y.Z]` link at the bottom.
4. After it is merged, tag the merge commit and publish the release with that changelog entry
   as its notes:

   ```
   git tag -a vX.Y.Z -m "Flagman X.Y.Z"
   git push origin vX.Y.Z
   gh release create vX.Y.Z --title "Flagman X.Y.Z" --notes-file <the entry>
   ```

5. Check that `/plugin marketplace update flagman` on an installed copy picks up the new
   version (`fm --version`).

## Code style

- Python 3.9 or newer, standard library only. No third-party packages, at run time or in tests.
- The page stays one self-contained HTML file: no build step, nothing loaded from the network.
- `fm` prints short, plain messages; an error says what to do next.
- Every change in behavior comes with a test. A bug fix comes with a test that fails without it.
- A new command or field is documented in `README.md` in the same pull request.
- The rules that both Python and the page apply (item and session states) must
  give the same answer in both places; keep them in step and test both.
- Commit messages: a short summary line in the imperative (`fm: add the next command`), then
  a blank line and the why, if it is not obvious.

## Windows notes

- Git on Windows does not keep the executable bit. A commit that adds or changes
  `plugin/bin/fm` or `plugin/scripts/hook` must set it by hand after `git add`:

  ```
  git update-index --chmod=+x plugin/bin/fm plugin/scripts/hook
  ```

  On macOS and Linux the reminder runs `bash "<plugin>/bin/fm" ...` and the hook starts
  through `bash`, so the bit does not matter there, but a checkout should still keep it.
- On Windows the reminder says plain `fm`: the Bash tool runs `bin/fm`, the PowerShell tool
  runs `bin/fm.cmd` (PowerShell cannot run an extensionless file, and `bash` in PowerShell is WSL).
- `bin/fm.cmd` must keep CRLF line endings; every other file uses LF. `.gitattributes` does
  this on checkout. When a script writes files, write bytes, not text, or Windows will turn LF
  into CRLF.

## Pull requests

- One pull request per issue, with `Closes #N` in the description.
- Keep the diff to the issue: unrelated cleanups go in their own pull request.
- Describe what changed for the user and how you checked it.
