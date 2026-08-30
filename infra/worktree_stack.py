#!/usr/bin/env python3
"""Per-worktree compose stacks (story 11.2): allocate ports, render, prune.

Every checkout used to share one compose stack on fixed ports with fixed
container names, so two worktrees running store-backed suites queued on the
cross-worktree projection lock. ``make worktree STORY=<slug>`` now provisions
a private stack per worktree -- compose project ``meetingminer-<slug>`` on the
ports allocated here -- and records it in the worktree's gitignored
``.env.worktree``. Three readers take the same ``KEY=value`` lines from that
file: ``infra/Makefile`` (``-include``), ``docker compose`` (a second
``--env-file``, which wins over ``.env``) and the config loader
(``meetingminer.config.merged_env``: after ``.env``, before the process
environment).

Standard library only: the Makefile runs this with the system ``python3``
before the worktree has a venv.

Subcommands::

    provision --slug <slug> --worktree <dir> --worktree-root <dir>
    prune --worktree-root <dir>

``provision`` writes ``<dir>/.env.worktree`` (or keeps an existing one) and
prints its lines. ``prune`` tears down every compose project named
``meetingminer-<slug>`` whose owning checkout directory no longer exists;
``meetingminer`` itself and any other project are never listed.
"""

from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
import zlib
from collections.abc import Callable, Iterable
from pathlib import Path

#: The compose host ports, in the order they are allocated, with the values
#: every default reproduces (``infra/docker-compose.yml`` interpolates each
#: as ``${NAME:-default}``; ``test_compose_contract.py`` pins the pairing).
DEFAULT_PORTS: dict[str, int] = {
    "MM_POSTGRES_PORT": 5433,
    "MM_NEO4J_HTTP_PORT": 7474,
    "MM_NEO4J_BOLT_PORT": 7687,
    "MM_MEILI_PORT": 7700,
    "MM_NEO4J_TEST_HTTP_PORT": 7475,
    "MM_NEO4J_TEST_BOLT_PORT": 7688,
    "MM_MEILI_TEST_PORT": 7701,
}
PORT_NAMES: tuple[str, ...] = tuple(DEFAULT_PORTS)

STACK_NAME_VAR = "MM_STACK_NAME"
TEST_NEO4J_URI_VAR = "MM_TEST_NEO4J_URI"
TEST_MEILI_URL_VAR = "MM_TEST_MEILI_URL"
MAIN_PROJECT = "meetingminer"
PROJECT_PREFIX = "meetingminer-"
ENV_FILENAME = ".env.worktree"

#: A slug names the branch, the directory and the compose project, so it is
#: held to characters none of git, the filesystem or compose rewrites.
SLUG_PATTERN = r"[a-z0-9][a-z0-9._-]*"
_SLUG_RE = re.compile(rf"^{SLUG_PATTERN}$")

#: Bases 20000, 20010, ... 23990: a stack's seven ports are base+1..base+7,
#: so the range stays inside 20000-23999.
BASE_MIN = 20000
BASE_STEP = 10
BASE_COUNT = 400
PORT_RANGE_END = BASE_MIN + BASE_COUNT * BASE_STEP  # exclusive

Probe = Callable[[int], bool]
Run = Callable[[list[str]], str]


class StackError(Exception):
    """A named refusal. The CLI prints it and exits 1."""


def validate_slug(slug: str) -> str:
    if not _SLUG_RE.match(slug):
        raise StackError(
            f"STORY must match {SLUG_PATTERN} (it names the branch, the"
            f" directory and the compose project): got {slug!r}"
        )
    return slug


def stack_name(slug: str) -> str:
    return f"{PROJECT_PREFIX}{validate_slug(slug)}"


def base_index(slug: str) -> int:
    """The deterministic starting base for ``slug``: re-provisioning the same
    slug lands on the same ports unless something else took them."""
    return zlib.crc32(slug.encode("utf-8")) % BASE_COUNT


def ports_for_base(base: int) -> dict[str, int]:
    return {name: base + offset for offset, name in enumerate(PORT_NAMES, start=1)}


def port_is_free(port: int) -> bool:
    """True when nothing on this host holds ``port`` on the loopback address
    compose publishes to."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def allocate_ports(
    slug: str, taken: Iterable[int], probe: Probe = port_is_free
) -> dict[str, int]:
    """Seven free ports for ``slug``: its hashed base, else the next base with
    all seven free (``+10``, wrapping inside the range).

    A port counts as taken when ``taken`` names it (a sibling worktree's
    ``.env.worktree`` -- its stack may be down right now, and a bind probe
    alone could not see it) or when ``probe`` says it is bound.
    """
    taken_set = set(taken)
    start = base_index(slug)
    for step in range(BASE_COUNT):
        base = BASE_MIN + ((start + step) % BASE_COUNT) * BASE_STEP
        ports = ports_for_base(base)
        if any(port in taken_set for port in ports.values()):
            continue
        if not all(probe(port) for port in ports.values()):
            continue
        return ports
    raise StackError(
        f"no free port base for {slug!r}: all {BASE_COUNT} bases in"
        f" {BASE_MIN}-{PORT_RANGE_END - 1} are taken or bound"
    )


def parse_env_lines(text: str) -> dict[str, str]:
    """``KEY=value`` lines of a generated ``.env.worktree`` (comments and
    blank lines skipped, an ``export`` prefix and matching quotes dropped).

    This parses only files this module rendered; the loader keeps using
    python-dotenv for the full ``.env`` dialect.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def declared_ports(env_file: Path) -> set[int]:
    """The ports one ``.env.worktree`` declares (unparseable values ignored)."""
    ports: set[int] = set()
    try:
        values = parse_env_lines(env_file.read_text(encoding="utf-8"))
    except OSError:
        return ports
    for name in PORT_NAMES:
        raw = values.get(name)
        if raw is not None and raw.isdigit():
            ports.add(int(raw))
    return ports


def taken_ports(worktree_root: Path, exclude: Path | None = None) -> set[int]:
    """Every port a sibling worktree under ``worktree_root`` has declared."""
    ports: set[int] = set()
    if not worktree_root.is_dir():
        return ports
    for env_file in sorted(worktree_root.glob(f"*/{ENV_FILENAME}")):
        if exclude is not None and env_file.parent.resolve() == exclude.resolve():
            continue
        ports |= declared_ports(env_file)
    return ports


def render_env(slug: str, ports: dict[str, int]) -> str:
    """The ``.env.worktree`` text: the stack name, the seven ports, and the
    two test-twin URLs the test session already reads by name."""
    name = stack_name(slug)
    lines = [
        f"# Generated by `make worktree STORY={slug}` (infra/worktree_stack.py):",
        "# this worktree's private compose stack. Read by infra/Makefile",
        "# (-include), docker compose (a second --env-file, which wins over",
        "# .env) and the config loader (after .env, before the process",
        "# environment). Gitignored under the .env.* rule.",
        f"# `make worktree-remove STORY={slug}` tears the stack and its volumes",
        "# down; `make test-db-prune` sweeps a stack whose worktree is gone.",
        f"{STACK_NAME_VAR}={name}",
    ]
    lines.extend(f"{port_name}={ports[port_name]}" for port_name in PORT_NAMES)
    lines.append(f"{TEST_NEO4J_URI_VAR}=bolt://localhost:{ports['MM_NEO4J_TEST_BOLT_PORT']}")
    lines.append(f"{TEST_MEILI_URL_VAR}=http://localhost:{ports['MM_MEILI_TEST_PORT']}")
    return "\n".join(lines) + "\n"


def provision(
    slug: str,
    worktree: Path,
    worktree_root: Path,
    probe: Probe = port_is_free,
) -> tuple[Path, bool]:
    """Write ``<worktree>/.env.worktree`` for ``slug``; keep one that exists.

    Returns the file path and whether it was written now. Nothing is written
    when no ports can be allocated.
    """
    validate_slug(slug)
    env_file = worktree / ENV_FILENAME
    if env_file.is_file():
        return env_file, False
    if not worktree.is_dir():
        raise StackError(f"worktree directory does not exist: {worktree}")
    ports = allocate_ports(slug, taken_ports(worktree_root, exclude=worktree), probe)
    env_file.write_text(render_env(slug, ports), encoding="utf-8")
    return env_file, True


# --- prune -----------------------------------------------------------------

PS_ARGV = [
    "docker",
    "ps",
    "-a",
    "--filter",
    "label=com.docker.compose.project",
    "--format",
    '{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}',
]
VOLUME_ARGV = [
    "docker",
    "volume",
    "ls",
    "--filter",
    "label=com.docker.compose.project",
    "--format",
    '{{.Name}}\t{{.Label "com.docker.compose.project"}}',
]


def run_docker(argv: list[str]) -> str:
    """Run one docker command and return its stdout; any failure is named."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise StackError(f"docker unavailable: {' '.join(argv)}: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise StackError(f"{' '.join(argv)} failed: {detail}")
    return proc.stdout


def _tab_rows(output: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        first, _, second = line.partition("\t")
        rows.append((first.strip(), second.strip()))
    return rows


def worktree_stacks(
    ps_output: str, volume_output: str, worktree_root: Path
) -> dict[str, set[Path]]:
    """Compose projects named ``meetingminer-<slug>`` and where each one's
    checkout would be.

    A container carries compose's ``working_dir`` label -- the ``infra/``
    directory the stack was started from -- so its checkout is that
    directory's parent. Volumes carry only the project label, so a project
    with volumes and no containers is placed at ``<worktree_root>/<slug>``,
    exact because the slug rule forbids characters compose would rewrite.
    ``meetingminer`` and every foreign project are left out.
    """
    owners: dict[str, set[Path]] = {}
    for project, working_dir in _tab_rows(ps_output):
        if not project.startswith(PROJECT_PREFIX) or project == MAIN_PROJECT:
            continue
        dirs = owners.setdefault(project, set())
        if working_dir:
            dirs.add(Path(working_dir).parent)
    for _volume, project in _tab_rows(volume_output):
        if not project.startswith(PROJECT_PREFIX) or project == MAIN_PROJECT:
            continue
        owners.setdefault(project, set())
    for project, dirs in owners.items():
        if not dirs:
            dirs.add(worktree_root / project[len(PROJECT_PREFIX) :])
    return owners


def prune(
    worktree_root: Path,
    run: Run = run_docker,
    out: Callable[[str], None] = print,
) -> list[str]:
    """Tear down every worktree stack whose checkout directory is gone.

    Returns the removed project names. Anything whose directory exists is
    reported as owned and skipped; ``meetingminer`` is never a candidate.
    """
    stacks = worktree_stacks(run(PS_ARGV), run(VOLUME_ARGV), worktree_root)
    removed: list[str] = []
    for project in sorted(stacks):
        present = sorted(path for path in stacks[project] if path.exists())
        if present:
            out(f"skipped owned {project} ({present[0]})")
            continue
        run(["docker", "compose", "-p", project, "down", "-v", "--remove-orphans"])
        out(f"removed stack {project}")
        removed.append(project)
    if not stacks:
        out("no worktree stacks found")
    return removed


# --- CLI -------------------------------------------------------------------


def _cmd_provision(args: argparse.Namespace) -> int:
    env_file, written = provision(
        args.slug, Path(args.worktree), Path(args.worktree_root), probe=port_is_free
    )
    verb = "written" if written else "kept (already present)"
    print(f"{ENV_FILENAME} {verb}: {env_file}")
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            print(f"  {line}")
    return 0


def _cmd_prune(args: argparse.Namespace) -> int:
    prune(Path(args.worktree_root), run=run_docker)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    provision_cmd = commands.add_parser(
        "provision", help="write <worktree>/.env.worktree for a slug"
    )
    provision_cmd.add_argument("--slug", required=True)
    provision_cmd.add_argument("--worktree", required=True)
    provision_cmd.add_argument("--worktree-root", required=True)
    provision_cmd.set_defaults(func=_cmd_provision)
    prune_cmd = commands.add_parser(
        "prune", help="tear down worktree stacks whose checkout is gone"
    )
    prune_cmd.add_argument("--worktree-root", required=True)
    prune_cmd.set_defaults(func=_cmd_prune)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except StackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
