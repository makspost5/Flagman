# Changelog

All notable changes to Flagman are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/): what stays stable within 1.x is under
[Compatibility](README.md#compatibility) in the README.

## [1.0.0] - Unreleased

The first public release. Earlier builds were published as 0.2.0 without tags; this entry
covers everything since then. Graphs made with 0.2.0 open in 1.0.0 without changes.

### Added

- `start`, `next`, `done` and `ask` shortcut commands for the usual item moves (#10).
- `fm --version` prints the plugin version (#17).
- `lang` setting: the language of new graphs, `en` or `ru` (#4).
- Auto graph: when a session splits a task into `auto_graph_min` (default 6) or more items in
  a plan file or its todo list and no graph exists, Claude offers one (`auto_graph=ask`, the
  default), creates it (`on`), or stays quiet (`off`) (#40).
- `watch_files` setting: which files remind a session to update the graph, as names or
  globs; default `status.md,plan.md` (#5).
- The page shows the number of items waiting on you in the tab title and on the favicon (#6).
- `fm show` prints a sessions line.
- `import` takes stage names as well as indexes in `items[].stage` and `deps[].stage`, and
  imports a session without a state as `todo` (#16).
- [Live demo](https://makspost5.github.io/Flagman/) on GitHub Pages and a GIF in the README (#2).
- [Workflow guide](docs/workflow.md): one big task with parallel sessions from plan to
  finish (#3).
- Compatibility promise for 1.x in the README (#14). `fm` refuses to change a graph in a
  newer format than it reads and says to update the plugin.
- CONTRIBUTING, SECURITY.md and issue templates (#12).
- CI runs the tests on Windows, macOS and Ubuntu with Python 3.9 and 3.13 (#1), and runs
  `fm` from PATH on the demo the way the plugin does (#15).

### Changed

- `fm init` without `lang=` creates an English graph; it was Russian before (#4).
- A session's state is computed from its items instead of being stored: any waiting on you
  makes it `wait-me`, any in progress `doing`, all done `done`. A stored `state` is ignored,
  and `fm session ID state=` is refused with an explanation (#8).
- Graph view: arrows run on their own tracks with fewer crossings and stay quiet until you
  hover or click an item, which lights up its dependencies, dependents and conflicts. A
  conflict shows as a mark on each item; its line appears for the selected item (#19).

### Fixed

- On Windows `fm.cmd` skips the Microsoft Store `python` alias and any Python older than
  3.9, and says where to get Python when none fits (#18).

## 0.2.0

The baseline before 1.0.0, not tagged.

- The `fm` command: `init`, `import`, `add`, `set`, `rm`, `dep`, `group`, `session`,
  `conflict`, `show`, `check`, `open`.
- `taskgraph.js` format version 1: items with stages and statuses, dependencies on an item
  or on one of its stages, groups, sessions with queues, conflicts.
- The page: a graph and a list, left-to-right or top-to-bottom, RU/EN, refreshing by itself.
- The `/flagman:graph` skill and the hook that reminds a session to update the graph when it
  edits `plan.md` or `status.md`.

[1.0.0]: https://github.com/makspost5/Flagman/releases/tag/v1.0.0
