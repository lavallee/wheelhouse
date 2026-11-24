#!/usr/bin/env python3
"""Refuse private names, local paths and private hostnames in what this
repository would publish.

    python3 scripts/hygiene.py              # check; exit 1 on any hit
    python3 scripts/hygiene.py --hash WORD  # the line to add to the deny-list

The files checked are everything git tracks plus new files git does not
ignore, and their paths, except under `records/`: a private copy of this
repository may keep its own records there, and they are never published. The deny-list (scripts/hygiene.sha256) holds SHA-256
hashes of lowercase words, so the list itself names nothing. A word is a run
of letters and digits, and hyphenated or underscored runs are checked whole and
in parts (`sign-in` and `sign`, `in`). A hit is shown masked, with its line.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DENY = ROOT / "scripts" / "hygiene.sha256"
PRIVATE = "records/"  # a private copy's own records: skipped here, never carried to the public tree
WORD = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
# Shapes that are never right in a published file, whatever the name.
PATTERNS = {
    "a home directory": re.compile(r"/home/[a-z]|/Users/[A-Za-z]|~/Projects"),
    "a private hostname": re.compile(r"\b[a-z0-9-]+\.(?:internal|lan|ts\.net|tailnet)\b"),
}


def digest(word: str) -> str:
    return hashlib.sha256(word.lower().encode()).hexdigest()


def denied() -> set[str]:
    lines = DENY.read_text().splitlines()
    return {line.split()[0] for line in lines if line.strip() and not line.startswith("#")}


def files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, check=True, capture_output=True).stdout
    return [name for name in out.decode().split("\0")
            if name and not name.startswith(PRIVATE) and (ROOT / name).is_file()]


def words(text: str):
    for token in WORD.findall(text.lower()):
        yield token
        if "-" in token or "_" in token:
            yield from re.split(r"[-_]", token)


def main(argv: list[str]) -> int:
    if argv[:1] == ["--hash"]:
        for word in argv[1:]:
            print(f"{digest(word)}")
        return 0
    deny, hits = denied(), []
    me = Path(__file__).resolve()
    for name in files():
        path = ROOT / name
        raw = path.read_bytes()
        text = "" if b"\0" in raw[:8192] else raw.decode("utf-8", errors="ignore")
        for word in set(words(name)):
            if digest(word) in deny:
                hits.append(f"{name}: a denied word in the path ({word[:1]}{'*' * (len(word) - 1)})")
        for number, line in enumerate(text.splitlines(), start=1):
            for word in set(words(line)):
                if digest(word) in deny:
                    hits.append(f"{name}:{number}: a denied word ({word[:1]}{'*' * (len(word) - 1)})")
        if path.resolve() != me:
            for what, pattern in PATTERNS.items():
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    hits.append(f"{name}:{line}: {what}")
    for hit in sorted(set(hits)):
        print(hit)
    if hits:
        print(f"hygiene: {len(set(hits))} problem(s); see scripts/hygiene.py", file=sys.stderr)
        return 1
    print("hygiene: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
