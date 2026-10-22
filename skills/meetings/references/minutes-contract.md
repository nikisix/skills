# Minutes contract (what the digest must capture)

Adapted from `github/awesome-copilot` → `skills/meeting-minutes` (extraction schema) and
`microsoft/cat-agent-skills` → `meeting-analyzer` (firmness scale, "missing owner/date is a finding").
The hidden-layer analysis from meeting-analyzer (tensions, personas) is deliberately **not** part of
this contract: it is noise in a committed worklog.

| Field | Rule |
|---|---|
| `summary` | 1–3 sentences: objective and high-level outcome. |
| `decisions[]` | Only things that were decided. `firmness`: `committed` (explicit agreement), `leaning` (preference stated, not closed), `discussed` (raised, no position). Never upgrade a discussion to a decision. `by` = who made/approved it, or `null`. |
| `action_items[]` | Task + `owner` (from the roster, or `null`) + `due` (ISO date if one was stated or clearly implied like "by Friday", else `null`). Missing owner/date is recorded as `null`, never guessed. `jira` = an explicitly mentioned DEV-key or `null`. `ticket_worthy` = engineering work of roughly half a day or more with no Jira key. |
| `follow_ups[]` | Future meetings/syncs that were proposed ("let's sync next Wednesday"). `when` = resolved ISO date relative to the meeting date, or `null`. |
| `open_questions[]` | Questions raised and not answered. |
| `source_quality` | `verbatim` (real transcript), `captions` (live captions, may be lossy), `notes` (someone's notes). |

Relative dates resolve against the meeting `date` ("Friday" = the next Friday on/after the meeting date;
"next Wednesday" = the Wednesday of the following week).
