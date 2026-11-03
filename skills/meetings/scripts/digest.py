"""Run the digest prompt through `claude -p` and validate the JSON against the schema.

Usage: digest.py <normalized.txt> -o <digests/stem.json>
       digest.py --validate-only <digest.json>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import jsonschema

from config import Paths, add_org_dir_arg, parse_args_or_none, paths_from_args
from orgfile import Heading, OrgDoc
from people import People

SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = SKILL_DIR / "references" / "digest-schema.json"
PROMPT_PATH = SKILL_DIR / "references" / "digest-prompt.md"
CHAT_PROMPT_PATH = SKILL_DIR / "references" / "chat-prompt.md"
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CATEGORIES = ("decision", "commitment", "waiting_on", "follow_up", "open_question")
EFFORTS = ("S", "M", "L")


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def validate(d: dict) -> list[str]:
    validator = jsonschema.Draft202012Validator(load_schema())
    errors = []
    for e in sorted(validator.iter_errors(d), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in e.path) or "<root>"
        errors.append(f"{where}: {e.message}")
    return errors


def extract_json(text: str) -> dict:
    """First balanced top-level {...} object in `text` (string-aware)."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object found in model output")


def normalize_digest(d: dict, people: People) -> dict:
    """Fill `category` / `effort` on a digest written before they existed (in place, returned). An
    action item is `commitment` when it is mine, `waiting_on` otherwise; a follow-up is `follow_up`; a
    bare-string open question becomes `{text, category: open_question, effort: null}`."""
    for item in d.get("action_items") or []:
        item.setdefault("category", "commitment" if people.is_me(item.get("owner")) else "waiting_on")
        item.setdefault("effort", None)
    for fu in d.get("follow_ups") or []:
        fu.setdefault("category", "follow_up")
        fu.setdefault("effort", None)
    qs = d.get("open_questions") or []
    d["open_questions"] = [
        q if isinstance(q, dict) else {"text": str(q), "category": "open_question", "effort": None} for q in qs
    ]
    for q in d["open_questions"]:
        q.setdefault("category", "open_question")
        q.setdefault("effort", None)
    return d


def ticket_candidates(paths: Paths, today: date) -> list[str]:
    """`DEV-N · Task` / `DEV-N · Task / Sub-task` for everything under `* In Progress` in tron-tasks.org,
    plus every keyed heading under today's day in worklog.org. These are the tickets an item may be
    linked to; the model never gets to invent one."""
    out: list[str] = []
    if paths.tron_tasks.exists():
        doc = OrgDoc.load(paths.tron_tasks)
        for i, line in enumerate(doc.lines):
            if line.strip() == "* In Progress":
                parent = None
                for j in range(i + 1, doc.section_end(i)):
                    h = Heading.parse(j, doc.lines[j])
                    if not h:
                        continue
                    if h.level == 2:
                        parent = h.title
                        if h.link:
                            out.append(f"{h.link} · {h.title}")
                    elif h.link:
                        out.append(f"{h.link} · {parent} / {h.title}" if parent else f"{h.link} · {h.title}")
                break
    if paths.worklog.exists():
        doc = OrgDoc.load(paths.worklog)
        day = doc.find_day(today)
        if day is not None:
            for j in range(day + 1, doc.section_end(day)):
                h = Heading.parse(j, doc.lines[j])
                if h and h.link:
                    out.append(f"{h.link} · {h.title}")
    return list(dict.fromkeys(out))


def build_prompt(
    header: str, body: str, people: People, open_items: list[str] | None = None, tickets: list[str] | None = None
) -> str:
    """Meeting prompt, or the chat prompt (with the open work items to dedupe against) when the
    header says `kind: chat`. `tickets` are the ticket_candidates lines."""
    chat = header_fields(header).get("kind") == "chat"
    template = (CHAT_PROMPT_PATH if chat else PROMPT_PATH).read_text()
    items = "\n".join(f"- {i}" for i in (open_items or [])) or "- (none)"
    ticket_lines = "\n".join(f"  - {t}" for t in (tickets or [])) or "  - (none)"
    return (
        template.replace("{{OPEN_ITEMS}}", items)
        .replace("{{TICKETS}}", ticket_lines)
        .replace("{{ME}}", people.me)
        .replace("{{ROSTER}}", ", ".join(people.canonical_names))
        .replace("{{SCHEMA}}", SCHEMA_PATH.read_text().strip())
        .replace("{{HEADER}}", header.strip())
        .replace("{{TRANSCRIPT}}", body.strip())
    )


def run_claude(prompt: str, timeout: int = 300) -> str:
    """Headless Claude Code call; returns the assistant's final text."""
    cmd = [CLAUDE_BIN, "-p", "--output-format", "json", "--max-turns", "1", "--tools", ""]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:500]}")
    return result_text(proc.stdout)


def result_text(stdout: str) -> str:
    """`claude -p --output-format json` prints either one envelope or a list of messages;
    the final text lives in the entry with type == "result"."""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout
    if isinstance(envelope, list):
        for msg in reversed(envelope):
            if isinstance(msg, dict) and msg.get("type") == "result":
                return msg.get("result", "") or ""
        return stdout
    if isinstance(envelope, dict):
        return envelope.get("result", stdout)
    return stdout


def split_normalized(text: str) -> tuple[str, str]:
    header, _, body = text.partition("\n\n")
    return header, body


def header_fields(header: str) -> dict[str, str]:
    out = {}
    for line in header.splitlines():
        k, sep, v = line.partition(":")
        if sep:
            out[k.strip().lower()] = v.strip()
    return out


def pin_to_header(data: dict, header: str) -> dict:
    """The file, not the model, decides date/source/key; a follow-up cannot precede the meeting."""
    h = header_fields(header)
    if h.get("date"):
        data["date"] = h["date"]
    if h.get("source") in ("teams", "slack", "manual"):
        data["source"] = h["source"]
    if h.get("key"):
        data["key"] = h["key"]
    if h.get("kind") in ("meeting", "chat"):
        data["kind"] = h["kind"]
    for fu in data.get("follow_ups") or []:
        if fu.get("when") and fu["when"] < data["date"]:
            fu["when"] = None
    return data


def open_work_items(paths) -> list[str]:
    from arxiv_scan import collect_work_items

    return collect_work_items(paths, include_children=True)


def digest_file(
    src: Path, out: Path, people: People, open_items: list[str] | None = None, tickets: list[str] | None = None
) -> int:
    header, body = split_normalized(src.read_text(encoding="utf-8"))
    prompt = build_prompt(header, body, people, open_items, tickets)
    raw, data = "", {}
    for attempt in range(2):
        try:
            raw = run_claude(prompt)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            raw = f"claude call failed: {exc}"
            print(raw, file=sys.stderr)
            break
        try:
            data = extract_json(raw)
            errors = validate(data)
        except ValueError as exc:
            errors = [str(exc)]
        if not errors:
            data = pin_to_header(data, header)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(out)
            return 0
        prompt = (
            prompt
            + "\n\nYour previous output did not validate. Errors (required fields are in the schema):\n- "
            + "\n- ".join(errors)
            + "\nReturn the corrected JSON object only."
        )
        print(f"digest attempt {attempt + 1} invalid: {errors[:3]}", file=sys.stderr)
    raw_path = out.with_suffix(".raw.txt")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(raw, encoding="utf-8")
    print(f"digest failed; raw output saved to {raw_path}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", type=Path, nargs="?")
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--validate-only", type=Path, metavar="DIGEST_JSON")
    ap.add_argument("--today", type=date.fromisoformat, default=None, help="day whose worklog headings are ticket candidates")
    add_org_dir_arg(ap)
    args = parse_args_or_none(ap, argv)
    if args is None:
        return 1
    if args.validate_only:
        errors = validate(json.loads(args.validate_only.read_text()))
        for e in errors:
            print(e, file=sys.stderr)
        return 1 if errors else 0
    if not args.file or not args.out:
        ap.error("need <normalized.txt> and -o <out.json>")
    paths = paths_from_args(args)
    header = split_normalized(args.file.read_text(encoding="utf-8"))[0]
    items = open_work_items(paths) if header_fields(header).get("kind") == "chat" else None
    tickets = ticket_candidates(paths, args.today or date.today())
    return digest_file(args.file, args.out, People.load(paths.people_file), items, tickets)


if __name__ == "__main__":
    sys.exit(main())
