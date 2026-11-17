# Workflow: one big task from start to finish

This guide follows one task from the first plan to the last merged item. The task is the
demo task `SHOP-1`, a web shop release with nine items run by three Claude sessions. Open
the finished graph to see where the guide ends up:

```bash
bash plugin/bin/fm examples/demo open
```

## Who does what

- **You** describe the task, answer questions, and say when to merge.
- **The architect session** is one Claude Code session that splits the task into items,
  builds the graph and writes a prompt for every worker session. It does not write the code.
- **Worker sessions** are the Claude Code sessions that do the work, one per line of work
  (here: payments, catalog, ops). Each one changes only its own items in the graph.
- **The page** (`taskgraph.html`) shows the graph to you. It refreshes by itself.

Only `fm` writes the graph file, `taskgraph.js`. Nobody edits it by hand, Claude included.

## The folder

A task lives in one folder. `fm` finds it by name in the current folder, its parents and
their `.tasks/` folders, or by full path. This guide uses `.tasks/SHOP-1` in the project:

```
my-shop/
  .tasks/SHOP-1/
    taskgraph.js            the graph, written only by fm
    taskgraph.html          the page, written by fm open
    plan.md                 the architect's plan (optional)
    sessions/
      01-payments/prompt.md   the prompt for worker session 01
      01-payments/status.md   its progress notes
      02-catalog/...
      03-ops/...
```

Keep `.tasks/` out of git (add it to `.gitignore`) or put the task folder outside the
project and set `tasks_dir` (see [Configuration](../README.md#configuration)).

## 1. Split the task into items

Start a Claude Code session in the project. This is the architect. Describe the task, or
point it at a plan, and ask for a graph:

```
/flagman:graph create a graph for this task in .tasks/SHOP-1: release the web shop.
Payments: a gateway client, then checkout, then refunds. Catalog: search index, category
pages, search UI. Ops: staging, a load test, the release checklist. Three parallel sessions.
```

Good items for the graph:

- **One item, one result** you can check: a merged PR, a decision, a document. "Checkout flow"
  is an item; "work on payments" is not.
- **Ids that say the area**: `P1`, `P2` for payments, `C1` for catalog.
- **Dependencies only where one item really needs another.** Fewer arrows mean more parallel work.

Claude runs `fm` for you. These are the commands it runs for `SHOP-1`, in case you want to
check them or build a graph by hand:

```
fm SHOP-1 init "Web shop release" due=2026-12-15
fm SHOP-1 group pay title=Payments estimate="3 days"
fm SHOP-1 group cat title=Catalog estimate="2 days"
fm SHOP-1 group ops title="Release ops" estimate="1 day"
```

`init` needs the folder to exist (`mkdir -p .tasks/SHOP-1`). The folder name becomes the task
key. Groups are optional; they color the items and carry an estimate.

## 2. Sessions, queues and dependencies

A session is one worker: a name, a folder for its notes, and a queue of items in the order
it should do them.

```
fm SHOP-1 session 01 name=payments dir=sessions/01-payments
fm SHOP-1 session 02 name=catalog dir=sessions/02-catalog
fm SHOP-1 session 03 name=ops dir=sessions/03-ops

fm SHOP-1 add P1 "Payment gateway client" group=pay session=01
fm SHOP-1 add P2 "Checkout flow" group=pay session=01 after=P1
fm SHOP-1 add P3 "Refunds" group=pay session=01 after=P2
fm SHOP-1 add C1 "Product search index" group=cat session=02
fm SHOP-1 add C2 "Category pages" group=cat session=02
fm SHOP-1 add C3 "Search UI" group=cat session=02 after=C1
fm SHOP-1 add O1 "Staging environment" group=ops session=03
fm SHOP-1 add O2 "Load test" group=ops session=03 after=P2@code,C2@code,O1
fm SHOP-1 add O3 "Release checklist" group=ops session=03 after=O2,P3,C3

fm SHOP-1 session 01 queue=P1,P2,P3
fm SHOP-1 session 02 queue=C1,C2,C3
fm SHOP-1 session 03 queue=O1,O2,O3

fm SHOP-1 conflict P2 C2 "Both change the product card component"
fm SHOP-1 check
fm SHOP-1 open
```

- `after=P1` means P2 can start when P1 is done. `after=P2@code` means "when P2 has finished
  the `code` stage": the load test can start on written code before the PR is merged.
- Change dependencies later with `fm SHOP-1 dep O2 +P3 -O1`.
- A **conflict** marks two items in different sessions that touch the same thing. They can
  still run in parallel, but the second one to change the shared code rebases on the first.
  Items that conflict a lot belong in one session, one after the other.
- Split the work so that each session has its own part of the code. Three sessions that all
  edit one file are slower than one.

`fm SHOP-1 show` now prints:

```
SHOP-1 - Web shop release (rev 20)
done 0/9
ready to start: P1, C1, C2, O1
blocked: P2 (needs P1), P3 (needs P2), C3 (needs C1), O2 (needs P2, C2, O1), O3 (needs O2, P3, C3)
sessions: payments todo, catalog todo, ops todo
```

## 3. The prompt for each worker session

Ask the architect to write one prompt per session into the session folder:

```
Write sessions/<id>-<name>/prompt.md for every session from the template in docs/workflow.md.
```

The template (here filled in for session 01). Use the full path of the task folder: worker
sessions may run in other folders, such as git worktrees, where `fm SHOP-1` alone would not
find it.

```
You are session 01 (payments) of task SHOP-1 "Web shop release".
Task folder: /home/me/my-shop/.tasks/SHOP-1
Work in: /home/me/my-shop (branch per item, one PR per item)
Keep your progress notes in /home/me/my-shop/.tasks/SHOP-1/sessions/01-payments/status.md.

Your items, in this order:
1. P1 Payment gateway client.
2. P2 Checkout flow. Needs P1. Conflicts with C2 (session 02): both change the product card.
3. P3 Refunds. Needs P2.
Others wait on you: O2 (session 03) needs P2 at the code stage.

Update the graph for your items only, with these commands (never open taskgraph.js):
- began an item:              fm "/home/me/my-shop/.tasks/SHOP-1" start P1
- finished the next stage:    fm "/home/me/my-shop/.tasks/SHOP-1" next P1 summary="one line of progress"
- waits on other people now:  fm "/home/me/my-shop/.tasks/SHOP-1" next P1 status=review
- need an answer from me:     fm "/home/me/my-shop/.tasks/SHOP-1" ask P1 "the exact question"
- finished:                   fm "/home/me/my-shop/.tasks/SHOP-1" done P1
Stages: plan, code, review, PR, merged, done.
Before each item run fm "/home/me/my-shop/.tasks/SHOP-1" show. If its dependencies are not
done, say so and stop; do not start it early.
Do not merge without my "ok".

Start: fm "/home/me/my-shop/.tasks/SHOP-1" start P1
```

Then open one Claude Code window per session (in the folder the prompt names) and paste its
prompt. Three windows, three sessions.

## 4. What a worker does

A worker moves its item through the stages. `stage` is the last stage **finished**, and the
status says what is happening now:

| The worker runs | Stage | Status | Means |
|---|---|---|---|
| `fm SHOP-1 start P1` | — | doing | started planning |
| `fm SHOP-1 next P1 summary="plan written"` | plan | doing | plan done, coding |
| `fm SHOP-1 next P1` | code | doing | code written, reviewing it |
| `fm SHOP-1 next P1 status=review summary="PR #12 open"` | review | review | PR open, waits on reviewers |
| `fm SHOP-1 done P1 summary="merged"` | done | done | finished |

- `next` moves one stage on and sets `doing`; add `status=review` when the item now waits on
  other people (code review, a merge), not on the worker.
- `done` jumps to the last stage. `set` changes anything else:
  `fm SHOP-1 set P1 stage=code status=doing`.
- `summary=` is one line of progress shown on the page. Use it with any command.
- Workers keep notes in their `status.md`. When a session edits a `status.md` or `plan.md`
  inside the task folder, the plugin's hook reminds it to update the graph and lists its
  items, so a forgotten `next` gets caught.

When a worker needs a decision only you can make, it asks and waits:

```
fm SHOP-1 ask C1 "Pick the search engine: hosted or self-managed"
```

The item turns yellow and moves to **Waiting on you**. The worker then takes the next item it
can do (C2 here) or stops.

## 5. Answering and unblocking

You see a question in three places:

- the page: the **Waiting on you** panel, with the question and the item; the tab title
  starts with the count, `(1) Task map SHOP-1 · Flagman`, and the favicon gets a red badge;
  turn on **Notifications** to get a browser notification;
- `fm SHOP-1 show`: `waiting on user: C1`;
- the session's own window, where it asked.

Answer **in the window of the session that asked** (the item shows its session: C1 belongs
to 02, catalog). The worker continues and clears the question itself:

```
fm SHOP-1 start C1 summary="hosted engine, as decided"
```

When an item is done (or reaches the stage others wait for, like `P2@code`), the items that
needed it move from **Waiting on others** to **Ready to start**. Sessions are not woken up:
each worker checks `fm SHOP-1 show` before its next item. If a session stopped and waits,
tell it "C1 is done, go on".

If two sessions reach a conflict (P2 and C2), the one that merges second rebases on the
first. The red line on the page shows such pairs.

## 6. Finishing

The task is finished when `fm SHOP-1 show` says `done 9/9` and every session is `done`.
Then:

- check that nothing is left in **Waiting on you** or **In review**;
- close the session windows; remove their git worktrees, if you used them;
- keep `.tasks/SHOP-1` as a record of the task, or delete the folder. Outside it Flagman keeps
  only the hook's small state and error log in the plugin data folder.

## Short version

1. Architect: `/flagman:graph create a graph for this task in .tasks/KEY: ...`, with sessions
   and their queues.
2. Architect: a `prompt.md` per session from the template above.
3. You: one Claude Code window per session, paste its prompt, keep the page open.
4. Workers: `start`, `next`, `ask`, `done`. You: answer what waits on you, say "ok" to merges.
5. All done: close the sessions, keep or delete the task folder.
