"""Normalize a transcript file (txt / vtt / docx) into canonical text plus metadata.

Filename convention: YYYY-MM-DD[-HHMM]-<slug>.<ext> (month and day may be unpadded; a doubled '-'
before the slug is tolerated). Optional front-matter (key: value lines up to the first blank line)
overrides filename-derived fields.

Three pasted shapes are detected and reduced to "Name: utterance" lines, with attendees taken from
the speakers: a .txt copied from the Teams transcript panel (initials / name / "Name N minutes N
seconds" / utterance), a Teams meeting-recording transcript (.docx download or its text: `Name   M:SS`
stamp, utterance below), and a Slack huddle copied from the captions pane (`Name` alone on a line,
utterance on the next, blank line between turns).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

FILENAME_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:-(\d{2})(\d{2}))?-+(.+)$")  # month/day may be unpadded
FRONTMATTER_KEYS = {"title", "date", "time", "source", "attendees", "kind"}
KINDS = ("meeting", "chat")
SPEAKER_TAG_RE = re.compile(r"<v\s+([^>]+)>")
ANY_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")  # Teams VTTs close every cue with </v>
SOURCE_BY_EXT = {".vtt": "teams", ".docx": "teams"}
# "Mara Stone 0 minutes 5 seconds" — the per-chunk stamp line of a Teams transcript-panel copy.
# The panel also prints "0 minutes 5 seconds0:05" (no name, clock suffix), which must not match.
TEAMS_STAMP_RE = re.compile(r"^(?P<name>\S.*?) (?:(?P<hr>\d+) hours? )?(?P<min>\d+) minutes? (?P<sec>\d+) seconds?$")
TEAMS_MIN_STAMPS = 2
# Teams "Meeting Recording" transcript download (.docx, or its text pasted): `Name   M:SS` / `H:MM:SS`
TEAMS_CLOCK_RE = re.compile(r"^(?P<name>\S.*?)\s{2,}(?P<clock>\d{1,2}:\d{2}(?::\d{2})?)$")
TEAMS_NOTICE_RE = re.compile(r"^\S.*? (?:started|stopped) transcription$")
# Slack huddle captions copied out: the name alone on a line, the utterance on the next, a blank line between
HUDDLE_NAME_RE = re.compile(r"^[A-Z][^\s:]*(?: [A-Z][^\s:]*){0,3}$")
HUDDLE_NOTICE_RE = re.compile(r"^(?:started|stopped|joined|left) (?:screen sharing|recording|transcription|the huddle)\.?$")
HUDDLE_MIN_BLOCKS = 3


@dataclass
class Meta:
    title: str
    date: date
    time: str | None
    source: str
    attendees: list[str] = field(default_factory=list)
    stem: str = ""
    key: str = ""
    kind: str = "meeting"  # "meeting" (transcript) or "chat" (a day of Slack messages)

    def header(self) -> str:
        return (
            f"title: {self.title}\n"
            f"date: {self.date.isoformat()}\n"
            f"time: {self.time or ''}\n"
            f"source: {self.source}\n"
            f"kind: {self.kind}\n"
            f"attendees: {', '.join(self.attendees)}\n"
            f"key: {self.key}\n"
        )


def slug_to_title(slug: str) -> str:
    # '-' becomes a space except between two digits ("rob-1-1" -> "Rob 1-1")
    spaced = re.sub(r"(?<!\d)-|-(?!\d)", " ", slug)
    return " ".join(w[:1].upper() + w[1:] for w in spaced.split())


def parse_filename(name: str) -> Meta:
    path = Path(name)
    m = FILENAME_RE.match(path.stem)
    if not m:
        raise ValueError(f"filename must look like YYYY-MM-DD[-HHMM]-<slug>.<ext>: {name}")
    yyyy, mo, dd, hh, mm, slug = m.groups()
    return Meta(
        title=slug_to_title(slug),
        date=date(int(yyyy), int(mo), int(dd)),
        time=f"{hh}:{mm}" if hh else None,
        source=SOURCE_BY_EXT.get(path.suffix.lower(), "manual"),
        stem=path.stem,
    )


def parse_frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines(keepends=True)
    meta: dict[str, str] = {}
    i = 0
    for i, line in enumerate(lines):
        if not line.strip():
            break
        k, sep, v = line.partition(":")
        if not sep or k.strip().lower() not in FRONTMATTER_KEYS:
            return {}, text
        meta[k.strip().lower()] = v.strip()
    else:
        return {}, text  # no blank line -> whole file is body
    if not meta:
        return {}, text
    return meta, "".join(lines[i + 1 :])


def _read_vtt(path: Path) -> str:
    """One 'Name: text' line per speaker turn. Teams splits a sentence across cues (and across lines
    inside a cue), so consecutive cues from one speaker are joined; a repeated cue is dropped."""
    import webvtt

    turns: list[list[str]] = []  # [speaker, text]
    last_text = None
    for caption in webvtt.read(str(path)):
        raw = caption.raw_text.strip()
        m = SPEAKER_TAG_RE.search(raw)
        speaker = m.group(1).strip() if m else ""
        text = re.sub(r"\s+", " ", ANY_TAG_RE.sub("", raw)).strip()
        if not text or text == last_text:
            continue
        last_text = text
        if turns and turns[-1][0] == speaker:
            turns[-1][1] += " " + text
        else:
            turns.append([speaker, text])
    return "\n".join(f"{who}: {what}" if who else what for who, what in turns)


def _read_docx(path: Path) -> str:
    import docx

    return "\n".join(p.text for p in docx.Document(str(path)).paragraphs if p.text.strip())


def parse_teams_copy(text: str) -> tuple[list[str], str] | None:
    """Reduce a Teams transcript-panel copy to (speakers in order of first appearance,
    "Name: utterance" lines). Returns None when the text does not have that shape.

    Only the line after a stamp line is kept; initials, bare names, duration lines, the
    "AI-generated content" banner, private-use glyphs, and started/stopped notices are dropped.
    Consecutive chunks from the same speaker merge into one line.
    """
    lines = text.splitlines()
    speakers: list[str] = []
    turns: list[list[str]] = []  # [speaker, text]
    stamps = 0
    i = 0
    while i < len(lines):
        m = TEAMS_STAMP_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        stamps += 1
        name = m.group("name")
        utterance = lines[i + 1].strip() if i + 1 < len(lines) else ""
        i += 2
        if name not in speakers:
            speakers.append(name)
        if not utterance:
            continue
        _merge_turns(turns, name, utterance)
    if stamps < TEAMS_MIN_STAMPS:
        return None
    return speakers, "\n".join(f"{who}: {what}" for who, what in turns) + "\n"


def _merge_turns(turns: list[list[str]], name: str, utterance: str) -> None:
    if turns and turns[-1][0] == name:
        turns[-1][1] += " " + utterance
    else:
        turns.append([name, utterance])


def parse_teams_recording(text: str) -> tuple[list[str], str] | None:
    """Reduce a Teams meeting-recording transcript (`Name   M:SS` stamp, utterance on the lines after,
    until the next stamp or a blank line) to (speakers, "Name: utterance" lines). The title, date,
    duration, and started/stopped-transcription notices are dropped. None when the shape is absent."""
    speakers: list[str] = []
    turns: list[list[str]] = []
    stamps = 0
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        m = TEAMS_CLOCK_RE.match(line)
        if m:
            stamps += 1
            current = m.group("name")
            if current not in speakers:
                speakers.append(current)
            continue
        if not line:
            current = None
            continue
        if current is None or TEAMS_NOTICE_RE.match(line):
            continue
        _merge_turns(turns, current, line)
    if stamps < TEAMS_MIN_STAMPS:
        return None
    return speakers, "\n".join(f"{who}: {what}" for who, what in turns) + "\n"


def parse_slack_huddle(text: str) -> tuple[list[str], str] | None:
    """Reduce a copied Slack huddle transcript (blocks of `Name` / utterance separated by blank lines)
    to (speakers, "Name: utterance" lines). Every block must have that shape and at least two people
    must speak, so prose paragraphs and `Name: text` chat do not match. Same-speaker runs merge;
    system notices ("started screen sharing.") are dropped."""
    blocks = [b.strip().split("\n") for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) < HUDDLE_MIN_BLOCKS:
        return None
    speakers: list[str] = []
    turns: list[list[str]] = []
    for block in blocks:
        name = block[0].strip()
        if len(block) < 2 or not HUDDLE_NAME_RE.match(name):
            return None
        if name not in speakers:
            speakers.append(name)
        utterance = " ".join(l.strip() for l in block[1:] if l.strip())
        if HUDDLE_NOTICE_RE.match(utterance):
            continue
        _merge_turns(turns, name, utterance)
    if len(speakers) < 2:
        return None
    return speakers, "\n".join(f"{who}: {what}" for who, what in turns) + "\n"


def read_transcript(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".vtt":
        return _read_vtt(path)
    if suffix == ".docx":
        return _read_docx(path)
    return path.read_text(encoding="utf-8", errors="replace")


def clean_body(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def normalize(path: Path) -> tuple[Meta, str]:
    path = Path(path)
    meta = parse_filename(path.name)
    fm, body = parse_frontmatter(read_transcript(path))
    suffix = path.suffix.lower()
    parsed = None
    if suffix == ".txt":
        parsed = parse_teams_copy(body) or parse_teams_recording(body)
        if parsed:
            meta.source = "teams"
        elif (parsed := parse_slack_huddle(body)):
            meta.source = "slack"
    elif suffix == ".docx":
        parsed = parse_teams_recording(body)
    if parsed:
        meta.attendees, body = parsed
    if "title" in fm:
        meta.title = fm["title"]
    if "date" in fm:
        meta.date = date.fromisoformat(fm["date"])
    if "time" in fm:
        meta.time = fm["time"] or None
    if "source" in fm:
        meta.source = fm["source"]
    if "attendees" in fm:
        meta.attendees = [a.strip() for a in fm["attendees"].split(",") if a.strip()]
    if fm.get("kind") in KINDS:
        meta.kind = fm["kind"]
    body = clean_body(body)
    meta.key = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return meta, body


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None)
    args = ap.parse_args(argv)
    meta, body = normalize(args.file)
    text = meta.header() + "\n" + body
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(args.out)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
