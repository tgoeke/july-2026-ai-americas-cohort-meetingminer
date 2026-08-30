#!/usr/bin/env python3
"""Per-worktree compose stacks (story 11.2): allocate, render, claim, prune.

Every checkout used to share one compose stack on fixed ports with fixed
container names, so two worktrees running store-backed suites queued on the
cross-worktree projection lock. ``make worktree STORY=<slug>`` now provisions
a private stack per worktree -- compose project ``meetingminer-<slug>`` on the
ports allocated here -- and records it in the worktree's gitignored
``.env.worktree``: the stack name, the seven host ports, the incarnation id
``MM_STACK_ID`` and the two test-twin URLs, exactly (``STACK_KEYS``).
``infra/Makefile`` (``-include``), ``docker compose`` (a second
``--env-file``) and the config loader (``meetingminer.config.merged_env``)
each read those keys, and every reader refuses a file that is incomplete,
incoherent, or carries any other key. The slug is always the checkout's
directory name, so ``git worktree move`` is not supported for a worktree
with a stack -- a renamed directory is refused by name.

Ownership has two layers, and each subcommand names the one it uses:

- **Directory ownership** (the general prune rule, ``make test-db-prune``):
  a ``meetingminer-<slug>`` project whose checkout directory exists is
  ``skipped owned``; one whose directory is gone and whose volumes are all
  recognised is removed; anything else is ``skipped unknown``, and a
  ``meetingminer-…`` name whose suffix is not a valid slug is
  ``skipped foreign``. ``meetingminer`` itself is never a candidate.
- **Incarnation ownership** (creation and every start, ``claim``): a project
  is *this worktree's* only when every one of its containers and volumes
  carries the ``com.meetingminer.stack-id`` label equal to the worktree
  file's ``MM_STACK_ID``. Anything else under that name -- no id, another
  id, a mix -- is a stale incarnation and is torn down before compose
  starts, never attached to.

``provision``, ``claim`` and ``prune`` all hold
``<worktree_root>/.provision.lock``, so allocation, publication, claiming
and destructive sweeps never interleave.

Standard library only: the Makefile runs this with the system ``python3``
before the worktree has a venv. The ``.env.worktree`` schema is therefore
spelled here *and* in ``meetingminer.config`` (which cannot import from
``infra/``); ``test_config.py`` pins the two equal.

Subcommands::

    provision --slug <slug> --worktree <dir> --worktree-root <dir>
        Write ``<dir>/.env.worktree`` atomically (keep a valid existing one,
        refuse a bad one by name) and print its lines.
    check --worktree <dir>
        Validate ``<dir>/.env.worktree`` against the directory name; exit 0
        silently, else the named error.
    identity --worktree <dir>
        Print the checkout-owned Compose project name and incarnation id.
    check-process-identity --worktree <dir>
        Refuse a non-blank process name/id that differs from the ownership
        record (or the main-checkout defaults).
    assert-identity --worktree <dir> --project <name> [--stack-id <id>]
        Re-read the record and refuse when Make's effective identity differs;
        this is the final backstop immediately before Compose executes.
    claim --worktree <dir> --worktree-root <root>
        Make the worktree's project safe to start: keep it when every
        container and volume carries the file's id, tear down a stale
        incarnation, refuse another checkout's stack or an unknown layout.
        ``infra-up``'s ``check-stack`` runs this before every start.
    down --project meetingminer-<slug> --worktree <dir>
         --worktree-root <root> [--stack-id <id>]
        Tear one recognised stack and its volumes down only after its layout,
        directory ownership and (when available) incarnation id agree; Docker
        off or an absent stack is a note, but an ownership, inventory or
        teardown failure is a named error.
    prune --worktree-root <dir> [--project meetingminer-<slug>]
        Tear down every worktree stack whose checkout directory is gone.
        With ``--project`` only that project, and an owner that still exists
        or an unknown layout is an error (``make worktree`` runs it before
        provisioning a slug).
"""

from __future__ import annotations

import argparse
import fcntl
import os
import re
import secrets
import socket
import subprocess
import sys
import zlib
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
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
#: The stack's incarnation identity: 12 lowercase hex, generated per
#: `provision`, stamped on every container and volume as the compose label
#: `com.meetingminer.stack-id`. Two incarnations of the same slug share the
#: directory, the project name and (deterministic allocator) usually the
#: ports — the id is what tells them apart, so `claim` can tear down a stale
#: same-named project instead of attaching to its volumes.
STACK_ID_VAR = "MM_STACK_ID"
STACK_ID_LABEL = "com.meetingminer.stack-id"
_STACK_ID_RE = re.compile(r"^[0-9a-f]{12}$")
TEST_NEO4J_URI_VAR = "MM_TEST_NEO4J_URI"
TEST_MEILI_URL_VAR = "MM_TEST_MEILI_URL"
#: Every key a rendered file carries, in the order it carries them — and the
#: only keys: `validate_env_file` refuses a file whose key set differs, and
#: the loader (`meetingminer.config.merged_env`) applies the same schema.
STACK_KEYS: tuple[str, ...] = (
    STACK_NAME_VAR,
    *PORT_NAMES,
    STACK_ID_VAR,
    TEST_NEO4J_URI_VAR,
    TEST_MEILI_URL_VAR,
)
MAIN_PROJECT = "meetingminer"
PROJECT_PREFIX = "meetingminer-"
ENV_FILENAME = ".env.worktree"
LOCK_FILENAME = ".provision.lock"

#: The compose file's volume names; compose stores them as ``<project>_<name>``.
VOLUME_NAMES: tuple[str, ...] = (
    "postgres-data",
    "neo4j-data",
    "neo4j-logs",
    "meilisearch-data",
    "neo4j-test-data",
    "neo4j-test-logs",
    "meilisearch-test-data",
)

#: A slug names the branch, the directory and the compose project, so it is
#: held to characters none of git, the filesystem or compose rewrites or
#: rejects (compose refuses ``.`` in a project name).
SLUG_PATTERN = r"[a-z0-9][a-z0-9_-]*"
_SLUG_RE = re.compile(rf"^{SLUG_PATTERN}$")
#: A worktree stack's project name, exactly: the prefix plus a valid slug.
#: `meetingminer-Foo` or `meetingminer-` is a foreign project, not ours.
_PROJECT_RE = re.compile(rf"^{re.escape(PROJECT_PREFIX)}{SLUG_PATTERN}$")
_ASSIGNMENT_RE = re.compile(
    r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=(.*)$"
)

#: Bases 20000, 20010, ... 23990: a stack's seven ports are base+1..base+7,
#: so the range stays inside 20000-23999.
BASE_MIN = 20000
BASE_STEP = 10
BASE_COUNT = 400
PORT_RANGE_END = BASE_MIN + BASE_COUNT * BASE_STEP  # exclusive

DOCKER_TIMEOUT_SECONDS = 120

Probe = Callable[[int], bool]
Run = Callable[[list[str]], str]


class StackError(Exception):
    """A named refusal. The CLI prints it and exits 1."""


def validate_slug(slug: str) -> str:
    if not _SLUG_RE.fullmatch(slug):
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


def parse_ownership_record(text: str, env_file: Path) -> dict[str, str]:
    """Strict ``.env.worktree`` syntax: data assignments, never Make code.

    Generated comments and blank lines are allowed. Every other line must be
    one ``KEY=value`` assignment (an ``export`` prefix and matching quotes are
    accepted for reader parity), and a key may appear exactly once. No line is
    ignored and no duplicate silently replaces an earlier ownership fact.
    """
    values: dict[str, str] = {}
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT_RE.fullmatch(raw)
        if match is None:
            raise StackError(
                f"{env_file}: invalid line {line_number}: {raw!r} — the file"
                " carries data assignments only, never Make directives"
            )
        key = match.group(1)
        if key in values:
            raise StackError(
                f"{env_file}: duplicate {key} on line {line_number} — each"
                " ownership key must be assigned exactly once"
            )
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def read_env_file(env_file: Path) -> dict[str, str]:
    try:
        return parse_ownership_record(env_file.read_text(encoding="utf-8"), env_file)
    except OSError as exc:
        raise StackError(f"{env_file} is unreadable: {exc}") from exc


def _remedy(env_file: Path, slug: str) -> str:
    return (
        f"delete {env_file} and run 'make worktree-start STORY={slug}' from"
        " the main checkout (or 'make worktree-provision' inside a post-11.2"
        " worktree); the stack is recreated and its volumes discarded"
    )


def validate_env_file(env_file: Path, slug: str) -> dict[str, str]:
    """The single ``.env.worktree`` schema: the values of a file that is this
    checkout's complete, coherent ownership record — else a named refusal.

    ``slug`` is the checkout's directory name (``make worktree`` always
    creates ``<WT_ROOT>/<slug>`` and ``worktree-provision`` keys on it), so a
    renamed or moved directory is refused by name: ``git worktree move`` is
    not supported for a worktree with a stack.

    The loader (``meetingminer.config.merged_env``) applies the same rules
    minus this slug/directory check — it does not know the checkout. The rule
    is spelled twice because this module must run stdlib-only under the
    system ``python3`` before a venv exists, while the server package cannot
    import from ``infra/``; ``test_config.py`` pins the two equal.
    """
    validate_slug(slug)
    try:
        values = read_env_file(env_file)
    except StackError as exc:
        raise StackError(f"{exc} — {_remedy(env_file, slug)}") from exc

    def refuse(problem: str) -> StackError:
        return StackError(f"{env_file}: {problem} — {_remedy(env_file, slug)}")

    foreign = [key for key in values if key not in STACK_KEYS]
    if foreign:
        raise refuse(
            f"{', '.join(foreign)} is not a stack key (the file carries"
            f" exactly {', '.join(STACK_KEYS)})"
        )
    missing = [key for key in STACK_KEYS if key not in values]
    if missing:
        raise refuse(f"missing {', '.join(missing)}")
    blank = [key for key in STACK_KEYS if not values[key].strip()]
    if blank:
        raise refuse(f"{', '.join(blank)} is blank")
    expected_name = stack_name(slug)
    if values[STACK_NAME_VAR] != expected_name:
        raise refuse(
            f"{STACK_NAME_VAR} is {values[STACK_NAME_VAR]!r} but this checkout"
            f" is {slug!r}, whose stack is {expected_name!r} ('git worktree"
            " move' is not supported for a worktree with a stack)"
        )
    ports: dict[str, int] = {}
    for name in PORT_NAMES:
        raw = values[name]
        if not (raw.isascii() and raw.isdigit()) or not 1 <= int(raw) <= 65535:
            raise refuse(f"{name} must be an integer port in 1..65535, got {raw!r}")
        ports[name] = int(raw)
    duplicated = [
        name for name in PORT_NAMES
        if list(ports.values()).count(ports[name]) > 1
    ]
    if duplicated:
        raise refuse(f"{', '.join(duplicated)} declare the same port")
    defaults = set(DEFAULT_PORTS.values())
    clashing = [name for name in PORT_NAMES if ports[name] in defaults]
    if clashing:
        raise refuse(
            f"{', '.join(clashing)} names a main-checkout default port — a"
            " worktree on it would reach the main stack"
        )
    if not _STACK_ID_RE.fullmatch(values[STACK_ID_VAR]):
        raise refuse(
            f"{STACK_ID_VAR} must be 12 lowercase hex characters, got"
            f" {values[STACK_ID_VAR]!r}"
        )
    expected_neo4j = f"bolt://localhost:{ports['MM_NEO4J_TEST_BOLT_PORT']}"
    if values[TEST_NEO4J_URI_VAR] != expected_neo4j:
        raise refuse(
            f"{TEST_NEO4J_URI_VAR} is {values[TEST_NEO4J_URI_VAR]!r}, not the"
            f" declared test port's {expected_neo4j!r}"
        )
    expected_meili = f"http://localhost:{ports['MM_MEILI_TEST_PORT']}"
    if values[TEST_MEILI_URL_VAR] != expected_meili:
        raise refuse(
            f"{TEST_MEILI_URL_VAR} is {values[TEST_MEILI_URL_VAR]!r}, not the"
            f" declared test port's {expected_meili!r}"
        )
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


def _sibling_env_files(worktree_root: Path) -> list[Path]:
    if not worktree_root.is_dir():
        return []
    return sorted(worktree_root.glob(f"*/{ENV_FILENAME}"))


def taken_ports(worktree_root: Path, exclude: Path | None = None) -> set[int]:
    """Every port a sibling worktree under ``worktree_root`` has declared."""
    ports: set[int] = set()
    for env_file in _sibling_env_files(worktree_root):
        if exclude is not None and env_file.parent.resolve() == exclude.resolve():
            continue
        ports |= declared_ports(env_file)
    return ports


def declared_owners(worktree_root: Path) -> dict[str, Path]:
    """``project -> checkout directory`` for every ``.env.worktree`` under the
    root, by the ``MM_STACK_NAME`` it declares. A worktree moved with
    ``git worktree move`` keeps its file, so this is what still owns it."""
    owners: dict[str, Path] = {}
    for env_file in _sibling_env_files(worktree_root):
        try:
            name = parse_env_lines(env_file.read_text(encoding="utf-8")).get(STACK_NAME_VAR)
        except OSError:
            continue
        # Only a valid meetingminer-<slug> name grants ownership: a broken
        # sibling file must not break allocation, but neither may it claim
        # `meetingminer` or a foreign project.
        if name and _PROJECT_RE.fullmatch(name):
            owners.setdefault(name, env_file.parent)
    return owners


def render_env(slug: str, ports: dict[str, int], stack_id: str) -> str:
    """The ``.env.worktree`` text: the stack name, the seven ports, the
    incarnation id, and the two test-twin URLs the test session reads by
    name — exactly ``STACK_KEYS``, in order."""
    name = stack_name(slug)
    if not _STACK_ID_RE.fullmatch(stack_id):
        raise StackError(
            f"{STACK_ID_VAR} must be 12 lowercase hex characters, got {stack_id!r}"
        )
    lines = [
        f"# Generated by `make worktree STORY={slug}` (infra/worktree_stack.py):",
        "# this worktree's private compose stack and its ownership record.",
        "# Read by infra/Makefile (-include), docker compose (a second",
        "# --env-file) and the config loader (after .env, before the process",
        "# environment). Stack keys only: every reader refuses any other key",
        "# here, and refuses an incomplete or incoherent file whole.",
        "# MM_STACK_ID is this incarnation's identity, stamped on the stack's",
        "# containers and volumes; a same-named stack without it is stale and",
        "# is torn down before this worktree's stack starts. Gitignored",
        f"# (.env.*). `make worktree-remove STORY={slug}` tears the stack and",
        "# its volumes down; `make test-db-prune` sweeps a stack whose",
        "# worktree is gone.",
        f"{STACK_NAME_VAR}={name}",
    ]
    lines.extend(f"{port_name}={ports[port_name]}" for port_name in PORT_NAMES)
    lines.append(f"{STACK_ID_VAR}={stack_id}")
    lines.append(f"{TEST_NEO4J_URI_VAR}=bolt://localhost:{ports['MM_NEO4J_TEST_BOLT_PORT']}")
    lines.append(f"{TEST_MEILI_URL_VAR}=http://localhost:{ports['MM_MEILI_TEST_PORT']}")
    return "\n".join(lines) + "\n"


@contextmanager
def _provision_lock(worktree_root: Path) -> Iterator[None]:
    """The one exclusion for allocation, publication, claiming and pruning:
    ``<worktree_root>/.provision.lock``, held exclusively. A sweep that ran
    against a pre-lock inventory snapshot could tear down a stack a
    concurrent ``make worktree`` had just created (finding 7). The root must
    already exist — creating it here would make ``prune`` invent a place to
    put volumes-only projects."""
    with open(worktree_root / LOCK_FILENAME, "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def provision(
    slug: str,
    worktree: Path,
    worktree_root: Path,
    probe: Probe = port_is_free,
) -> tuple[Path, bool]:
    """Write ``<worktree>/.env.worktree`` for ``slug``; keep a valid one.

    Returns the file path and whether it was written now. An existing file
    must pass :func:`validate_env_file` for this slug — a truncated,
    hand-edited or copied file is refused by name, never kept. Allocation
    and publication happen under :func:`_provision_lock` so two concurrent
    provisions cannot pick the same base, and publication is atomic
    (rendered to a temp file, ``os.replace``-d into place): nothing named
    ``.env.worktree`` ever holds a partial write.
    """
    validate_slug(slug)
    env_file = worktree / ENV_FILENAME
    if env_file.is_file():
        validate_env_file(env_file, slug)
        return env_file, False
    if not worktree.is_dir():
        raise StackError(f"worktree directory does not exist: {worktree}")
    temp_file = worktree / f"{ENV_FILENAME}.tmp-{os.getpid()}"
    try:
        worktree_root.mkdir(parents=True, exist_ok=True)
        with _provision_lock(worktree_root):
            # The file may have been published by another provisioner after
            # our fast-path existence check but before this lock acquisition.
            # Its complete record wins; a waiter must never mint a second id
            # for the same target and overwrite the first incarnation.
            if env_file.is_file():
                validate_env_file(env_file, slug)
                return env_file, False
            ports = allocate_ports(slug, taken_ports(worktree_root, exclude=worktree), probe)
            text = render_env(slug, ports, secrets.token_hex(6))
            try:
                temp_file.write_text(text, encoding="utf-8")
                os.replace(temp_file, env_file)
            except OSError:
                temp_file.unlink(missing_ok=True)
                raise
    except OSError as exc:
        raise StackError(f"cannot write {env_file}: {exc}") from exc
    return env_file, True


# --- prune -----------------------------------------------------------------

PS_ARGV = [
    "docker",
    "ps",
    "-a",
    "--filter",
    "label=com.docker.compose.project",
    "--format",
    '{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}\t{{.Label "com.meetingminer.stack-id"}}',
]
VOLUME_ARGV = [
    "docker",
    "volume",
    "ls",
    "--filter",
    "label=com.docker.compose.project",
    "--format",
    '{{.Name}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.meetingminer.stack-id"}}',
]


def run_docker(argv: list[str]) -> str:
    """Run one docker command and return its stdout; any failure is named."""
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, check=False, timeout=DOCKER_TIMEOUT_SECONDS
        )
    except OSError as exc:
        raise StackError(f"docker unavailable: {' '.join(argv)}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise StackError(
            f"{' '.join(argv)} did not finish within {DOCKER_TIMEOUT_SECONDS}s"
        ) from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise StackError(f"{' '.join(argv)} failed: {detail}")
    return proc.stdout


def _tab_rows(output: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        first, _, rest = line.partition("\t")
        second, _, third = rest.partition("\t")
        rows.append((first.strip(), second.strip(), third.strip()))
    return rows


def _is_worktree_project(project: str) -> bool:
    """Exactly ``meetingminer-<valid slug>``: only a name this tool could
    have provisioned may ever be classified, let alone torn down.
    ``meetingminer-Foo``, ``meetingminer-`` or ``meetingminer-.backup`` is a
    foreign project, whatever its prefix (finding 2)."""
    return bool(_PROJECT_RE.fullmatch(project)) and project != MAIN_PROJECT


@dataclass
class Stack:
    """One ``meetingminer-<slug>`` compose project and where its checkout
    would be. ``unknown`` marks a project this tool will not touch: volumes
    it does not recognise, or nowhere to place a volumes-only project.
    ``ids`` and ``volume_ids`` are the ``com.meetingminer.stack-id`` labels
    on its containers and volumes (the empty string for an unlabeled one) —
    the incarnation identities ``claim`` compares against the worktree's
    ``.env.worktree``."""

    project: str
    owners: set[Path] = field(default_factory=set)
    unknown: bool = False
    ids: set[str] = field(default_factory=set)
    volume_ids: set[str] = field(default_factory=set)

    @property
    def present_owner(self) -> Path | None:
        present = sorted(path for path in self.owners if path.exists())
        return present[0] if present else None


def worktree_stacks(
    ps_output: str, volume_output: str, worktree_root: Path
) -> tuple[dict[str, Stack], list[str]]:
    """Every ``meetingminer-<slug>`` project docker knows, classified, plus
    the sorted foreign names (a ``meetingminer-`` prefix whose suffix is not
    a valid slug) that must only ever be reported.

    A container carries compose's ``working_dir`` label -- the ``infra/``
    directory the stack was started from -- so its checkout is that
    directory's parent. A ``.env.worktree`` under ``worktree_root`` that
    declares the project's name owns it too (a moved worktree keeps its file).
    ``unknown`` is computed for **every** candidate from its volumes,
    containers or not (finding 3): a volume that is not one of the compose
    file's seven (``<project>_<name>``) marks the project untouchable. A
    recognised volumes-only project is placed at ``<worktree_root>/<slug>``
    when the root exists, else it is ``unknown`` too. ``meetingminer`` and
    every project without the prefix are left out entirely.
    """
    containers: dict[str, set[str]] = {}
    container_ids: dict[str, set[str]] = {}
    foreign: set[str] = set()

    def classify(project: str) -> bool:
        if not project.startswith(PROJECT_PREFIX) or project == MAIN_PROJECT:
            return False
        if not _is_worktree_project(project):
            foreign.add(project)
            return False
        return True

    for project, working_dir, stack_id in _tab_rows(ps_output):
        if not classify(project):
            continue
        containers.setdefault(project, set())
        container_ids.setdefault(project, set()).add(stack_id)
        if working_dir:
            containers[project].add(working_dir)
    volumes: dict[str, list[str]] = {}
    volume_ids: dict[str, set[str]] = {}
    for volume, project, stack_id in _tab_rows(volume_output):
        if not classify(project):
            continue
        volumes.setdefault(project, []).append(volume)
        volume_ids.setdefault(project, set()).add(stack_id)
    declared = declared_owners(worktree_root)

    stacks: dict[str, Stack] = {}
    for project in sorted(set(containers) | set(volumes)):
        stack = Stack(
            project,
            ids=container_ids.get(project, set()),
            volume_ids=volume_ids.get(project, set()),
        )
        stack.owners.update(Path(wd).parent for wd in containers.get(project, ()))
        if project in declared:
            stack.owners.add(declared[project])
        ours = {f"{project}_{name}" for name in VOLUME_NAMES}
        stack.unknown = not all(volume in ours for volume in volumes.get(project, []))
        if not stack.owners and not stack.unknown:
            if worktree_root.is_dir():
                stack.owners.add(worktree_root / project[len(PROJECT_PREFIX) :])
            else:
                stack.unknown = True
        stacks[project] = stack
    return stacks, sorted(foreign)


def down(
    project: str,
    worktree: Path,
    worktree_root: Path,
    stack_id: str | None = None,
    run: Run = run_docker,
    out: Callable[[str], None] = print,
) -> None:
    """Tear one worktree stack and its volumes down, honestly (finding 6).

    A valid project name alone is not ownership. The recognised compose layout
    must resolve only to ``worktree``; when the removed checkout had a valid
    ownership record, every remaining container and volume must also carry its
    ``stack_id``. A missing pre-11.2 record keeps the frozen fallback, but only
    for a recognised layout owned by the expected directory. Inventory and
    teardown hold the provisioning lock, closing the check/remove race against
    provision, claim and prune.

    Docker being off is a note (``make test-db-prune`` sweeps later) and an
    absent stack is a note; an ownership mismatch, failed inventory or failed
    ``down -v`` is a named error. ``make worktree-remove`` and
    ``worktree-prune`` call this and propagate its status.
    """
    if not _is_worktree_project(project):
        raise StackError(
            f"refusing to tear down stack {project!r} — only"
            " meetingminer-<slug> stacks belong to worktrees"
        )
    worktree = Path(worktree).absolute()
    worktree_root = Path(worktree_root).absolute()
    stack_id = stack_id or None
    if stack_id is not None and not _STACK_ID_RE.fullmatch(stack_id):
        raise StackError(
            f"{STACK_ID_VAR} must be 12 lowercase hex characters, got {stack_id!r}"
        )
    try:
        run(["docker", "info"])
    except StackError:
        out(
            f"note: Docker daemon not running — stack {project} left in"
            " place; 'make test-db-prune' sweeps it once its worktree is gone"
        )
        return
    guard = _provision_lock(worktree_root) if worktree_root.is_dir() else nullcontext()
    with guard:
        stacks, _foreign = worktree_stacks(run(PS_ARGV), run(VOLUME_ARGV), worktree_root)
        stack = stacks.get(project)
        if stack is None:
            out(f"note: stack {project} was already gone")
            return
        if stack.unknown:
            raise StackError(
                f"refusing to tear down stack {project}: its containers or"
                " volumes do not match the recognised worktree-stack layout"
            )
        expected_owner = worktree.resolve()
        foreign_owners = sorted(
            owner for owner in stack.owners if owner.resolve() != expected_owner
        )
        if foreign_owners:
            raise StackError(
                f"refusing to tear down stack {project}: it belongs to"
                f" {foreign_owners[0]}, not the removed checkout {worktree}"
            )
        if stack_id is not None and (stack.ids | stack.volume_ids) != {stack_id}:
            observed = sorted(stack.ids | stack.volume_ids)
            raise StackError(
                f"refusing to tear down stack {project}: its"
                f" {STACK_ID_LABEL} labels {observed!r} do not all match"
                f" {stack_id!r} from the removed checkout's {ENV_FILENAME}"
            )
        run(["docker", "compose", "-p", project, "down", "-v", "--remove-orphans"])
        out(f"removed stack {project}")


def claim(
    worktree: Path,
    worktree_root: Path,
    run: Run = run_docker,
    out: Callable[[str], None] = print,
) -> None:
    """Make ``<worktree>``'s compose project safe to start (findings 4, 5).

    Incarnation ownership: the project is *this worktree's* only when every
    one of its containers and volumes carries the ``MM_STACK_ID`` of the
    worktree's validated ``.env.worktree``. Anything else under that name —
    no id (a pre-remediation or hand-deleted worktree's leavings), another
    id, or a mix — is a stale incarnation and is torn down (``down -v``)
    before compose starts, never attached to. A present owner other than
    this worktree, or a layout this tool does not recognise, is an error.
    Runs under :func:`_provision_lock` so it cannot interleave with a
    concurrent provision or prune. ``infra-up``'s ``check-stack``
    prerequisite runs this before every ``up`` that has a stack file, so
    the Docker-down retry, the compose-failure retry, an old-ref worktree's
    start and a plain restart are all the same path.
    """
    worktree = Path(worktree).absolute()
    env_file = worktree / ENV_FILENAME
    values = validate_env_file(env_file, worktree.name)
    name = values[STACK_NAME_VAR]
    stack_id = values[STACK_ID_VAR]
    worktree_root.mkdir(parents=True, exist_ok=True)
    with _provision_lock(worktree_root):
        stacks, _foreign = worktree_stacks(run(PS_ARGV), run(VOLUME_ARGV), worktree_root)
        stack = stacks.get(name)
        if stack is None:
            out(f"no stale stack {name}")
            return
        target = worktree.resolve()
        foreign_owners = sorted(
            path for path in stack.owners
            if path.exists() and path.resolve() != target
        )
        if foreign_owners:
            raise StackError(
                f"stack {name} belongs to the existing checkout"
                f" {foreign_owners[0]} — remove that worktree"
                " (make worktree-remove) or pick another STORY"
            )
        if stack.unknown:
            raise StackError(
                f"a compose project named {name} exists with containers or"
                " volumes this tool does not recognise — inspect it and"
                f" remove it by hand (docker compose -p {name} down -v) first"
            )
        if stack.ids | stack.volume_ids == {stack_id}:
            out(f"kept stack {name} (this worktree's)")
            return
        run(["docker", "compose", "-p", name, "down", "-v", "--remove-orphans"])
        out(f"removed stale stack {name} (not started from {env_file})")


def prune(
    worktree_root: Path,
    run: Run = run_docker,
    out: Callable[[str], None] = print,
    project: str | None = None,
) -> list[str]:
    """Tear down every worktree stack whose checkout directory is gone.

    Returns the removed project names. A stack whose directory exists is
    reported as owned and skipped; an ``unknown`` one is reported and
    skipped; ``meetingminer`` is never a candidate. A ``down`` that fails is
    reported and the sweep continues, then the whole run fails by name.

    With ``project``, only that project is considered, and an existing owner
    or an unknown layout is an error: the caller is about to create a stack
    of that name and must not attach to someone else's.

    Inventory and every teardown run under :func:`_provision_lock`, the same
    file ``provision`` and ``claim`` hold, so a sweep never interleaves with
    a concurrent creation (finding 7); and ownership is re-resolved
    immediately before every ``down -v`` — a directory that appeared after
    the snapshot always wins.
    """
    # An absent root holds no lock file and no worktrees to interleave with;
    # taking the lock there would also *create* the root and hand
    # volumes-only projects a place they never had.
    guard = _provision_lock(worktree_root) if worktree_root.is_dir() else nullcontext()
    with guard:
        stacks, foreign = worktree_stacks(run(PS_ARGV), run(VOLUME_ARGV), worktree_root)
        if project is not None:
            stacks = {name: stack for name, stack in stacks.items() if name == project}
            if not stacks:
                out(f"no stale stack {project}")
                return []
        else:
            for name in foreign:
                out(f"skipped foreign {name} (not a meetingminer-<slug> name)")
        removed: list[str] = []
        failed: list[str] = []
        for name in sorted(stacks):
            stack = stacks[name]
            owner = stack.present_owner
            if owner is not None:
                if project is not None:
                    raise StackError(
                        f"stack {name} belongs to the existing checkout {owner} —"
                        " remove that worktree (make worktree-remove) or pick another STORY"
                    )
                out(f"skipped owned {name} ({owner})")
                continue
            if stack.unknown:
                if project is not None:
                    raise StackError(
                        f"a compose project named {name} exists with containers or"
                        " volumes this tool does not recognise — inspect it and"
                        f" remove it by hand (docker compose -p {name} down -v) first"
                    )
                out(f"skipped unknown {name}")
                continue
            # Re-resolve immediately before the teardown: the owner directory
            # may have appeared since the check above.
            owner = stack.present_owner
            if owner is not None:
                out(f"skipped owned {name} ({owner})")
                continue
            try:
                run(["docker", "compose", "-p", name, "down", "-v", "--remove-orphans"])
            except StackError as exc:
                failed.append(name)
                out(f"failed {name}: {exc}")
                continue
            out(f"removed stack {name}")
            removed.append(name)
        if not stacks:
            out("no worktree stacks found")
        if failed:
            raise StackError(f"{len(failed)} stack(s) could not be removed: {', '.join(failed)}")
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
    prune(Path(args.worktree_root), run=run_docker, project=args.project)
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    worktree = Path(args.worktree).absolute()
    validate_env_file(worktree / ENV_FILENAME, worktree.name)
    return 0


def _declared_identity(worktree: Path) -> tuple[str, str]:
    """Return the checkout-owned Compose identity, never a process override."""
    worktree = worktree.absolute()
    env_file = worktree / ENV_FILENAME
    if env_file.is_file():
        values = validate_env_file(env_file, worktree.name)
        return values[STACK_NAME_VAR], values[STACK_ID_VAR]
    return MAIN_PROJECT, ""


def _cmd_identity(args: argparse.Namespace) -> int:
    project, stack_id = _declared_identity(Path(args.worktree))
    print(f"{project} {stack_id}")
    return 0


def _cmd_check_process_identity(args: argparse.Namespace) -> int:
    project, stack_id = _declared_identity(Path(args.worktree))
    expected = {STACK_NAME_VAR: project, STACK_ID_VAR: stack_id}
    for key, declared in expected.items():
        requested = os.environ.get(key, "").strip()
        if requested and requested != declared:
            raise StackError(
                f"{key} effective process value {requested!r} does not match"
                f" ownership record value {declared!r}; the process environment"
                " cannot override stack identity"
            )
    return 0


def _cmd_assert_identity(args: argparse.Namespace) -> int:
    project, stack_id = _declared_identity(Path(args.worktree))
    if args.project != project:
        raise StackError(
            f"{STACK_NAME_VAR} effective value {args.project!r} does not match"
            f" ownership record value {project!r}; the record changed after Make parsed it"
        )
    if args.stack_id != stack_id:
        raise StackError(
            f"{STACK_ID_VAR} effective value {args.stack_id!r} does not match"
            f" ownership record value {stack_id!r}; the record changed after Make parsed it"
        )
    return 0


def _cmd_claim(args: argparse.Namespace) -> int:
    claim(Path(args.worktree), Path(args.worktree_root), run=run_docker)
    return 0


def _cmd_down(args: argparse.Namespace) -> int:
    down(
        args.project,
        Path(args.worktree),
        Path(args.worktree_root),
        stack_id=args.stack_id,
        run=run_docker,
    )
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
    check_cmd = commands.add_parser(
        "check", help="validate <worktree>/.env.worktree against the directory name"
    )
    check_cmd.add_argument("--worktree", required=True)
    check_cmd.set_defaults(func=_cmd_check)
    identity_cmd = commands.add_parser(
        "identity", help="print the checkout-owned Compose project name and incarnation id"
    )
    identity_cmd.add_argument("--worktree", required=True)
    identity_cmd.set_defaults(func=_cmd_identity)
    process_identity_cmd = commands.add_parser(
        "check-process-identity",
        help="refuse process values that differ from the checkout-owned identity",
    )
    process_identity_cmd.add_argument("--worktree", required=True)
    process_identity_cmd.set_defaults(func=_cmd_check_process_identity)
    assert_identity_cmd = commands.add_parser(
        "assert-identity",
        help="compare Make's effective Compose identity with the live ownership record",
    )
    assert_identity_cmd.add_argument("--worktree", required=True)
    assert_identity_cmd.add_argument("--project", required=True)
    assert_identity_cmd.add_argument("--stack-id", default="")
    assert_identity_cmd.set_defaults(func=_cmd_assert_identity)
    claim_cmd = commands.add_parser(
        "claim",
        help="tear down a stale same-named stack before this worktree's starts",
    )
    claim_cmd.add_argument("--worktree", required=True)
    claim_cmd.add_argument("--worktree-root", required=True)
    claim_cmd.set_defaults(func=_cmd_claim)
    down_cmd = commands.add_parser(
        "down", help="tear down one worktree-owned stack and its volumes"
    )
    down_cmd.add_argument("--project", required=True)
    down_cmd.add_argument("--worktree", required=True)
    down_cmd.add_argument("--worktree-root", required=True)
    down_cmd.add_argument("--stack-id", default="")
    down_cmd.set_defaults(func=_cmd_down)
    prune_cmd = commands.add_parser(
        "prune", help="tear down worktree stacks whose checkout is gone"
    )
    prune_cmd.add_argument("--worktree-root", required=True)
    prune_cmd.add_argument(
        "--project", help="act on this meetingminer-<slug> project only; an owner is an error"
    )
    prune_cmd.set_defaults(func=_cmd_prune)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except StackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
