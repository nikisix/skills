You are extracting a structured digest from a meeting transcript. Output ONLY one JSON object that
validates against the schema below. No prose before or after it, no markdown fence.

The person reading this digest is {{ME}}. The roster of known people is: {{ROSTER}}.
For `owner`, `by`, `attendees`, and `with`, use a roster name exactly as written. A person who is
not on the roster but is named in the header or speaks in the transcript is written with their name
exactly as it appears there (e.g. "Mitch Slavens"). Use `null` only when nobody was named.
Never invent names, dates, or commitments.

Rules:
- `summary`: 1–3 sentences on the objective and outcome.
- `decisions`: only things decided. `firmness` is `committed` (explicit agreement), `leaning`
  (preference, not closed), or `discussed` (raised, no position). Do not upgrade discussion to decision.
- `action_items`: task + owner + due date. A missing owner or date is `null` — that is a finding, not a
  gap to fill. `jira` is a `DEV-NNNN` key only if one was said. `ticket_worthy` is true only for
  engineering work of roughly half a day or more that has no Jira key.
- `follow_ups`: proposed future meetings/syncs that involve {{ME}} (they become {{ME}}'s TODOs); a
  sync between two other people is not a follow-up. Resolve relative dates against the meeting date
  ("Friday" = next Friday on/after the meeting date; "next Wednesday" = the following week's Wednesday).
- `open_questions`: raised and unanswered.
- `source_quality`: `verbatim` for a real transcript, `captions` for live captions, `notes` for notes.
- Use the metadata header for `title`, `date`, `source`, and `attendees` unless the transcript clearly
  contradicts it. Header attendees may be full names ("Abhi Gurudwar"): map each to its roster name
  when the first name is on the roster, otherwise keep the full name as written. Add attendees who
  speak in the transcript if they are in the roster.
- A `source: teams` transcript is `verbatim` even though Teams labels it "AI-generated"; a `.txt`
  pasted from Slack side-by-side captions is `captions`.

JSON schema:
{{SCHEMA}}

Metadata header:
{{HEADER}}

Transcript:
<<<
{{TRANSCRIPT}}
>>>
