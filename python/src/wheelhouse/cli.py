"""wheelhouse: commission a new admin, and report how far a project's copies
of the shared parts have drifted.

    wheelhouse new <id> --name "Name" --tagline "..." [--dir PATH] [--port N]
                         [--wheelhouse PATH_OR_GIT_URL] [--rev REF]
    wheelhouse drift <ui dir> [--json]
    wheelhouse sync <ui dir> [item ...] [--write]

The registry manifest (template/ui/registry.json) is the list of shared parts.
`drift` and `sync` read it directly, so they need no registry server.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # the wheelhouse checkout
TEMPLATE = ROOT / "template"
MANIFEST = TEMPLATE / "ui" / "registry.json"
SKIP = shutil.ignore_patterns("node_modules", "web", "dist", "__pycache__", ".venv", ".pytest_cache", "uv.lock", "registry.json", "*.pyc")
# Where a new admin gets the package unless told otherwise: the public
# repository, pinned to the tag of this version.
PUBLIC_GIT = "https://github.com/lavallee/wheelhouse"
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


def _manifest(starters: bool = True) -> list[dict]:
    """Shared parts, plus the stock shadcn primitives the template pins. Items named
    `screen-*` are starting points an app is expected to change, not shared parts."""
    items = json.loads(MANIFEST.read_text())["items"]
    primitives = sorted((TEMPLATE / "ui" / "src" / "components" / "ui").glob("*.tsx"))
    items.insert(0, {"name": "primitives", "files": [{"path": str(p.relative_to(TEMPLATE / "ui"))} for p in primitives]})
    return [item for item in items if starters or not item["name"].startswith("screen-")]


def _source(dest: Path, spec: str | None, rev: str | None) -> str:
    """The `[tool.uv.sources]` entry for the new admin's wheelhouse dependency.

    A git URL is written as given (with `subdirectory = "python"`); a path is
    written relative to the new admin, so the generated file names no local
    directory. The default is the public repository at this version's tag.
    """
    if spec is None:
        from . import __version__
        spec, rev = PUBLIC_GIT, rev or f"v{__version__}"
    if "://" in spec or spec.startswith("git@"):
        url = spec.removeprefix("git+")
        extra = f", rev = {json.dumps(rev)}" if rev else ""
        return f'wheelhouse = {{ git = {json.dumps(url)}, subdirectory = "python"{extra} }}'
    if rev:
        raise SystemExit("--rev applies only to a git URL")
    target = Path(spec).expanduser().resolve()
    if not (target / "pyproject.toml").is_file():
        raise SystemExit(f"{spec} is not the wheelhouse python package (no pyproject.toml there)")
    if Path(os.path.commonpath([target, dest])) == Path(target.anchor):
        # A path up to the filesystem root would spell out where this checkout lives.
        raise SystemExit(f"the new admin and the wheelhouse package share no directory but {target.anchor}; "
                         "pass --wheelhouse with a git URL, or create the admin nearer the checkout")
    rel = Path(os.path.relpath(target, dest)).as_posix()
    return f"wheelhouse = {{ path = {json.dumps(rel)}, editable = true }}"


def cmd_new(args) -> int:
    if not ID_RE.match(args.id):
        print("id must be lowercase letters, digits and hyphens, starting with a letter", file=sys.stderr)
        return 2
    dest = Path(args.dir or Path.cwd() / args.id).resolve()
    if dest.exists() and any(dest.iterdir()):
        print(f"{dest} exists and is not empty; nothing written", file=sys.stderr)
        return 1
    source = _source(dest, args.wheelhouse, args.rev)
    shutil.copytree(TEMPLATE, dest, ignore=SKIP, dirs_exist_ok=True)
    name = args.name or args.id.replace("-", " ").title()
    config = dest / "ui" / "src" / "app.config.ts"
    config.write_text(
        "// The one file that names this admin. `wheelhouse new` wrote it.\n"
        "export const APP = {\n"
        f"  id: {json.dumps(args.id)},\n"
        f"  name: {json.dumps(name)},\n"
        f"  tagline: {json.dumps(args.tagline or '')},\n"
        "  /** One sentence the sidebar footer shows about what this admin does and never does. */\n"
        f"  promise: {json.dumps(args.promise or '')},\n"
        "};\n"
    )
    env = re.sub(r"[^A-Z0-9]", "_", args.id.upper())
    swaps = [
        ("wheelhouse-template-ui", f"{args.id}-admin-ui"),
        ("sample-admin", f"{args.id}-admin"),
        ('APP_ID = "sample"', f"APP_ID = {json.dumps(args.id)}"),
        ("SAMPLE_ADMIN_MODE", f"{env}_ADMIN_MODE"),
        ("Sample admin", name),
        ('wheelhouse = { path = "../python", editable = true }', source),
        ("8870", str(args.port)),
    ]
    for rel in ["backend/app.py", "backend/test_app.py", "README.md", "AGENTS.md", "pyproject.toml", "ui/package.json",
                "ui/package-lock.json", "ui/vite.config.ts", "ci.sh", "dev.sh"]:
        path = dest / rel
        if path.exists():
            text = path.read_text()
            for old, new in swaps:
                text = text.replace(old, new)
            path.write_text(text)
    print(f"created {dest}")
    print(f"  depends on {source}")
    print(f"  cd {dest} && ./ci.sh          # install, build, test")
    print(f"  cd {dest} && ./dev.sh         # run it on http://127.0.0.1:{args.port}")
    return 0


def _find(ui: Path, rel: str) -> Path | None:
    """The project's copy of a shared file: same path, or the same file name anywhere under src."""
    exact = ui / rel
    if exact.exists():
        return exact
    matches = [p for p in (ui / "src").rglob(Path(rel).name) if "node_modules" not in p.parts]
    return matches[0] if len(matches) == 1 else None


def _drift(ui: Path) -> list[dict]:
    rows = []
    for item in _manifest(starters=False):
        for entry in item["files"]:
            rel = entry["path"]
            ours = (TEMPLATE / "ui" / rel).read_text()
            theirs_path = _find(ui, rel)
            if theirs_path is None:
                rows.append({"item": item["name"], "file": rel, "state": "missing"})
                continue
            theirs = theirs_path.read_text()
            if theirs == ours:
                state, added, removed = "identical", 0, 0
            else:
                diff = list(difflib.unified_diff(theirs.splitlines(), ours.splitlines(), lineterm="", n=0))
                added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
                removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
                state = "differs"
            rows.append({"item": item["name"], "file": rel, "state": state, "at": str(theirs_path.relative_to(ui)),
                         "lines_to_add": added, "lines_to_remove": removed})
    return rows


def cmd_drift(args) -> int:
    ui = Path(args.ui).resolve()
    if not (ui / "src").is_dir():
        print(f"{ui} has no src directory", file=sys.stderr)
        return 2
    rows = _drift(ui)
    if args.json:
        print(json.dumps(rows, indent=1))
    else:
        for row in rows:
            detail = "" if row["state"] != "differs" else f"  +{row['lines_to_add']} -{row['lines_to_remove']}  ({row['at']})"
            print(f"{row['state']:<10} {row['item']:<16} {row['file']}{detail}")
        tally = {state: sum(1 for r in rows if r["state"] == state) for state in ("identical", "differs", "missing")}
        print(f"{tally['identical']} identical, {tally['differs']} differ, {tally['missing']} missing")
    return 0


def cmd_sync(args) -> int:
    ui = Path(args.ui).resolve()
    wanted = set(args.items)
    known = {item["name"] for item in _manifest()}
    if wanted - known:
        print(f"unknown items: {', '.join(sorted(wanted - known))}", file=sys.stderr)
        return 2
    changed = 0
    for item in _manifest(starters=bool(wanted)):
        if wanted and item["name"] not in wanted:
            continue
        for entry in item["files"]:
            rel = entry["path"]
            source = TEMPLATE / "ui" / rel
            target = _find(ui, rel) or ui / rel
            if target.exists() and target.read_text() == source.read_text():
                continue
            changed += 1
            print(f"{'write' if args.write else 'would write'} {target.relative_to(ui)}  ({item['name']})")
            if args.write:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    if not changed:
        print("nothing to do")
    elif not args.write:
        print("dry run; pass --write to apply")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wheelhouse", description="Commission admins and track the shared parts.")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="create a new admin from the template")
    new.add_argument("id")
    new.add_argument("--name")
    new.add_argument("--tagline")
    new.add_argument("--promise")
    new.add_argument("--dir")
    new.add_argument("--port", type=int, default=8870)
    new.add_argument("--wheelhouse", metavar="PATH_OR_GIT_URL",
                     help="where the new admin gets the wheelhouse package: a git URL, or a path to a "
                          "checkout's python/ directory, written relative to the admin "
                          f"(default: {PUBLIC_GIT} at this version's tag)")
    new.add_argument("--rev", help="git tag, branch or commit, with a git URL (default with the public URL: v<version>)")
    new.set_defaults(run=cmd_new)
    drift = sub.add_parser("drift", help="compare a project's copies of the shared parts with the registry")
    drift.add_argument("ui")
    drift.add_argument("--json", action="store_true")
    drift.set_defaults(run=cmd_drift)
    sync = sub.add_parser("sync", help="copy shared parts into a project (dry run unless --write)")
    sync.add_argument("ui")
    sync.add_argument("items", nargs="*")
    sync.add_argument("--write", action="store_true")
    sync.set_defaults(run=cmd_sync)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
