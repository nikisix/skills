---
name: create-mr
description: >
  Use when a feature branch is ready for a merge request and needs its unit, golden, and accuracy tests gated,
  a code review, and the decisions made during development written into the MR description for review.
  Triggers on /create-mr or a request to open an MR/PR with decisions included.
user-invocable: true
---

# Create MR

Moves merge-request review upstream: a reviewer checks the decisions behind a change, not the generated
code line by line. The skill gates the branch on tests, adds a code review, and puts the feature's decision
log (from the sessions skill) into the description.

**Setup:** the repo needs a `create-mr/create-mr-config.json` at its root (see `examples/tron.create-mr.json`). It holds
the target branch, the description file, the suites, and `reviewers` (added to every MR). The decisions step needs
the sessions skill installed at `~/.claude/skills/sessions`, and the feature's session must be the current
session.

Run the helper as `python3 <skill-dir>/scripts/create_mr.py`. Run every step from inside the repo.

## Steps

Run them in order. Stop at the first failure and report it.

### 1. Tests (gate)

Choose a run label that says why the accuracy run was made, from the branch name and the change, for example
`create-mr-<short-topic>`. Record that choice as a decision (see Decisions below).

```bash
python3 <skill-dir>/scripts/create_mr.py test --label <label> --session <path-to-active-session>
```

- The suites run in order: `unit`, `golden`, `accuracy`. The first failure stops the run.
- **On failure:** the script writes `create-mr/create-mr--failed-tests.md` with the suite, command, exit code, branch and
  HEAD, the active session, and the last 50 lines of output. Stop here. Tell the user the file path. Do not
  continue to review or open an MR. The fix happens in the main session, and then `/create-mr` runs again.
- **On success:** the script writes `create-mr/create-mr--test-results.md`, which records the HEAD tested and whether the
  working tree was clean. Commit the MR's changes before running the gate. `open` refuses to run unless the last
  passing test run was on the current HEAD and the working tree is clean.
- Never run `make golden-record` or the remote `make eval`. Both spend money on AWS or Bedrock. The configured
  suites are offline by design.

### 2. Code review

Invoke the `code-review` skill through the Skill tool, at `medium` level, against the branch diff. Save its
findings as markdown to `create-mr/create-mr--code-review.md`. If it reports no findings, write that sentence instead.

### 3. Summary and decisions

- Write `create-mr/create-mr--summary.md`: a short description of what changed and why, in prose a reviewer can scan.
- Export the decisions from the current session:

  ```bash
  python3 ~/.claude/skills/sessions/scripts/sessions.py decisions > create-mr/create-mr--decisions.md
  ```

  This prints each turn's Decisions block, with the question, who answered it, the choices, and the bold
  selection. If the output is `(no decisions recorded)`, say so in the MR. Do not invent decisions.

### 4. Describe

```bash
python3 <skill-dir>/scripts/create_mr.py describe \
  --summary create-mr/create-mr--summary.md \
  --review create-mr/create-mr--code-review.md \
  --decisions create-mr/create-mr--decisions.md
```

This writes the MR description to the file named by `description_file` in `create-mr/create-mr-config.json`. It sections the
body as Summary, Decisions, Code review, and Test results. Show the user the description and the proposed title.

If the change is over 1000 changed lines, the description must link an explainer diagram in `docs/diagrams/`
(REVIEW.md requirement). Create the diagram and link it here before showing the description. `open` checks for
the link and refuses without it.

**Stop for approval.** Opening an MR is outward-facing, so wait for the user to approve the description and title.

### 5. Open

After the user approves:

```bash
python3 <skill-dir>/scripts/create_mr.py open --title "<title>" [--draft]
```

`open` picks `glab mr create` for GitLab remotes and `gh pr create` for GitHub remotes. It does not push: push
the branch first, or confirm with the user before pushing. Report the MR URL the command prints.

The assignee is the user signed in to `glab` (looked up with `glab api user`). Every username in `reviewers`
from `create-mr/create-mr-config.json` is added as a reviewer. `open` refuses, with a message and no MR, when the working tree
has uncommitted changes, when the last test run was not on HEAD, or when the change is over 1000 lines and the
description has no `docs/diagrams/` link. Fix the cause, then re-run from step 1 (or step 4 for description
changes).

## Decisions

Record every question and choice made during this skill as a structured decision in the session turn log:
the label choice, the code-review level, the title, and any draft choice. Set `answered_by` to `human` when the
user answered, or `agent` when you chose.

## Files this skill writes

All are created in the `create-mr/` folder at the repo root and are not meant for commit. The helper writes a
`.gitignore` inside that folder that ignores everything in it, so the folder never shows up in `git status`. The
folder holds `create-mr--failed-tests.md` (on failure), `create-mr--test-results.md`, `create-mr--code-review.md`,
`create-mr--summary.md`, `create-mr--decisions.md`, the description file, and the config file.

## Common mistakes

- Treating the accuracy row as proof for the change. The accuracy suite scores whatever `LOCAL_EST_DIR` points
  at. If that run predates the change, say so in the summary: the suite passes without testing the change.
- Using the wrong session. `sessions.py decisions` reads the current session, so make sure it is the feature's session.
- Changing the description after approval. Re-run `describe`, then show the user again.
