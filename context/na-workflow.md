# na Workflow

`na` ("next action") is a CLI tool by Brett Terpstra that reads TaskPaper files and surfaces tasks tagged `@na`.

## Key facts

- Install: available at `/opt/homebrew/bin/na`, version 1.2.100
- Project file: `todo.taskpaper` in the project root
- `na` or `na next` — shows all tasks tagged `@na` in the current directory
- `na add "Task text"` — adds a new task
- `na complete SEARCH` — marks matching task `@done`
- `na find PATTERN` — search across all tasks

## Tagging conventions

- `@na` — marks a task as a next action; shows up in `na next`
- `@done` — marks complete; excluded from `na next`
- `@priority(1-5)` — urgency; `na tagged @priority>=3` filters by level

## Workflow for grandma-watcher

Tasks in `todo.taskpaper` that are ready to work on should be tagged `@na`.
Tasks that are blocked or future should have no `@na` tag.
When starting a task, it can be left `@na`. When done, run `na complete <search>` or manually add `@done`.

## Prompt integration

Run `na prompt install` to auto-show next actions when `cd`-ing into the project directory.

## Lessons Learned

2026-04-10: Scott uses `na` CLI to track next actions. Tasks in todo.taskpaper need `@na` tag to surface in `na next`. Tag ready-to-work tasks with `@na`; leave future/blocked tasks untagged.
