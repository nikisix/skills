# Jira Ticket Template

> Target size: **1-5 days of work.** If a ticket is bigger than that, split it (see _Breaking it down_ at the bottom).
> Keep every section as short as the caps allow. Tickets are not design docs.

---

## Summary
_What is the business need and why does it matter?_

**Cap: 3-5 sentences (~100 words). No implementation details.**

- Who is affected (user, internal team, customer, etc.)
- What outcome they need
- Why now / what it unblocks

---

## Notes
_Optional. Context and open decisions — not a design._

**Cap: ~200 words, bullet points preferred.**

- Open questions the implementer (or reviewer) needs to resolve
- Links to prior conversations, related tickets, or relevant docs
- Constraints the team has already agreed on

Do **not** put implementation steps here. If you find yourself writing prose paragraphs, you're writing a design doc — move it elsewhere and link.

A high-level context diagram (mermaid) is fine here if it aids understanding — but it must show *the what*, not internal architecture. If it depicts modules, call sequences, or data-layer flows, it's a design doc and doesn't belong.

---

## Acceptance Criteria
_What can a QA tester verify without reading code?_

**Cap: 3-7 items. Each item is an observable outcome.**

- Use plain bullets or Given/When/Then — be consistent within the ticket
- Each criterion should be independently testable
- Write in terms of user-visible behavior, not internal state
- A user-flow (`flowchart`) or state (`stateDiagram-v2`) diagram may accompany the criteria when it makes the expected behavior clearer — it must match what these criteria assert, nothing more

---

## Technical Acceptance Criteria
_Optional. What technically must be true when this is done?_

**Cap: 3-10 items. Outcomes, not instructions.**

- Specific systems / files / endpoints / schemas affected
- Non-functional requirements (perf budgets, security constraints, observability)
- Migration or backfill expectations
- Backward-compat or deprecation expectations

Do **not** include:
- Step-by-step implementation ("first do X, then Y")
- Function signatures or pseudo-code
- Restated user-facing AC dressed up in technical language

---

## Breaking it down

If any of these apply, split the ticket:

- **More than 7 acceptance criteria** → split by user-facing capability
- **Touches multiple subsystems** (e.g. backend + frontend, multiple services) → one ticket per subsystem with a parent epic
- **Summary contains "and then…"** or lists multiple outcomes → those are separate tickets
- **Estimate exceeds 5 days** → carve out a vertical slice that delivers value on its own
- **Requires a spike / unknowns to be resolved first** → make the spike its own ticket

### Splitting patterns

When a ticket (or epic) is too big, use one of these canonical patterns to find a
smaller slice. Each split should still deliver value on its own — prefer a thin
vertical slice over a horizontal layer. (Synthesized from Lawrence, Wake, and the
Humanizing Work story-splitting flowchart.)

- **Workflow steps** — build the start and end of a workflow first; add the middle steps as later tickets.
- **Business-rule variations** — ship a subset of the rules first (e.g. "flexible dates" → one date scheme), add the rest later.
- **Major effort** — when the first variant carries most of the cost, do one variant first, then the rest cheaply (e.g. one payment type, then all).
- **Simple / complex** — do the simple core that delivers most of the value; defer the complications.
- **Variations in data** — handle one kind/source of data first, add other kinds later.
- **Data-entry / interface methods** — ship a basic input first, add the richer UI later.
- **Defer performance** — make it work first ("searching…"), meet the perf budget in a follow-up.
- **Operations (CRUD)** — split a "manage X" story into create / read / update / delete.
- **Break out a spike** — if unknowns block estimation, make answering them its own ticket, then re-split.

---

## Anti-patterns (don't do these)

- Prescriptive implementation walkthroughs — leave room for the implementer to make decisions
- Pasting an LLM-generated design doc as the description
- Mixing business rationale into Technical AC (it belongs in Summary or Notes)
- Acceptance Criteria that only the author can verify (requires reading code, looking at logs, etc.)
- Wall-of-text Summary — if it doesn't fit the cap, the ticket is probably too big
