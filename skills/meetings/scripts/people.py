"""Alias -> canonical first-name map, loaded from meetings/people.yaml."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def norm_name(name: str) -> str:
    """Lowercase, strip punctuation, collapse spaces: 'J.T.' -> 'jt', 'Nick  Tomasino' -> 'nick tomasino'."""
    return _NON_ALNUM.sub(" ", name.lower()).strip()


@dataclass
class People:
    me: str
    aliases: dict[str, str] = field(default_factory=dict)  # normalized alias -> canonical

    @classmethod
    def load(cls, path: Path) -> "People":
        data = yaml.safe_load(Path(path).read_text()) or {}
        me = data.get("me", "Nick")
        aliases: dict[str, str] = {}
        for canonical, names in (data.get("people") or {}).items():
            aliases[norm_name(canonical)] = canonical
            for alias in names or []:
                aliases[norm_name(str(alias))] = canonical
        return cls(me=me, aliases=aliases)

    @property
    def canonical_names(self) -> list[str]:
        return sorted(set(self.aliases.values()))

    def resolve(self, name: str | None) -> str | None:
        if not name:
            return None
        key = norm_name(name)
        if key in self.aliases:
            return self.aliases[key]
        # 'j t' (from 'J.T.') -> 'jt'
        compact = key.replace(" ", "")
        return self.aliases.get(compact)

    def is_me(self, name: str | None) -> bool:
        return self.resolve(name) == self.me

    def tokens_for(self, canonical: str) -> set[str]:
        """All alias tokens that refer to this canonical person (for heading matching)."""
        out: set[str] = set()
        for alias, canon in self.aliases.items():
            if canon == canonical:
                out.update(alias.split())
        return out
