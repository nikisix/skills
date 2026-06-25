# sessions

A Claude Code skill that maintains a persistent, per-project session log across
conversations. Every prompt, decision, file change, and blocker is recorded to a
markdown file so work is never lost between sessions.

## How it works

Session notes live in `~/code/sessions/<project>/` (configurable). Claude writes a
pending turn JSON at the end of each response; a Stop hook appends the formatted turn
to the active session file. Sessions are numbered sequentially per project and stored
as human-readable markdown.

```
~/code/sessions/
  my-project/
    1-auth-refactor.md
    2-api-cleanup.md
  other-project/
    1-setup.md
```

## Commands

| Command | Description |
|---------|-------------|
| `/sessions init <name>` | Create a new session in the current project |
| `/sessions init <dir> <name>` | Create a session in an explicit project folder |
| `/sessions init <dir>/<name>` | Same via slash notation |
| `/sessions set-sessions-dir <dir>` | Create project folder and set as active for this session |
| `/sessions set-project <dir>` | Alias for `set-sessions-dir` |
| `/sessions scan` | List all sessions with overviews |
| `/sessions current` | Show the active session path and overview |
| `/sessions end` | Flush pending turn and end the session |
| `/sessions switch <n>` | Switch active session (flush first) |
| `/sessions resume <n>` | Re-open an ended session |
| `/sessions merge <src> <tgt>` | Append all turns from src into tgt, renumber, delete src |
| `/sessions merge <src> <tgt> --keep` | Same but keep source file |
| `/sessions summarize` | Print the session overview |
| `/sessions summarize <spec>` | Synthesize a git-commit-style summary for a turn range |
| `/sessions capture <proj> <name>` | Snapshot the current transcript as a session file |
| `/sessions detect-project` | Show auto-detected project name and sessions dir |

### Summarize specs

| Spec | Turns selected |
|------|----------------|
| *(none)* | Returns `## Overview` verbatim |
| `a-b` | Turns a through b (inclusive) |
| `a-` | Turns a through last |
| `-n` | Last n turns |
| `YYYY-MM-DD` | All turns since that date |

## Configuration

Config file: `~/.claude/skills/sessions/config.yaml`

```yaml
sessions_root: ~/code/sessions   # where project folders live

project_aliases:
  claude-skills: sessions        # rename a repo's session folder
```

## Session file format

```markdown
# Auth Refactor

## Overview

One-paragraph description updated each turn.

---

*Started: 2026-06-24 10:00*

## Turn 1 — 2026-06-24 10:05

### Prompt
Verbatim user prompt.

### Summary
What was done and why.

### Files Changed
| File | Action |
|------|--------|
| `auth/middleware.py` | edited |

### Decisions
- Chose JWT over sessions because stateless scaling

---

*Ended: 2026-06-24 11:30*
```

## Design history

The skill started as a multi-step decision-tree flow (detect project → scan → name →
init). It was refactored to a direct command-mapping model where each `/sessions <cmd>`
maps 1:1 to a Python script call with no intermediate reasoning — reducing latency and
simplifying the prompt.

Key additions over time:
- **Shell wrapper** (`sessions.sh`) for direct terminal use
- **`capture`** — snapshots the current Claude Code conversation transcript (`~/.claude/projects/**/*.jsonl`) into a session file automatically, rather than requiring manual overview input
- **`merge`** — combines two sessions into one with automatic turn renumbering
- **`summarize`** — emits selected turns as JSON; Claude synthesizes a git-commit-style message with an imperative subject line
- **`set-sessions-dir` / `set-project`** — explicitly targets a project folder within `sessions_root`, sets it active for the current Claude session
- **Parallel session support** — pointer files are scoped by `CLAUDE_CODE_SESSION_ID` so multiple concurrent Claude sessions don't clobber each other
