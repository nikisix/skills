You classify items that were already extracted from one of {{ME}}'s meeting or chat digests, for
{{ME}}'s action-items ledger. Do not add, drop, merge, or reword items.

Return ONLY a JSON object of this shape, with exactly one entry per input item, in input order:

{"action_items": [{"category": "...", "effort": "...", "jira": "..."}, ...],
 "follow_ups": [{"category": "...", "effort": "..."}, ...],
 "open_questions": [{"category": "...", "effort": "..."}, ...]}

Rules:
- `category` is one of: `decision` (an unresolved item that needs more discussion or a meeting before
  it can move: a choice between options, an escalation, "let's meet on this"; a follow-up whose purpose
  is to decide something is `decision`, not `follow_up`), `commitment` (what {{ME}} committed to,
  {{ME}}'s new TODOs), `waiting_on` (what {{ME}} is waiting on from someone else), `follow_up` (a
  concrete later task or sync with no decision pending), `open_question` (left unresolved, including a
  disagreement left standing). Default for an action item by owner: {{ME}} owns it -> `commitment`,
  someone else owes it -> `waiting_on`; override only when the text clearly says otherwise.
- `effort`: {{ME}}'s own effort to clear the item: `S` under an hour, `M` a half day to a day, `L`
  more. `null` for items others own unless the text implies {{ME}}'s share.
- `jira` (action items only): keep the key the item already has. Otherwise set one of the tickets in
  play below only when the item is clearly work on that ticket, else `null`. Never invent a key.
- Tickets in play (key · task / sub-task):
{{TICKETS}}

Digest: {{TITLE}} ({{DATE}}, {{SOURCE}}; attendees: {{ATTENDEES}})
Summary: {{SUMMARY}}

Items:
{{ITEMS}}
