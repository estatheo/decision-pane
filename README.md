# Decisions panel for Gas City and Claude Code

**Using Codex?** Run the local browser panel below. It uses the same Gas City
decisions and work list as the Claude Code pane, without starting another model.
The docked `/decisions` pane remains a Claude Code integration; the browser panel
does not add a native sidebar inside Codex.

## Local panel for Codex and other agents

Requires Python 3.9+ and Gas City (`gc`) on your PATH. From a checkout of this
repository, run:

```bash
python3 gascity/lib/panel.py --city /absolute/path/to/your-city
```

It prints a localhost URL and opens your browser. Keep that process running;
Ctrl-C stops it. Use `--no-open` to print the URL only, or `--port 8765` for a
fixed port. No Python packages, API key, paid service or model session is needed.

When the city's pinned decisions pack includes this version, you can also run
`gc decisions panel` from inside the city. Existing pins must be updated through
your normal pack upgrade process; do not edit Gas City's imported cache.

The panel shows pending decisions, recommendations, option details, a custom
answer field, **Discuss first**, **Later**, and grouped work progress. Keys
`1`–`9`, `D` and `L` work when focus is outside a form control. It refreshes every
eight seconds while visible and preserves an answer being typed. Later only
changes this browser tab's queue; it does not answer or withdraw anything.

Answers are saved to the original bead and sent to its `reply_to` agent through
`gc mail send --notify`. If delivery fails, the saved choice stays visible with
**Retry delivery**. A saved answer cannot be replaced with another choice.
Repeat submissions skip already delivered answers; retries also use Gas City's
mail deduplication key (best effort if the configured mail provider lacks dedup
support). Decisions created only for a Claude session need a `reply_to` recipient
before the browser panel can deliver them. Use one answering interface per city
at a time; simultaneous submissions from the Claude pane and browser are not an
atomic cross-client operation.

The server binds only to `127.0.0.1`, checks Host/Origin, and requires a per-run
token for answers. It does not expose a shell or an arbitrary command endpoint.
Do not expose it through a tunnel or reverse proxy. This is a local interface,
not a multi-user hosted service. If Gas City is unavailable, the last view stays
on screen with an error; no empty successful state is substituted.

To check the browser panel and its answer-delivery contract:

```bash
python3 -m unittest discover -s tests -v
node tests/panel-ui.cjs  # optional UI regression check; Node 18+
gc lint gascity
```

## Claude Code pane

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
- **Works with Gas City agents on any model.** Agents running on GPT (Codex) or anything else post with `gc decisions ask` and get your answer back by `gc mail`. See [Gas City](#gas-city-any-model-gpt-included).

## Install

You need Claude Code with mods (function hooks), version 2.1.300 or later.

In a Claude Code session, type:

```
/plugin install decisions --marketplace estatheo/decision-pane
```

Press `y` to add the marketplace, then pick a scope (just you, or this project). Or from a shell:

```bash
claude plugin install decisions --marketplace estatheo/decision-pane
```

That's it. Start a new session and Claude has the tools.

### Run it from a local copy

```bash
git clone https://github.com/estatheo/decision-pane
claude --plugin-dir ./decision-pane
```

To load it in every session, set `CLAUDE_CODE_PLUGIN_DIRS=/path/to/decision-pane` in your shell or in the `env` block of `~/.claude/settings.json`.

## Gas City (any model, GPT included)

In a [Gas City](https://github.com/gastownhall/gascity) the decisions and the work list can live in the city's beads instead of one Claude Code session. Then every agent in the city posts to your panel, whichever model runs it, and each answer goes back to the agent that asked, by `gc mail`, with a wake-up if it is asleep.

```
 GPT / Codex agent ──gc decisions ask──┐
 Claude agent ─────mcp__decisions__post┼──▶ city beads ──▶ your Decisions panel
 any agent ────────gc decisions work───┘                        │ you press 1
                       ◀── gc mail "DECISION hq-4f2: ..." ──────┘
```

Three steps, run once per city:

**1. Give the agents the commands.** Import the pack from this repo into the city:

```bash
cd /path/to/your-city
gc import add https://github.com/estatheo/decision-pane/tree/main/gascity --name decisions
```

That adds `gc decisions ask`, `work`, `list` and `withdraw` (`--name` sets the `decisions` in those commands). They need `python3` on the machine.

**2. Tell every agent to use them.** Add the pack's prompt fragment to `city.toml`:

```toml
[workspace]
global_fragments = ["decisions"]   # keep your existing entries in the list
```

**3. Point your panel at the city.** Install the mod in the Claude Code session where you work (see [Install](#install)), then set its store to beads, in `/config` or in `~/.claude/settings.json`:

```json
{ "pluginConfigs": { "decisions@estatheo": { "options": { "store": "beads" } } } }
```

Start that session inside the city folder so `gc` finds the city. If `gc` is not on your `PATH`, set `gcPath` too. If the city has no Claude Code session, use the local browser panel above. The docked terminal pane itself needs Claude Code.

What agents run:

```bash
gc decisions ask "Merge the auth refactor now or after the release?" \
  --context "Tests pass. The release branch is cut on Friday." \
  --option "Merge now :: lands in this release" --option "Wait for the release" --recommend 1

gc decisions work API-212 --title "Rate limits on the public API" --status running --note "writing docs"
gc decisions work API-212 --status review
```

Decisions are beads labelled `decision` and work items beads labelled `work`, with the details in the bead's metadata, so they also show in `gc bd list` and the Gas City dashboard.

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

It is a single hooks module (`hooks/register.tsx`) using the Claude Code mods API: it registers the six tools and the `/decisions` command, draws the pane, and submits each answer as a prompt.

- **local store (the default):** state is saved to the Claude Code mod store, keyed by the session's folder, so each project has its own decisions and work list.
- **beads store:** the panel reads the city's beads every few seconds through `gc bd`, writes answers back to the bead, and sends them by `gc mail` to the agent that asked. The `gascity/` folder is a Gas City pack with the `gc decisions` commands (`gascity/lib/decisions.py`, standard library only) and the agents' prompt fragment.

Nothing leaves your machine.

## Contributing

Issues and pull requests are welcome. Check a change with:

```bash
claude plugin validate .
gc lint gascity
```

## License

MIT
