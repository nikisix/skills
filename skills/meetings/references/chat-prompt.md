You are extracting what matters to {{ME}} from one day of Slack messages in one conversation. Output
ONLY one JSON object that validates against the schema below. No prose before or after it, no fence.

The roster of known people is: {{ROSTER}}. For `owner`, `by`, `attendees`, and `with`, use a roster name
exactly as written; a person not on the roster is written as named in the messages. Use `null` only when
nobody was named. Never invent names, dates, or commitments.

These work items are ALREADY TRACKED in {{ME}}'s worklog and task list:
{{OPEN_ITEMS}}

Rules:
- `summary`: one sentence on what the conversation was about.
- `action_items`: only things {{ME}} agreed to do or was asked to do, plus things others committed to
  that {{ME}} is waiting on. Skip an item only when a tracked item above is the SAME deliverable; a new
  deadline, a new recipient, or a narrower sub-task of a tracked item is new and must be included.
  Skip chatter, FYIs, and questions that were answered in the thread. A missing owner or date is `null`.
  `jira` is a `DEV-NNNN` key only if one was written. `ticket_worthy` is true only for engineering work
  of roughly half a day or more with no Jira key.
- `decisions`: only things decided in the messages, with `firmness` committed / leaning / discussed.
- `follow_ups`: proposed meetings or syncs that involve {{ME}}; resolve relative dates against the date
  in the header ("Friday" = next Friday on/after that date).
- `open_questions`: asked of {{ME}} and not answered.
- `source_quality`: `verbatim`.
- Use the metadata header for `title`, `date`, `source`, and `attendees`.

JSON schema:
{{SCHEMA}}

Metadata header:
{{HEADER}}

Messages:
<<<
{{TRANSCRIPT}}
>>>
