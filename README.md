# Decisions panel for Claude Code

Stop answering Claude's questions in the chat. With this mod, Claude puts every choice it needs from you in a panel beside the chat and keeps working. You answer with one keypress when you are ready, and the answer goes straight back to Claude.

It also keeps a **Work of the day** list in the same panel, so you can see what is running, what waits on you and how far the day has got.

```
╭─ Decisions ─────────────────────────────────────────╮
│ D7 · 1 of 3 waiting · from reviewer agent           │
│ Merge the auth refactor now or after the release?   │
│ Tests pass. The release branch is cut on Friday.    │
│                                                     │
│ [1] Merge now (recommended)                         │
│     Lands in this release; two files conflict.      │
│ [2] Wait for the release                            │
│ Other: type your own answer              [send]     │
│ [d] Discuss first   [l] Later                       │
│                                                     │
│ Work · 6 of 14 done 43%                             │
│ ██████████████████░░░░░░░                           │
│ █ done 6  █ to merge 1  █ working 1  █ blocked 1    │
│ ▾ Today          ██████░░░░  4/8 50%                │
│ working  API-212 Rate limits on the public API      │
│          tests green, writing docs                  │
│ to merge API-208 Retry queue                        │
│ blocked  API-215 Webhook signing                    │
│          waiting on the security review             │
│ Done · 6 (show)                                     │
╰─────────────────────────────────────────────────────╯
```

## Why use it

- **Claude does not stop to wait for you.** A question in the chat ends Claude's turn. A decision in the panel does not: Claude posts it and carries on with other work.
- **Answer in one keypress.** Press `1` to `9` for an option, type your own answer, press `d` to talk it over first, or `l` to move it to the back of the queue.
- **Questions arrive ready to answer.** Each one has a short question, a line or two of context and numbered options, with Claude's recommendation first and marked.
- **Many agents, one queue.** Subagents and parallel sessions in the same project post to the same panel and say who asked, so you answer everything in one place.
- **See the day at a glance.** The work list shows each item as working, to merge, waiting, blocked, to do, done or dropped, with a progress bar for the day and for each group.
- **It survives restarts.** Open decisions and the work list are kept per project. Finished items from earlier days drop off by themselves.
- **Jira stays in step.** If you use the Atlassian MCP server, moving a ticket that is on the list moves the list item too.

## Install

You need Claude Code with mods (function hooks), version 2.1.300 or later.

In a Claude Code session, type:

```
/plugin install decisions --marketplace estatheo/claude-decisions
```

Press `y` to add the marketplace, then pick a scope (just you, or this project). Or from a shell:

```bash
claude plugin install decisions --marketplace estatheo/claude-decisions
```

That's it. Start a new session and Claude has the tools.

### Run it from a local copy

```bash
git clone https://github.com/estatheo/claude-decisions
claude --plugin-dir ./claude-decisions
```

To load it in every session, set `CLAUDE_CODE_PLUGIN_DIRS=/path/to/claude-decisions` in your shell or in the `env` block of `~/.claude/settings.json`.

## Use

- `/decisions` opens the panel. The status line shows how many decisions are waiting.
- The panel opens by itself when Claude posts a decision. It docks beside the chat in the fullscreen layout on a terminal about 110 columns wide or more. On a narrower terminal, `/decisions` still opens it.
- Claude decides when to use the tools from their descriptions. You can also ask: "put that in the panel", "add this to today's list", "group these under Sprint 12".

For the best results, add a line like this to your `CLAUDE.md`:

```markdown
When you need me to choose something, post it with mcp__decisions__post instead of asking in chat,
and keep the Work of the day list current with mcp__decisions__work_update.
```

### Keys

| Key | What it does |
| --- | --- |
| `1` to `9` | Pick that option |
| Other field | Type your own answer and press Enter |
| `d` | Discuss first: Claude asks you about it in the chat and does not act yet |
| `l` | Later: move this decision to the back of the queue |
| `w` | Show or hide finished work |

### What Claude gets

| Tool | What it does |
| --- | --- |
| `post` | Adds one or more decisions: question, context, 2 to 9 options, the recommended one, who asked |
| `list` | Lists open decisions and the ones answered recently |
| `withdraw` | Removes open decisions that no longer need you |
| `work_update` | Adds or updates work items by key: status, note, owner, link, group, order, due date |
| `work_list` | Shows the work list with progress per group |
| `work_remove` | Removes work items by key |

Each answer reaches Claude as a new message:

```
DECISION D7: the user answered option 1: "Merge now".
Question: Merge the auth refactor now or after the release?
Raised by: reviewer agent
Act on it now. Do not ask them again.
```

## How it works

It is a single hooks module (`hooks/register.tsx`) using the Claude Code mods API: it registers the six tools and the `/decisions` command, draws the pane, and submits each answer as a prompt. State is kept in the session and saved to the mod store, keyed by the session's folder, so each project has its own decisions and work list. Nothing leaves your machine.

## Contributing

Issues and pull requests are welcome. Check a change with:

```bash
claude plugin validate .
```

## License

MIT
