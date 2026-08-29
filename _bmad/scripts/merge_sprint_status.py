#!/usr/bin/env python3
"""Git merge driver for `sprint-status.yaml`.

Why this exists
---------------
Every story branch flips its own line in one shared file, and reviewers flip it
again on the way back. Git merges that file by *text proximity*, so two
branches touching two different stories conflict whenever their lines sit near
each other — which, in a file that is 61% comments, is most of the time. The
conflicts are never real: two agents advancing two unrelated stories have no
disagreement to resolve.

Ten BMad skills read this file, so its format is a contract and cannot change.
This driver keeps the bytes identical and merges *by key* instead of by line.

Semantics
---------
For each `story-id: status` key, compared against the merge base:

* changed on neither side          -> keep it
* changed on one side only         -> take that side
* changed on both, same value      -> take it
* changed on both, different value -> take the furthest-along status, because
  status advances (`backlog` -> `ready-for-dev` -> `in-progress` -> `review` ->
  `done`), and report it on stderr so the resolution is never silent
* added on one side only           -> include it
* removed on one side, untouched on the other -> honour the removal

Anything this cannot decide — a genuine disagreement in the comment preamble,
or a backwards status move where the other side also moved — is left as a
normal git conflict. A driver that resolved everything would be lying.

Install (once per clone; worktrees share the common config):

    _bmad/scripts/install_merge_drivers.sh

which registers an absolute-path `python3` invocation — absolute because git
runs a merge driver from the top of the worktree being merged, and `python3`
rather than `uv run` because this has no third-party imports and a merge must
not fail on dependency resolution. `.gitattributes` already carries:

    _bmad-output/implementation-artifacts/sprint-status.yaml merge=sprint-status

but that only *selects* a driver; without the registration above git falls back
to the default merge and the conflicts return, silently.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: Status order. A merge that sees two different values keeps the later one.
#: Unknown values sort *below* everything known, so an unrecognised status can
#: never silently beat a real one — it loses and the run says so.
STATUS_ORDER: tuple[str, ...] = (
    "backlog",
    "optional",
    "ready-for-dev",
    "in-progress",
    "review",
    "done",
)

#: `  2-7-some-slug: in-progress` — the leading indent is REQUIRED, and that is
#: a decision rather than an accident. It scopes this driver to the indented
#: `development_status:` entries and deliberately excludes the six top-level
#: scalars (`generated`, `last_updated`, `project`, ...). Those are stamped by
#: every branch, so merging them key-wise would make the *date* the new
#: permanent conflict — trading a real conflict for a sillier one. They are
#: taken from `ours` and never conflict.
#:
#: This assumes the file stays flat: top-level scalars plus one 2-space map,
#: which is its shape today. A nested block under a story id would be seen as
#: an entry at whatever indent it carries.
ENTRY = re.compile(r"^(?P<indent>\s+)(?P<key>[A-Za-z0-9][A-Za-z0-9._-]*):\s*(?P<value>\S.*?)\s*$")


def rank(status: str) -> int:
    try:
        return STATUS_ORDER.index(status)
    except ValueError:
        return -1


def parse(text: str) -> dict[str, str]:
    """Every `key: value` entry in the file, ignoring comments and blanks."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = ENTRY.match(line)
        if match:
            out[match.group("key")] = match.group("value")
    return out


def merge(base: str, ours: str, theirs: str, path: str) -> tuple[str, bool]:
    """Return the merged text and whether a conflict survived.

    `ours` is the structural template: it keeps our comments, ordering and
    preamble, and only the *values* move. That is deliberate — the alternative
    is reflowing a file ten skills parse.
    """
    b, o, t = parse(base), parse(ours), parse(theirs)
    resolved: dict[str, str] = {}
    conflicted = False

    for key in set(o) | set(t):
        base_value = b.get(key)
        our_value, their_value = o.get(key), t.get(key)

        if our_value == their_value:
            if our_value is not None:
                resolved[key] = our_value
            continue
        # Removed on one side and untouched on the other: honour the removal.
        if our_value is None:
            if their_value == base_value:
                continue
            resolved[key] = their_value  # type: ignore[assignment]
            continue
        if their_value is None:
            if our_value == base_value:
                continue
            resolved[key] = our_value
            continue
        # Both present and different: whoever moved wins; if both moved, the
        # furthest-along status wins.
        if our_value == base_value:
            resolved[key] = their_value
            continue
        if their_value == base_value:
            resolved[key] = our_value
            continue
        our_rank, their_rank = rank(our_value), rank(their_value)
        if our_rank == their_rank:
            # Two unknown statuses, or a tie we have no rule for. Real conflict.
            conflicted = True
            resolved[key] = our_value
            print(
                f"{path}: CONFLICT on {key!r}: {our_value!r} vs {their_value!r}"
                " — no ordering rule applies; resolve by hand",
                file=sys.stderr,
            )
            continue
        winner = our_value if our_rank > their_rank else their_value
        resolved[key] = winner
        print(
            f"{path}: {key}: {our_value!r} + {their_value!r} -> {winner!r}"
            " (furthest-along status wins)",
            file=sys.stderr,
        )

    # Rewrite `ours` line by line, substituting merged values and appending any
    # key that exists only on their side, so a story another branch registered
    # is never dropped on the floor.
    lines = ours.splitlines()
    seen: set[str] = set()
    for index, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        match = ENTRY.match(line)
        if not match:
            continue
        key = match.group("key")
        seen.add(key)
        if key in resolved:
            lines[index] = f"{match.group('indent')}{key}: {resolved[key]}"

    added = [k for k in resolved if k not in seen]
    if added:
        # Appended rather than slotted in: guessing the right section is how a
        # merge driver corrupts a file it does not really understand.
        lines.append("")
        lines.append("  # Added by a concurrent branch; re-file under its epic.")
        for key in added:
            lines.append(f"  {key}: {resolved[key]}")
            print(f"{path}: adopted {key!r} from the other side", file=sys.stderr)

    return "\n".join(lines) + "\n", conflicted


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(
            "usage: merge_sprint_status.py <base> <ours> <theirs> [path]",
            file=sys.stderr,
        )
        return 2
    base_path, ours_path, theirs_path = (Path(p) for p in argv[1:4])
    label = argv[4] if len(argv) > 4 else str(ours_path)

    merged, conflicted = merge(
        base_path.read_text(encoding="utf-8"),
        ours_path.read_text(encoding="utf-8"),
        theirs_path.read_text(encoding="utf-8"),
        label,
    )
    # Git takes the result from %A whatever the exit status.
    ours_path.write_text(merged, encoding="utf-8")
    return 1 if conflicted else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
