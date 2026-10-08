"""Read-only access to a lora-kernel checkout, one value at a time, with its source.

Every value this example takes from lora-kernel goes through a `Reader`: a JSON
pointer into a results file, a module-level constant or an argparse default read
with `ast` (the code is parsed, never imported or run), a regex over a text file,
or a sha256 over a file's bytes. Each read returns the value and records where it
came from (`path#locator`), so the manifest and the ledger can cite their sources and
`make_fixture.py` can rebuild the minimal subset the tests need.

Nothing here writes inside the lora-kernel tree.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path


def pointer_escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def pointer(keys) -> str:
    return "/" + "/".join(pointer_escape(str(k)) for k in keys)


def norm(text: str) -> str:
    """Whitespace collapsed and markdown emphasis removed, so a quote that wraps
    across lines in a BRIEF.md still matches."""
    return re.sub(r"\s+", " ", text.replace("*", "")).strip()


class Reader:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise SystemExit(f"lora-kernel checkout not found: {self.root}")
        self.log: list[dict] = []  # every access, for make_fixture.py
        self._cache: dict = {}

    # -- files -------------------------------------------------------------
    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root not in p.parents:
            raise ValueError(f"{rel} is outside the checkout")
        return p

    def text(self, rel: str) -> str:
        key = ("text", rel)
        if key not in self._cache:
            self._cache[key] = self.path(rel).read_text(encoding="utf-8")
        return self._cache[key]

    def _json(self, rel: str):
        key = ("json", rel)
        if key not in self._cache:
            self._cache[key] = json.loads(self.text(rel))
        return self._cache[key]

    # -- reads -------------------------------------------------------------
    def json(self, rel: str, *keys):
        """The value at `keys` in a JSON file; source `rel#/json/pointer`."""
        v = self._json(rel)
        for k in keys:
            v = v[k]
        self.log.append({"kind": "json", "file": rel, "keys": list(keys), "value": v})
        return v, f"{rel}#{pointer(keys)}"

    def const(self, rel: str, name: str):
        """A module-level `NAME = <literal>` (parsed, not imported)."""
        for node in ast.parse(self.text(rel)).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                v = ast.literal_eval(node.value)
                self.log.append({"kind": "const", "file": rel, "name": name, "value": v})
                return v, f"{rel}:{name}"
        raise KeyError(f"{rel}: no module-level literal {name}")

    def argdefault(self, rel: str, flag: str):
        """The `default=` of `add_argument(flag, ...)`; BooleanOptionalAction keeps its default."""
        for node in ast.walk(ast.parse(self.text(rel))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_argument" and node.args
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value == flag):
                for kw in node.keywords:
                    if kw.arg == "default":
                        v = ast.literal_eval(kw.value)
                        self.log.append({"kind": "arg", "file": rel, "flag": flag, "value": v})
                        return v, f"{rel}:add_argument({flag!r}).default"
                raise KeyError(f"{rel}: {flag} has no literal default")
        raise KeyError(f"{rel}: no add_argument({flag!r})")

    def regex(self, rel: str, pattern: str, group: int = 1):
        """The first match of `pattern` (over whitespace-normalised text); source names the pattern."""
        m = re.search(pattern, norm(self.text(rel)))
        if not m:
            raise KeyError(f"{rel}: /{pattern}/ not found")
        self.log.append({"kind": "regex", "file": rel, "pattern": pattern, "match": m.group(0)})
        return m.group(group), f"{rel} /{pattern}/"

    def quote(self, rel: str, words: str):
        """Assert a quote is in the file verbatim (modulo wrapping) and return it with its source."""
        if norm(words) not in norm(self.text(rel)):
            raise KeyError(f"{rel}: quote not found: {words!r}")
        self.log.append({"kind": "quote", "file": rel, "quote": words})
        return words, rel

    def sha256_file(self, rel: str):
        h = hashlib.sha256(self.path(rel).read_bytes()).hexdigest()
        self.log.append({"kind": "sha256", "file": rel})
        return h, f"sha256({rel})"

    def sha256_const(self, rel: str, name: str):
        """sha256 of a string constant's UTF-8 — the convention lora-kernel's role.toml
        `[prompt] sha256` uses. The text itself is never returned."""
        for node in ast.parse(self.text(rel)).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                v = ast.literal_eval(node.value)
                self.log.append({"kind": "prompt", "file": rel, "name": name})
                return hashlib.sha256(v.encode("utf-8")).hexdigest(), len(v), f"{rel}:{name}"
        raise KeyError(f"{rel}: no module-level literal {name}")


def fraction(s: str) -> float:
    """'27/30' -> 0.9 (results files write counts as strings)."""
    a, b = s.split("/")
    return int(a) / int(b)
