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
- `open_questions`: asked of {{ME}} and not answered, as objects `{text, category, effort}`; `category`
  is usually `open_question`, `decision` when it needs a meeting to settle.
- Classification. Every action item, follow-up, and open question carries a `category`, one of:
  `decision` (an unresolved item that needs more discussion or a meeting before it can move: a choice
  between options, an escalation, "let's meet on this"; a follow-up whose purpose is to decide something
  is `decision`, not `follow_up`), `commitment` (what {{ME}} committed to, {{ME}}'s new TODOs),
  `waiting_on` (what {{ME}} is waiting on from someone else), `follow_up` (a concrete later task or
  sync with no decision pending), `open_question` (left unresolved, including a disagreement left
  standing). Default for an action item by owner: {{ME}} owns it -> `commitment`, someone else owes it
  -> `waiting_on`; override only when the text clearly says otherwise.
- `effort`: {{ME}}'s own effort to clear the item: `S` under an hour, `M` a half day to a day, `L` more.
  `null` for items others own unless the text implies {{ME}}'s share.
- Tickets in play (key · task / sub-task):
{{TICKETS}}
  Set `jira` to one of these keys only when the item is clearly work on that ticket, keep a key that was
  written or said, otherwise `null`. Never invent a key.
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
