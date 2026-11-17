---
name: graph
description: "Граф задачи: заведи граф, обнови граф, покажи граф, статус пунктов, стадии, параллельные сессии. Task graph: create, update or show the dependency graph of a task's items (stages, statuses, waiting on the user, parallel sessions) with the fm command (Flagman) and a local web page."
---

Command: `fm` (on PATH in Bash and PowerShell; on Windows PowerShell runs `bin/fm.cmd`). Never prefix it with `bash` in PowerShell (that is WSL there). If `fm` is not found: Bash `bash "${CLAUDE_PLUGIN_ROOT}/bin/fm"`, PowerShell `& "${CLAUDE_PLUGIN_ROOT}/bin/fm.cmd"`. Form: `fm TASK COMMAND [key=value ...]`; TASK is the folder name or path. For `init` and `import` it is an existing folder (path, or a name found by lookup). If not found, add `--root '${user_config.tasks_dir}'` first. Never read or edit `taskgraph.js`; use `show`.

**Worker session** (changes only its own items):
- `fm TASK start ID` began work; `fm TASK next ID` finished the next stage (status doing; done after the last stage; `next ID status=review` when it now waits on other people); `fm TASK done ID` finished; `fm TASK ask ID "what you need from the user"` waits on the user. Add `summary="..."` to any of them.
- Full control: `fm TASK set ID stage=code status=doing` (stages: plan, code, review, PR, merged, done; or the graph's own; statuses: todo, doing, wait-me, review, done; `review` = finished on our side, waiting for other people: code review, merge). `stage` is the last stage FINISHED: code written → `stage=code`; coding just started → keep the previous stage, `status=doing`. For an item with several parts, the stage all parts have finished.
- `fm TASK set ID summary="one line of progress"`
- `fm TASK show` prints a short summary; `fm TASK log` the last changes (`n=50` for more).

**Architect** (structure, in this order):
- `fm TASK init "Title" lang='${user_config.lang}'` (a different language only if the user asks); `fm TASK group G title=Name estimate="2 days"`
- `fm TASK session 01 name=api dir=sessions/01-api`
- `fm TASK add A1 "Title" group=G session=01`; `fm TASK add B1 "Title" group=G session=01`; `fm TASK add A2 "Title" group=G session=01 after=A1,B1@code`
- `fm TASK session 01 queue=A1,A2` (after the items exist)
- `fm TASK dep A2 +B1@review -A1`; `fm TASK conflict A2 B1 "both edit the same file"`; `fm TASK add C1 "Title"`; `fm TASK rm C1` (refused while another item, a queue or a conflict refers to it)
- `fm TASK check` validates; `fm TASK open` copies and opens the page.

**Graph for a running task:** build one JSON from its plan/status, run `fm TASK import FILE.json` (creates the graph if the folder has none), then `fm TASK check`. Minimal JSON: `{"version":1,"lang":"en","task":{"key":"K","title":"T"},"stages":["plan","code","done"],"items":[{"id":"A1","title":"first","stage":-1,"status":"todo"},{"id":"A2","title":"second","stage":-1,"status":"todo","deps":[{"id":"A1","stage":"code"}]}]}`. `stage` is a stage name or an index into stages (-1 = not started); a dependency's `stage` (optional) is the stage of that item it waits for. Put each session's items and its `start` / `next` / `done` / `ask` lines into that session's prompt.

**Auto graph reminder** (the hook says a task is split into N items and has no graph): if it says to ask, ask the user in one line and stop there unless they agree. Then: pick a short upper-case KEY for the task (issue or branch name), create the folder the reminder names with that KEY, build the JSON from the plan's items (ids, titles, deps between them, sessions if the plan has them) and `fm KEY import FILE.json`, `fm KEY check`, `fm KEY open`. If the task already has a graph, use it instead.

Answer the user in their language.
