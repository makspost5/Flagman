# Security policy

## Report a vulnerability

Do not open a public issue. Report it privately through GitHub:
[Security → Report a vulnerability](https://github.com/makspost5/Flagman/security/advisories/new).

Include what an attacker can do, the steps to reproduce, the Flagman version (`fm --version`),
your OS and shell. You will get an answer within 7 days. A fix goes out in a new release, and
the advisory is published after it, with credit to you unless you ask otherwise.

## Supported versions

Only the latest release gets security fixes.

## Scope

In scope:

- **`fm`** (`plugin/bin/`, `plugin/scripts/taskgraph/`): for example, writing outside the task
  folder, running code from a `taskgraph.js` or from arguments, or a crafted graph that corrupts
  other files.
- **The hook** (`plugin/scripts/hook`, `plugin/hooks/hooks.json`): for example, running
  commands or reading files it should not, based on what a session edits.
- **The page** (`plugin/page/taskgraph.html`) rendering `taskgraph.js`: for example, a title,
  summary, note or link in the graph that runs script in the page (XSS) or a link that opens
  a `javascript:` URL.

Out of scope:

- What a Claude Code session does with its own tools. Flagman only suggests `fm` commands.
- Anyone who can already write to your task folder or plugin folder: they can change the
  page and the scripts directly.
- Issues in Claude Code, Python, bash or the browser themselves.
