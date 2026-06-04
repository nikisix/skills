---
name: session-new
description: >
  Manage Claude Code session notes in .claude/sessions/. Use whenever the user
  types /session-new (start), /session-end (end), /session-switch (switch),
  /session-scan (list all sessions), /session-current (show active session), or
  /session-resume (re-open an ended session), says "start a new session", "begin
  logging", "end this session", "switch sessions", "list my sessions", "what session
  is active", "resume session", or asks to review prior session notes. Also trigger
  proactively if the user asks what was discussed in a previous session or wants a
  recap of prior work.
user-invocable: true
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

## On /session-new

Run these steps in order:

### 0. Detect and confirm the project

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py detect-project
```

Present the output to the user:
> "Sessions for this repo will be stored in `<sessions dir>`. Does that look right?"

If the user wants a different project name, ask them to add a `project_aliases` entry
to `~/.claude/skills/sessions/config.yaml` (see config docs) and re-run `/session-new`.

### 1. Surface prior sessions

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py scan
```

If sessions exist, present each filename and its overview paragraph. Ask the
user whether any are relevant to what they're about to work on. **Do not read
an entire session file into context without asking first** — overviews exist
precisely to avoid context pollution on fresh tasks.

### 2. Name the session

Based on the user's first message or stated intent, propose a short kebab-case
slug summarizing the session's essence (e.g. `api-auth-refactor`,
`onboarding-debug`, `sessions-skill-creation`). Ask the user to approve or
adjust it, then run:

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py init <approved-name>
```

Confirm the file that was created (the path is printed by the `init` command).

---

## On /session-end

Ends the active session cleanly. Run these steps:

### 1. Write the final pending turn

Before ending, write `.claude/sessions/.pending-turn.json` for the current turn
(same as turn-end logging below) — include `"session_end": true` in the JSON so
the stop hook knows to finalize the session after appending the turn.

### 2. Flush immediately

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py flush
```

This commits the pending turn right now rather than waiting for the stop hook.
The stop hook will see no pending file and do nothing.

### 3. End the session

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py end
```

This appends `*Ended: YYYY-MM-DD HH:MM*` to the session file and clears the
`.current-session` pointer. Confirm the session path that was ended.

---

## On /session-scan

Lists all sessions with their overviews:

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py scan
```

Present the output to the user. If any session looks relevant to what they're
working on, offer to read it in full — but only load it after they confirm.

---

## On /session-current

Shows the active session file and its current overview:

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py current
```

Report both the file path and the overview to the user. If there is no active
session, say so and offer to start one with `/session-new`.

---

## On /session-resume

Re-opens an ended session as the active session. Run these steps:

### 1. Flush any pending turn for the current session

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py flush
```

### 2. List available sessions (if no target was given)

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py scan
```

Present each session's filename and overview, then ask the user which one to resume.

### 3. Resume

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py resume <n>
```

Where `<n>` is the session number (e.g. `3`) or a slug fragment. This sets the
session as current **and** appends `*Resumed: YYYY-MM-DD HH:MM*` to the file so
the history shows the gap. Confirm the path that is now active.

---

## On /session-switch

Switches the active session to an existing one. Run these steps:

### 1. Flush the current turn first

Before switching, write and flush the pending turn for the current session so
it lands in the right file:

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py flush
```

### 2. List available sessions

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py scan
```

Present each session's filename and overview. Ask the user which session to
switch to.

### 3. Switch

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py switch <n>
```

Where `<n>` is the session number (e.g. `3`) or a slug fragment. Confirm the
session that is now active.

---

## Turn-End Logging (Every Turn)

**After every response**, write the pending turn JSON as your final action before
finishing. The Stop hook reads this file and appends the formatted turn to the
session note.

Get the correct path first:

```bash
python3 /Users/six/.claude/skills/sessions/scripts/sessions.py pending-path
```

Write the JSON to that path (e.g. `/Users/six/code/sessions/my-repo/.pending-turn.json`).

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

## Reviewing Prior Notes

When the user asks about previous work, or when beginning a new session:

1. Run `scan` to get overviews
2. Identify sessions likely to be relevant (by filename slug + overview text)
3. Offer to read specific sessions: *"Session 3 (`api-auth-refactor`) looks
   relevant — want me to read it in full?"*
4. Only load the file after explicit confirmation

This keeps fresh sessions clean while making prior context available on demand.
