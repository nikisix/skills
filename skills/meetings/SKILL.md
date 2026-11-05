---
name: meetings
description: Turn meeting transcripts (Teams via m365, or hand-pasted Slack/Teams text) into org-mode worklog blocks, dated follow-ups, Jira ticket suggestions, and rows in the action-items.org ledger; done-sync propagates ticked rows back to the worklog and tron-tasks; weekly arXiv scan against open work items. Triggers on /meetings, "digest this meeting", "meeting transcript", "action items", "ledger", "arxiv scan for my work items".
---

# meetings

Two-stage pipeline. **Stage 1** (LLM): a transcript becomes a JSON digest that must validate against
`references/digest-schema.json` (contract: `references/minutes-contract.md`). **Stage 2**
(deterministic Python): the digest is rendered into org text and added — never edited — into the
org files with greppable `:auto:` markers, and every item also lands as a row in `action-items.org`.
The one deliberate exception to "never edited" is done-sync (`sync_done.py`): a DONE cell the user
fills in the ledger flips the worklog item to `DONE` and moves the tron task. Runbook with policies
and rollback lives in the org repo: `~/org/ringmaster/CLAUDE-meetings.md`.

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
| `fetch` | pull new Teams transcripts into the inbox: meetings I organized (calendar) and any meeting chat I am in (chats route) | `$RUN/fetch_teams.py [--dry-run]` |
| `slack` | pull yesterday's DMs / group DMs / listed channels into the inbox as `kind: chat` files | `$RUN/fetch_slack.py [--dry-run] [--today YYYY-MM-DD]` |
| `arxiv` | weekly research scan against open work items, filed in `arxiv.org` | `$RUN/arxiv_scan.py [--dry-run]` |
| `status` | what is in inbox / digests / state, plus ledger counts | `bash $SKILL/scripts/run.sh status` |
| `done` | propagate checked DONE cells in `action-items.org` to the worklog item and the tron task | `bash $SKILL/scripts/run.sh done [--dry-run]` |
| `ledger` | counts per category: open / done / untracked rows; `--reformat` re-wraps every table to the 140-column layout | `bash $SKILL/scripts/run.sh ledger [--reformat]` |
| `ledger-backfill` | one-time: classify digests on disk, row every landed item | `bash $SKILL/scripts/run.sh ledger-backfill [--since YYYY-MM-DD] [--dry-run]` |

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

## Action items ledger

Every action item, follow-up, and open question in a digest carries a `category` (`decision`,
`commitment`, `waiting_on`, `follow_up`, `open_question`) and an `effort` (`S`/`M`/`L`/null, kept in
the digest only). The
worklog headline is tagged `:<category>:auto:` and the item is appended as a row to that category's
table in `<org>/action-items.org` (`| DONE | WHEN | WHO | WHAT |`, lines at most 140 wide, a
long WHAT continued on rows whose other cells are blank). The row's identity is the last org link in
WHAT (`[[file:worklog.org::*<headline prefix>][↗]]`, the headline cut at a word boundary to 56
characters), recorded in `state.json` under `ledger`. The user ticks DONE by hand during triage; `done` (run first in `daily`) flips the worklog
item and moves the tron task to the bucket the DONE word names (`x` = In Review; see the runbook
table). `ledger-backfill` classifies digests written before `category` existed
(`references/classify-prompt.md`) and rows the items that were landed; run it once.

## Exit codes (writers)

`0` wrote · `2` nothing to do (already processed) · `3` mtime guard (file saved < 15 min ago; use
`--force` interactively) · `1` error.
