<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/brand/banner-dark.png">
  <img src="docs/brand/banner-light.png" alt="Flagman. Run big tasks with ease. See everything at a glance.">
</picture>

<img src="docs/brand/mascot.png" width="240" align="right" alt="The Flagman mascot: a robot in a cap with a flag">

Flagman is a Claude Code plugin for a big task split into many items. It keeps a dependency
graph of the items. Every item has a stage (plan, code, review, PR, merged, done) and a status
(`todo`, `doing`, `wait-me`, `review`, `done`). Several Claude sessions can work on one task in
parallel and update their own items with a short `fm` command; a local web page shows the
graph, the list, what waits on you, what can run in parallel, and conflicts between items.

The name: a flagman is the road worker with a flag who decides who goes now and who waits.

![Flagman page](docs/screenshot.png)

Try it on the bundled example: run `bash plugin/bin/fm examples/demo open`; it writes
`examples/demo/taskgraph.html` (git-ignored) and opens it.

## Requirements

- Claude Code with plugin support
- Python 3.9 or newer (standard library only)
- bash (Git Bash on Windows)
- a browser for the page

Tested on Windows only. The code is portable, but macOS and Linux are not verified.

Maintainer note: a commit made on Windows stores `plugin/bin/fm` and `plugin/scripts/hook`
without the executable bit. After `git add`, run
`git update-index --chmod=+x plugin/bin/fm plugin/scripts/hook`. On macOS and
Linux the hook reminder runs the command as `bash "<plugin>/bin/fm" ...`, so it works regardless
of the bit; the hook itself is started through `bash` as well. On Windows the reminder says
plain `fm`: Claude Code's Bash tool runs `bin/fm`, its PowerShell tool runs `bin/fm.cmd`
(PowerShell cannot run an extensionless file, and `bash` in PowerShell is WSL). Keep
`bin/fm.cmd` with CRLF line endings (`.gitattributes` does this).

## Install

```
/plugin marketplace add <path or git URL of this repository>
/plugin install flagman@flagman
/reload-plugins
```

Install at user level to have the plugin in every session. The optional setting `tasks_dir`
(where task folders live) is asked for when the plugin is enabled; leave it empty and `fm`
finds the task from the current folder.

## Lines for your CLAUDE.md

Russian:

```
- Если в папке задачи есть `taskgraph.js`, стадии и статусы пунктов меняй только командой из `/flagman:graph`;
  сам файл не читай и не правь.
- Для задачи с несколькими параллельными сессиями архитектор заводит граф (`/flagman:graph`) и вписывает в
  промпт каждой сессии её пункты и команду обновления.
```

English:

```
- If the task folder has a `taskgraph.js`, change item stages and statuses only with the command from
  `/flagman:graph`; do not read or edit the file itself.
- For a task with several parallel sessions, the architect creates the graph (`/flagman:graph`) and puts each
  session's items and the update command into that session's prompt.
```

## Commands

`fm [--root DIR] TASK COMMAND [key=value ...]`. `TASK` is a task folder path, or a folder
name looked up in the current folder, its parents, their `.tasks/` folders, and `--root`. The
`fm` launcher is on PATH only inside Claude Code (its Bash and PowerShell tools) while the plugin
is enabled. From your own terminal run `<plugin>/bin/fm` (or `bash <plugin>/bin/fm`), or on
Windows `<plugin>\bin\fm.cmd`.

| Command | Meaning |
|---|---|
| `init TITLE [lang=ru\|en] [due=YYYY-MM-DD] [link=LABEL\|HREF]` | create `taskgraph.js` |
| `import FILE.json` | replace the graph from a JSON file |
| `add ID TITLE [group= session= stage= status= after=A,B summary= wait= detail= file= link=]` | add an item |
| `set ID [stage= status= wait= summary= title= group= session=]` | change an item |
| `rm ID` | remove an item (refused while something refers to it) |
| `dep ID +DEP -DEPID [note=]` | add or remove dependencies; `DEP` is `ID[@STAGE][:part]` |
| `group ID [title= estimate=]` | create or update a group |
| `session ID [name= dir= state= note= queue=a,b]` | create or update a session |
| `conflict A B WHY` / `conflict A B -` | mark or clear a conflict between two items |
| `show` | short summary: done, waiting on the user, in progress, ready, blocked |
| `check` | validate the file (`ok` or a list of problems) |
| `open [--no-browser]` | copy the page next to `taskgraph.js` and open it |

Example:

```
fm SHOP-1 set P2 stage=review status=wait-me wait="pick the payment provider"
```

The `/flagman:graph` skill tells Claude when and how to use these commands.

## The page

`fm open` writes `taskgraph.html` next to `taskgraph.js` and opens it from `file://`. The page
re-reads the data every few seconds, so it follows `fm` updates. It has a graph tab and a list
tab, left-to-right or top-to-bottom layout, and an RU/EN switch. Query parameters:
`?lang=ru|en`, `?dir=lr|tb`, `?tab=graph|list`, `?poll=MS` (refresh interval, at least 200).

## How the hook works

A hook watches edits (`Edit`, `Write`, `MultiEdit`) of files named `status.md` or `plan.md`.
When a session edits one inside a folder that has a `taskgraph.js` (found by walking up from
the file), the hook adds a short reminder to that session's context, once per user prompt.
If the edited path belongs to a session's `dir` in the graph, the reminder lists that
session's items and the exact `set` command; otherwise it is a neutral reminder. Example text:

```
Task graph SHOP-1, session 01 items: P2 code/doing, P3 -/todo. If a stage or status
changed, run: fm "<task folder>" set <id> stage=<last finished stage>
status=<todo|doing|wait-me|review|done> (add wait="<what you need from the user>" with wait-me).
Otherwise ignore this.
```

A graph that is missing or broken makes the hook silent. Errors go to `hook-errors.log` in
the plugin data folder (`~/.flagman` if unset).

## Data format

`taskgraph.js` is a JavaScript file that assigns one JSON object to `window.TASKGRAPH`, so
the page can load it with `<script src>` from `file://`. Only `fm` writes it, atomically.

```
{ "version": 1, "lang": "en",
  "task": { "key", "title", "links": [{label, href}], "due", "updated", "rev" },
  "stages": ["plan", "code", ...],
  "groups": [{ "id", "title", "estimate" }],
  "sessions": [{ "id", "name", "dir", "state", "note", "queue": [item ids] }],
  "items": [{ "id", "title", "group", "session", "stage", "status", "wait",
              "deps": [{ "id", "stage"?, "kind"?, "note" }],
              "summary", "details", "links", "files" }],
  "conflicts": [{ "a", "b", "why" }] }
```

`stage` is an index into `stages` (`-1` = not started). The last stage means done.
`stages` must hold at least 2 unique, non-empty names. Ids are strings; `import` converts
numeric ids to strings. Run `fm TASK check` after importing a hand-made file.

## Brand

The Flagman mark: `docs/brand/flagman-mark.svg` for light backgrounds and
`docs/brand/flagman-mark-sticker.svg` (with a white outline) for dark ones. The README banner
(`docs/brand/banner-dark.png`, `banner-light.png`) and the mascot (`docs/brand/mascot.png`) are
in the same folder.

## Tests

```
py -3 -m unittest discover -s tests -t . -v
```

The page tests use Microsoft Edge in headless mode and are skipped when no browser is found.
