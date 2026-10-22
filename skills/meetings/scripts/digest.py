"""Run the digest prompt through `claude -p` and validate the JSON against the schema.

Usage: digest.py <normalized.txt> -o <digests/stem.json>
       digest.py --validate-only <digest.json>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import jsonschema

from config import add_org_dir_arg, paths_from_args
from people import People

SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = SKILL_DIR / "references" / "digest-schema.json"
PROMPT_PATH = SKILL_DIR / "references" / "digest-prompt.md"
CLAUDE_BIN = "claude"


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


def build_prompt(header: str, body: str, people: People) -> str:
    template = PROMPT_PATH.read_text()
    return (
        template.replace("{{ME}}", people.me)
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


def digest_file(src: Path, out: Path, people: People) -> int:
    header, body = split_normalized(src.read_text(encoding="utf-8"))
    prompt = build_prompt(header, body, people)
    raw, data = "", {}
    for attempt in range(2):
        raw = run_claude(prompt)
        try:
            data = extract_json(raw)
            errors = validate(data)
        except ValueError as exc:
            errors = [str(exc)]
        if not errors:
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
    add_org_dir_arg(ap)
    args = ap.parse_args(argv)
    if args.validate_only:
        errors = validate(json.loads(args.validate_only.read_text()))
        for e in errors:
            print(e, file=sys.stderr)
        return 1 if errors else 0
    if not args.file or not args.out:
        ap.error("need <normalized.txt> and -o <out.json>")
    paths = paths_from_args(args)
    return digest_file(args.file, args.out, People.load(paths.people_file))


if __name__ == "__main__":
    sys.exit(main())
