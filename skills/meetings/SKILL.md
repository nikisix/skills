---
name: meetings
description: Turn meeting transcripts (Teams via m365, or hand-pasted Slack/Teams text) into org-mode worklog blocks, dated follow-ups, and Jira ticket suggestions; weekly arXiv scan against open work items. Triggers on /meetings, "digest this meeting", "meeting transcript", "arxiv scan for my work items".
---

# meetings

Two-stage pipeline. **Stage 1** (LLM): a transcript becomes a JSON digest that must validate against
`references/digest-schema.json` (contract: `references/minutes-contract.md`). **Stage 2**
(deterministic Python): the digest is rendered into org text and added — never edited — into the
org files with greppable `:auto:` markers. Runbook with policies and rollback lives in the org repo:
`~/org/ringmaster/CLAUDE-meetings.md`.

Skill source: `~/code/skills/skills/meetings` (symlinked into `~/.claude/skills/meetings`). All
commands run through `uv`:

```bash
SKILL=~/code/skills/skills/meetings
RUN="uv run --project $SKILL python $SKILL/scripts"
```

## Commands

| `/meetings …` | Does | Invocation |
|---|---|---|
| `digest <file>` | normalize one inbox file and produce its JSON digest | `$RUN/normalize.py <file> -o /tmp/n.txt && $RUN/digest.py /tmp/n.txt -o <org>/meetings/digests/<stem>.json` |
| `write <digest.json>` | render + insert into worklog (merge/new heading, dated follow-ups) | `$RUN/write_org.py <digest.json> --key <key> [--dry-run]` |
| `suggest <digest.json>` | append ticket suggestions | `$RUN/suggest.py <digest.json> [--dry-run]` |
| `run` | the whole daily pass over `meetings/inbox/` | `bash $SKILL/scripts/run.sh daily` |
| `fetch` | pull new Teams transcripts for my own meetings into the inbox | `$RUN/fetch_teams.py [--dry-run]` |
| `slack` | pull yesterday's DMs / group DMs / listed channels into the inbox as `kind: chat` files | `$RUN/fetch_slack.py [--dry-run] [--today YYYY-MM-DD]` |
| `arxiv` | weekly research scan against open work items | `$RUN/arxiv_scan.py [--dry-run]` |
| `status` | what is in inbox / digests / state | `bash $SKILL/scripts/run.sh status` |

Always prefer `--dry-run` first when the user is present; the scheduled job runs without it.

## When invoked interactively

1. If the user pasted transcript text instead of a file: save it to
   `<org>/meetings/inbox/YYYY-MM-DD[-HHMM]-<slug>.txt` (ask for the date/title if the text does not
   say), optionally with front-matter (`title:`, `date:`, `source:`, `attendees:`), then run `digest`.
2. Show the digest's action items and follow-ups in a short table before `write`; then `write --dry-run`,
   then the real write. The scheduled job skips the preview.
3. Never edit `worklog.org` by hand in this skill — the writer owns insertion so reruns stay idempotent.

## Headless digestion

`digest.py` calls `claude -p --output-format json --max-turns 1 --tools ""` with the filled
`references/digest-prompt.md` on stdin and reads the `result` entry of the returned message list.
Invalid JSON is retried once with the validation errors appended; a second failure leaves
`digests/<stem>.raw.txt` and exit code 1.

## Slack chat days

`scripts/fetch_slack.py` pulls each *completed* local day of your DMs, group DMs, and the channels
listed in `meetings/slack.yaml` into `inbox/YYYY-MM-DD-slack-<name>.txt` with `kind: chat`. The chat
prompt (`references/chat-prompt.md`) is handed the open work items from `worklog.org` and
`tron-tasks.org` and returns only *new* action items, which land as `**** TODO` lines under a
`*** Slack #<channel> :chat:auto:` block inside the day's single `** Slack :chat:auto:` group. Token: `$SLACK_USER_TOKEN` or the keychain item
`meetings-slack`. `run.sh daily` runs it after the Teams fetch; it is skipped when `slack.yaml` is absent.

## Exit codes (writers)

`0` wrote · `2` nothing to do (already processed) · `3` mtime guard (file saved < 15 min ago; use
`--force` interactively) · `1` error.
