---
name: sessions
description: >
  Direct session management. Invoke on /sessions <cmd> or when user says start/end/switch/scan/resume/current a session. Maps cleanly to Python script calls with minimal reasoning.
user-invocable: true
subagent: true
model: haiku
---

# Sessions

Maintains a central per-project session log — prompts, decisions, file changes, and
blockers — so the work we do together is never lost between conversations. Sessions
are stored in a configurable central directory (default `~/code/sessions/<project>/`),
shared across all git worktrees for the same repo.

The helper script lives at:
```
/Users/six/.claude/skills/sessions/scripts/sessions.py
```

Config file (create if absent):
```
~/.claude/skills/sessions/config.yaml
```

---

## Direct Command Mapping

Each invocation maps directly to a single Python call. No decision trees—just execute:

### /sessions set-sessions-dir \<dir\>  (alias: /sessions set-project \<dir\>)

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py set-sessions-dir <dir>
```

Create `<dir>` inside `$sessions_root` and make it the active project folder for this
Claude session. Subsequent bare `init <name>` calls will use this folder. Print the
created directory path.

### /sessions init \<name\>

Three equivalent forms — all create a numbered session file and set it as current:

```bash
# Use auto-detected (or set-sessions-dir) project folder
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py init <name>

# Explicit folder + name (two args)
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py init <dir> <name>

# Slash notation (single arg with /)
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py init <dir>/<name>
```

When `<dir>` is provided, it is created if absent and set as the active project for
this session. Print the created file path. If user asks to scan prior sessions first,
run `/sessions scan` separately.

### /sessions scan

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py scan
```

Print all session filenames and overviews.

### /sessions current

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py current
```

Print active session file path and overview.

### /sessions end

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py flush
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py end
```

Flush pending turn, then end the session. Confirm the path.

### /sessions switch \<n\>

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py flush
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py switch <n>
```

Where `<n>` is session number or slug fragment. Flush first, then switch.

### /sessions resume \<n\>

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py flush
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py resume <n>
```

Where `<n>` is session number or slug fragment. Flush first, then resume.

### /sessions detect-project

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py detect-project
```

Print auto-detected project name and sessions directory.

### /sessions summarize [spec]

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py summarize [spec]
```

Emit session data scoped to `spec`, then **synthesize a git-commit-style summary** from the output.

**Argument forms:**

| Spec | Behavior |
|------|----------|
| *(none)* | Print the `## Overview` section verbatim — no synthesis needed |
| `a-b` | Emit turns a through b (inclusive) |
| `a-` | Emit turns a through the last turn |
| `-n` | Emit the last n turns |
| `YYYY-MM-DD` | Emit all turns since that date (inclusive) |

**No-arg:** the script prints the Overview text. Print it directly to the user.

**With spec:** the script prints a JSON object:
```json
{
  "session": "<slug>",
  "range_desc": "<human-readable range>",
  "turns": [
    {"num": 1, "timestamp": "YYYY-MM-DD HH:MM", "block": "<raw turn markdown>"}
  ]
}
```

Read the `block` field of each turn to extract `### Summary`, `### Files Changed`,
`### Decisions`, and `### Errors/Blockers`. Then write a git-commit-style message:

- **Subject line** (imperative, ≤72 chars): a synthesized phrase describing what changed
  across all selected turns. Example: `Add summarize command to sessions skill`
- **Blank line**
- **Body**: bullet points grouped by theme (not per-turn). Prefer 3–7 bullets.
- **Files changed** footer if any files appear across the turns.
- **Decisions** footer if notable decisions appear.

Print the full commit message to the user. Do not add any framing text around it.

---

## Turn-End Logging (Every Turn)

**After every response**, write the pending turn JSON as your final action before
finishing. The Stop hook reads this file and appends the formatted turn to the
session note.

Get the correct path first:

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py pending-path
```

Write the JSON to that path. The filename includes the current `CLAUDE_CODE_SESSION_ID` (e.g.
`.pending-turn-8670aafb-….json`), so parallel sessions each write to their own file without
clobbering each other. The Stop hook reads the same session-scoped file, so the turn always
lands in the right session note.

Structure:

```json
{
  "prompt": "<verbatim user prompt>",
  "summary": "<1–2 sentences: what you did and why>",
  "files_changed": [
    {"path": "relative/path/to/file.py", "action": "created|edited|deleted"}
  ],
  "decisions": [
    "Chose X over Y because Z"
  ],
  "errors_blockers": [
    "Error: could not find file X — resolved by creating it"
  ],
  "overview": "<updated one-paragraph summary of the entire session so far>"
}
```

- Omit empty arrays (`files_changed`, `decisions`, `errors_blockers`).
- The `overview` field replaces the `## Overview` section in the session file.
  Keep it to one paragraph; write it as if explaining the session to a future
  version of yourself who needs to decide whether this session is relevant.
- The `summary` field is for this turn only; `overview` covers the whole
  session.
- For `/session-end` turns, include `"session_end": true` at the top level.

**Why this matters:** the Stop hook is the reliable write path. Even if
context is compacted or another skill triggers, the hook fires and processes
whatever is in the pending file. Never skip this write.

---

## Session File Format

```markdown
# <Session Title>
<!-- Update H1 if the session focus shifts significantly -->

## Overview

One paragraph. Updated each turn via the `overview` field in the pending JSON.

---

*Started: YYYY-MM-DD HH:MM*

## Turn 1 — YYYY-MM-DD HH:MM

### Prompt

Verbatim user prompt.

### Summary

What you did and why — one or two sentences.

### Files Changed

| File | Action |
|------|--------|
| `path/to/file.py` | edited |

### Decisions

- Chose approach X because Y
- Decided not to refactor — out of scope

### Errors/Blockers

- Build failed due to missing dep Z — resolved by installing it

---

*Ended: YYYY-MM-DD HH:MM*
```

**Formatting guidelines:**
- Target 120-column line width; exceed it only for tables or mermaid diagrams
  that can't be shortened without losing meaning
- Use mermaid diagrams to illustrate flows, architectures, or sequences
- Use tables for comparisons, option lists, file change logs
- Use markdown links when referencing files or prior sessions

---

### /sessions capture \<proj\> \<name\>

Captures the current Claude Code session as a session file. Steps:

**1. Read the transcript:**
```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py read-transcript
```
(Uses `$CLAUDE_CODE_SESSION_ID` automatically. Output: JSON with `title`, `turns`, `files_changed`.)

**2. Get the target file path:**
```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py capture-path <proj> <name>
```

**3. Synthesize and write the session file.**

Using the transcript JSON + your own conversation context, generate a full session markdown
file and write it to the path from step 2 using the Write tool. Use this format:

```markdown
# <Title from aiTitle or derived from name>

## Overview

<One paragraph summarizing the entire session — what was attempted, decided, and changed.>

---

*Captured: YYYY-MM-DD HH:MM*

## Turn 1 — <timestamp from first user message>

### Prompt
<verbatim or lightly cleaned user prompt>

### Summary
<1–2 sentences: what was done and why>

### Files Changed
| File | Action |
|------|--------|
| `path/to/file` | edited |

### Decisions
- <any notable decisions from this turn>

---
...repeat for each real user↔assistant turn...
```

- Skip system-injected turns (command outputs, /model switches, interrupt notices).
- Group each real user prompt with the assistant work that followed it as one Turn.
- Files changed: include only turns where actual file edits happened.
- The file is NOT set as the active session — it's a snapshot, not an ongoing session.

---

## Reviewing Prior Sessions

When user asks about previous work:

1. Run `/sessions scan` to list overviews
2. Identify relevant sessions by filename slug + overview text
3. Offer to read: *"Session N (`slug`) looks relevant — want me to read it in full?"*
4. Only read full file after explicit user confirmation

This avoids context pollution while keeping past work discoverable.
