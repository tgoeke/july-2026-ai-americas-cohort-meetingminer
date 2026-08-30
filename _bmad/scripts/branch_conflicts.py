#!/usr/bin/env python3
"""Pairwise merge-conflict matrix for in-flight story branches.

Dispatch and integrate decisions in this repository turn on one question:
would two branches conflict when both land on the integration branch?
Filenames answer it badly — two stories editing different regions of
`config.py` merge cleanly, while two stories appending to the same test
module do not. `git merge-tree --write-tree` answers it exactly, without
touching any worktree, so the answer is measured rather than guessed.

Usage:
  branch_conflicts.py                  every local story/* branch, pairwise and against --base
  branch_conflicts.py A B [C ...]      only these refs (pairwise, and each against --base)
  branch_conflicts.py --against A      A against every other story/* branch and --base
  branch_conflicts.py --hunks A        A's changed regions relative to --base, per file
                                       (base line ranges; use it to declare or check a footprint)
  --base REF                           integration branch (default: main)
  --json                               machine-readable output

Exit status: 0 = no conflicting pair, 1 = at least one pair conflicts,
2 = usage or git error. Run from anywhere inside the repository.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import subprocess
import sys

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.exit(2)
    return proc


def story_branches() -> list[str]:
    out = git("for-each-ref", "--format=%(refname:short)", "refs/heads/story/").stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def conflicts_between(a: str, b: str) -> list[str]:
    """Files that conflict when `a` and `b` are merged; empty when clean."""
    proc = git("merge-tree", "--write-tree", "--name-only", a, b, check=False)
    if proc.returncode == 0:
        return []
    if proc.returncode != 1:
        sys.stderr.write(f"git merge-tree {a} {b}: {proc.stderr}")
        sys.exit(2)
    files: list[str] = []
    for line in proc.stdout.splitlines()[1:]:  # first line is the tree oid
        if not line.strip():
            break
        files.append(line.strip())
    return files


def hunks(ref: str, base: str) -> dict[str, list[str]]:
    """Per file, the base-coordinate ranges `ref` changes (new files are `+new`)."""
    out = git("diff", "--unified=0", f"{base}...{ref}").stdout
    result: dict[str, list[str]] = {}
    current = None
    new_file = False
    for line in out.splitlines():
        if line.startswith("diff --git "):
            current = line.split(" b/", 1)[1]
            new_file = False
            result.setdefault(current, [])
        elif line.startswith("new file mode"):
            new_file = True
            result[current] = ["+new"]
        elif current and not new_file and (m := HUNK.match(line)):
            start, length = int(m.group(1)), int(m.group(2) or "1")
            end = start + max(length, 1) - 1
            result[current].append(f"{start}" if start == end else f"{start}-{end}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("refs", nargs="*")
    parser.add_argument("--base", default="main")
    parser.add_argument("--against")
    parser.add_argument("--hunks")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.hunks:
        table = hunks(args.hunks, args.base)
        if args.json:
            print(json.dumps({"ref": args.hunks, "base": args.base, "files": table}, indent=2))
        else:
            print(f"{args.hunks} vs {args.base} — changed regions in {args.base} line numbers:")
            for path in sorted(table):
                print(f"  {path}: {', '.join(table[path]) or '(mode/rename only)'}")
        return 0

    refs = args.refs or story_branches()
    if args.against:
        refs = [args.against] + [r for r in refs if r != args.against]
        pairs = [(args.against, r) for r in refs[1:]]
    else:
        pairs = list(itertools.combinations(refs, 2))
    pairs = [(args.base, r) for r in refs if r != args.base] + pairs

    report = []
    for a, b in pairs:
        report.append({"a": a, "b": b, "conflicts": conflicts_between(a, b)})

    bad = [r for r in report if r["conflicts"]]
    if args.json:
        print(json.dumps({"base": args.base, "pairs": report}, indent=2))
    else:
        width = max((len(r["a"]) + len(r["b"]) for r in report), default=10) + 5
        for r in report:
            label = f"{r['a']} × {r['b']}".ljust(width)
            print(f"{label} {'CONFLICT: ' + ', '.join(r['conflicts']) if r['conflicts'] else 'clean'}")
        print()
        print(f"{len(report) - len(bad)} clean pair(s), {len(bad)} conflicting pair(s).")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
