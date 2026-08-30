"""infra/worktree_stack.py (story 11.2): the per-worktree stack allocator,
the `.env.worktree` renderer and the orphan-stack pruner — plus the conftest
helpers that read the result (`twin_endpoints`) and refuse a linked worktree
that has no stack file (`linked_worktree_without_stack`).

Pure-function coverage with a fake bind probe and a recording fake `docker`
runner -- no Docker, no store, no network. The module is stdlib-only and
lives under infra/ (the Makefile runs it with the system python3), so it is
loaded here by path rather than imported as a package.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from dotenv import dotenv_values

from conftest import linked_worktree_refusal, twin_endpoints
from meetingminer.config import merged_env
from repo_paths import REPO_ROOT


def _load_module() -> ModuleType:
    path = REPO_ROOT / "infra" / "worktree_stack.py"
    spec = importlib.util.spec_from_file_location("worktree_stack", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations via sys.modules
    spec.loader.exec_module(module)
    return module


ws = _load_module()

ALL_FREE = lambda port: True  # noqa: E731 - a probe that finds every port free
NONE_FREE = lambda port: False  # noqa: E731
SLUG_RULE_RE = r"\[a-z0-9\]\[a-z0-9_-\]\*"


def _slug_with_base_index(index: int) -> str:
    """A slug whose deterministic base is `index` (search is cheap: 400 buckets)."""
    for n in range(100_000):
        slug = f"s{n}"
        if ws.base_index(slug) == index:
            return slug
    raise AssertionError(f"no slug hashed to base index {index}")


# --- defaults and slugs ----------------------------------------------------


def test_defaults_reproduce_todays_stack() -> None:
    assert ws.DEFAULT_PORTS == {
        "MM_POSTGRES_PORT": 5433,
        "MM_NEO4J_HTTP_PORT": 7474,
        "MM_NEO4J_BOLT_PORT": 7687,
        "MM_MEILI_PORT": 7700,
        "MM_NEO4J_TEST_HTTP_PORT": 7475,
        "MM_NEO4J_TEST_BOLT_PORT": 7688,
        "MM_MEILI_TEST_PORT": 7701,
    }
    assert ws.MAIN_PROJECT == "meetingminer"
    assert ws.stack_name("11-2") == "meetingminer-11-2"
    assert ws.STACK_KEYS == (
        "MM_STACK_NAME",
        *ws.PORT_NAMES,
        "MM_STACK_ID",
        "MM_TEST_NEO4J_URI",
        "MM_TEST_MEILI_URL",
    )


@pytest.mark.parametrize("slug", ["Foo_Bar!", "-lead", "UPPER", "a b", "", "x/y", "a.b_c", "v1.2"])
def test_bad_slug_is_refused_by_name(slug: str) -> None:
    """Compose rejects `.` in a project name, so the rule refuses it too."""
    with pytest.raises(ws.StackError, match=SLUG_RULE_RE):
        ws.validate_slug(slug)


@pytest.mark.parametrize("slug", ["11-2", "1-7-remediation", "a_b-c", "0"])
def test_good_slug_passes(slug: str) -> None:
    assert ws.validate_slug(slug) == slug


# --- allocation ------------------------------------------------------------


def test_allocation_is_deterministic_and_inside_the_range() -> None:
    first = ws.allocate_ports("11-2", set(), ALL_FREE)
    second = ws.allocate_ports("11-2", set(), ALL_FREE)
    assert first == second
    assert tuple(first) == ws.PORT_NAMES
    values = list(first.values())
    assert values == list(range(values[0], values[0] + 7))
    assert (values[0] - 1 - ws.BASE_MIN) % ws.BASE_STEP == 0
    assert ws.BASE_MIN < values[0] and values[-1] < ws.PORT_RANGE_END


def test_two_slugs_with_different_hashed_bases_get_different_ports() -> None:
    a, b = "11-2", "11-3"
    assert ws.base_index(a) != ws.base_index(b)
    assert ws.allocate_ports(a, set(), ALL_FREE) != ws.allocate_ports(b, set(), ALL_FREE)


def test_a_bound_port_moves_to_the_next_base() -> None:
    home = ws.ports_for_base(ws.BASE_MIN + ws.base_index("probe") * ws.BASE_STEP)
    bound = home["MM_MEILI_PORT"]
    ports = ws.allocate_ports("probe", set(), lambda port: port != bound)
    assert ports["MM_POSTGRES_PORT"] == home["MM_POSTGRES_PORT"] + ws.BASE_STEP


def test_sibling_declared_ports_count_as_taken(tmp_path: Path) -> None:
    """A sibling whose stack is down is invisible to a bind probe; its file is not."""
    root = tmp_path / "wt"
    (root / "other").mkdir(parents=True)
    home = ws.allocate_ports("probe", set(), ALL_FREE)
    (root / "other" / ".env.worktree").write_text(
        ws.render_env("other", home, GOOD_STACK_ID), encoding="utf-8"
    )
    taken = ws.taken_ports(root)
    assert taken == set(home.values())
    ports = ws.allocate_ports("probe", taken, ALL_FREE)
    assert ports["MM_POSTGRES_PORT"] == home["MM_POSTGRES_PORT"] + ws.BASE_STEP


def test_taken_ports_excludes_the_worktree_being_provisioned(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    mine = root / "mine"
    mine.mkdir(parents=True)
    (mine / ".env.worktree").write_text(
        ws.render_env("mine", ws.ports_for_base(20000), GOOD_STACK_ID), encoding="utf-8"
    )
    assert ws.taken_ports(root, exclude=mine) == set()
    assert ws.taken_ports(root) == set(range(20001, 20008))


def test_the_last_base_wraps_to_the_first() -> None:
    slug = _slug_with_base_index(ws.BASE_COUNT - 1)
    last_base = ws.BASE_MIN + (ws.BASE_COUNT - 1) * ws.BASE_STEP
    taken = set(ws.ports_for_base(last_base).values())
    assert ws.allocate_ports(slug, taken, ALL_FREE) == ws.ports_for_base(ws.BASE_MIN)


def test_exhaustion_is_a_named_error() -> None:
    with pytest.raises(ws.StackError, match="no free port base"):
        ws.allocate_ports("probe", set(), NONE_FREE)


# --- rendering and provisioning --------------------------------------------


def test_rendered_file_round_trips_through_dotenv_and_carries_stack_keys_only(tmp_path: Path) -> None:
    ports = ws.ports_for_base(20000)
    text = ws.render_env("11-2-probe", ports, GOOD_STACK_ID)
    env_file = tmp_path / ".env.worktree"
    env_file.write_text(text, encoding="utf-8")
    values = dotenv_values(env_file)
    assert values["MM_STACK_NAME"] == "meetingminer-11-2-probe"
    assert {name: int(values[name]) for name in ws.PORT_NAMES} == ports
    assert values["MM_STACK_ID"] == GOOD_STACK_ID
    assert values["MM_TEST_NEO4J_URI"] == "bolt://localhost:20006"
    assert values["MM_TEST_MEILI_URL"] == "http://localhost:20007"
    assert tuple(values) == ws.STACK_KEYS
    # The module's own parser agrees with dotenv on what it wrote.
    assert ws.parse_env_lines(text) == {k: v for k, v in values.items() if v is not None}


def test_provision_writes_once_and_keeps_a_complete_existing_file(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    worktree = root / "11-2-probe"
    worktree.mkdir(parents=True)
    env_file, written = ws.provision("11-2-probe", worktree, root, ALL_FREE)
    assert written and env_file == worktree / ".env.worktree"
    assert (root / ".provision.lock").exists()
    before = env_file.read_text(encoding="utf-8")
    # Every port now bound (the stack is up): re-provisioning keeps the file.
    env_file2, written2 = ws.provision("11-2-probe", worktree, root, NONE_FREE)
    assert (env_file2, written2) == (env_file, False)
    assert env_file.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    "text",
    [
        "",
        "MM_STACK_NAME=meetingminer-probe\n",
        "MM_POSTGRES_PORT=20001\nMM_NEO4J_HTTP_PORT=20002\n",
        "MM_STACK_NAME=\nMM_POSTGRES_PORT=20001\n",
    ],
)
def test_provision_refuses_an_incomplete_existing_file_by_name(tmp_path: Path, text: str) -> None:
    """A truncated or hand-edited file would put the worktree on the main stack."""
    worktree = tmp_path / "probe"
    worktree.mkdir()
    (worktree / ".env.worktree").write_text(text, encoding="utf-8")
    with pytest.raises(ws.StackError, match=r"\.env\.worktree: missing .*delete"):
        ws.provision("probe", worktree, tmp_path, ALL_FREE)
    assert (worktree / ".env.worktree").read_text(encoding="utf-8") == text


def test_provision_refuses_a_bad_slug_before_touching_the_tree(tmp_path: Path) -> None:
    with pytest.raises(ws.StackError, match="STORY must match"):
        ws.provision("Foo_Bar!", tmp_path / "x", tmp_path, ALL_FREE)
    assert not (tmp_path / "x").exists()


def test_provision_exhaustion_writes_nothing(tmp_path: Path) -> None:
    worktree = tmp_path / "probe"
    worktree.mkdir()
    with pytest.raises(ws.StackError, match="no free port base"):
        ws.provision("probe", worktree, tmp_path, NONE_FREE)
    assert not (worktree / ".env.worktree").exists()


def test_provision_names_a_write_failure(tmp_path: Path) -> None:
    worktree = tmp_path / "probe"
    (worktree / ".env.worktree").mkdir(parents=True)  # a directory where the file goes
    with pytest.raises(ws.StackError, match=r"cannot write .*\.env\.worktree"):
        ws.provision("probe", worktree, tmp_path, ALL_FREE)


# --- prune -----------------------------------------------------------------


class _FakeDocker:
    """Answers `docker ps` and `docker volume ls`, records everything else."""

    def __init__(self, ps: str, volumes: str, fail: bool = False, fail_down: set[str] | None = None) -> None:
        self.ps = ps
        self.volumes = volumes
        self.fail = fail
        self.fail_down = fail_down or set()
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(list(argv))
        if self.fail:
            raise ws.StackError("docker unavailable: simulated")
        if argv == ws.PS_ARGV:
            return self.ps
        if argv == ws.VOLUME_ARGV:
            return self.volumes
        if argv[:3] == ["docker", "compose", "-p"] and argv[3] in self.fail_down:
            raise ws.StackError(f"down failed for {argv[3]}: simulated")
        return ""


def _downs(fake: _FakeDocker) -> list[str]:
    return [call[3] for call in fake.calls if call[:3] == ["docker", "compose", "-p"]]


def _our_volumes(project: str, stack_id: str = "") -> str:
    return "\n".join(
        f"{project}_{name}\t{project}\t{stack_id}" for name in ws.VOLUME_NAMES
    )


def test_prune_classifies_owned_orphaned_foreign_and_main(tmp_path: Path) -> None:
    root = tmp_path / "meetingminer-wt"
    owned = root / "11-2"
    (owned / "infra").mkdir(parents=True)
    main_dir = tmp_path / "meetingminer"
    (main_dir / "infra").mkdir(parents=True)
    gone = root / "gone"  # deleted by hand while its stack ran
    ps = "\n".join(
        [
            f"meetingminer-11-2\t{owned / 'infra'}",
            f"meetingminer-11-2\t{owned / 'infra'}",
            f"meetingminer-gone\t{gone / 'infra'}",
            f"meetingminer\t{main_dir / 'infra'}",
            f"backend\t{tmp_path / 'elsewhere'}",
        ]
    )
    volumes = "\n".join(
        [
            "meetingminer-11-2_postgres-data\tmeetingminer-11-2",
            "meetingminer-gone_postgres-data\tmeetingminer-gone",
            "meetingminer_postgres-data\tmeetingminer",
            "backend_pgdata\tbackend",
        ]
    )
    fake = _FakeDocker(ps, volumes)
    lines: list[str] = []
    removed = ws.prune(root, run=fake, out=lines.append)
    assert removed == ["meetingminer-gone"]
    assert _downs(fake) == ["meetingminer-gone"]
    assert ["docker", "compose", "-p", "meetingminer-gone", "down", "-v", "--remove-orphans"] in fake.calls
    assert f"skipped owned meetingminer-11-2 ({owned})" in lines
    assert "removed stack meetingminer-gone" in lines
    assert not any("backend" in line or line.endswith(" meetingminer") for line in lines)


def test_prune_volumes_only_stack_with_our_volumes_is_placed_under_the_worktree_root(tmp_path: Path) -> None:
    root = tmp_path / "meetingminer-wt"
    (root / "kept").mkdir(parents=True)
    volumes = _our_volumes("meetingminer-kept") + "\n" + _our_volumes("meetingminer-x")
    fake = _FakeDocker("", volumes)
    lines: list[str] = []
    removed = ws.prune(root, run=fake, out=lines.append)
    assert removed == ["meetingminer-x"]
    assert _downs(fake) == ["meetingminer-x"]
    assert f"skipped owned meetingminer-kept ({root / 'kept'})" in lines


def test_prune_volumes_only_stack_with_a_foreign_volume_is_skipped_unknown(tmp_path: Path) -> None:
    """Only the compose file's seven volume names make a project ours."""
    root = tmp_path / "meetingminer-wt"
    root.mkdir()
    volumes = _our_volumes("meetingminer-x") + "\nmeetingminer-x_scratch\tmeetingminer-x"
    fake = _FakeDocker("", volumes)
    lines: list[str] = []
    assert ws.prune(root, run=fake, out=lines.append) == []
    assert _downs(fake) == []
    assert lines == ["skipped unknown meetingminer-x"]


def test_prune_without_an_existing_worktree_root_never_guesses_a_path(tmp_path: Path) -> None:
    fake = _FakeDocker("", _our_volumes("meetingminer-x"))
    lines: list[str] = []
    assert ws.prune(tmp_path / "absent-root", run=fake, out=lines.append) == []
    assert _downs(fake) == []
    assert lines == ["skipped unknown meetingminer-x"]


def test_prune_treats_a_project_declared_by_a_sibling_file_as_owned(tmp_path: Path) -> None:
    """`git worktree move` keeps `.env.worktree`; the name in it still owns the stack."""
    root = tmp_path / "meetingminer-wt"
    moved = root / "renamed-dir"
    moved.mkdir(parents=True)
    (moved / ".env.worktree").write_text(
        ws.render_env("orig", ws.ports_for_base(20000), GOOD_STACK_ID), encoding="utf-8"
    )
    ps = f"meetingminer-orig\t{tmp_path / 'old-place' / 'orig' / 'infra'}"  # gone
    fake = _FakeDocker(ps, "meetingminer-orig_postgres-data\tmeetingminer-orig")
    lines: list[str] = []
    assert ws.prune(root, run=fake, out=lines.append) == []
    assert _downs(fake) == []
    assert f"skipped owned meetingminer-orig ({moved})" in lines


def test_prune_never_touches_the_main_project_even_without_its_directory(tmp_path: Path) -> None:
    ps = f"meetingminer\t{tmp_path / 'nowhere' / 'infra'}"
    volumes = "meetingminer_postgres-data\tmeetingminer"
    fake = _FakeDocker(ps, volumes)
    lines: list[str] = []
    assert ws.prune(tmp_path, run=fake, out=lines.append) == []
    assert _downs(fake) == []
    assert lines == ["no worktree stacks found"]


def test_prune_continues_after_a_failed_down_and_fails_at_the_end(tmp_path: Path) -> None:
    root = tmp_path / "meetingminer-wt"
    root.mkdir()
    volumes = _our_volumes("meetingminer-a") + "\n" + _our_volumes("meetingminer-b")
    fake = _FakeDocker("", volumes, fail_down={"meetingminer-a"})
    lines: list[str] = []
    with pytest.raises(ws.StackError, match="1 stack\\(s\\) could not be removed: meetingminer-a"):
        ws.prune(root, run=fake, out=lines.append)
    assert _downs(fake) == ["meetingminer-a", "meetingminer-b"]
    assert any(line.startswith("failed meetingminer-a: ") for line in lines)
    assert "removed stack meetingminer-b" in lines


def test_prune_project_filter_removes_only_that_stale_project(tmp_path: Path) -> None:
    root = tmp_path / "meetingminer-wt"
    root.mkdir()
    volumes = _our_volumes("meetingminer-a") + "\n" + _our_volumes("meetingminer-b")
    fake = _FakeDocker("", volumes)
    lines: list[str] = []
    assert ws.prune(root, run=fake, out=lines.append, project="meetingminer-b") == ["meetingminer-b"]
    assert _downs(fake) == ["meetingminer-b"]
    assert lines == ["removed stack meetingminer-b"]


def test_prune_project_filter_errors_when_the_owner_exists(tmp_path: Path) -> None:
    root = tmp_path / "meetingminer-wt"
    (root / "b").mkdir(parents=True)
    fake = _FakeDocker("", _our_volumes("meetingminer-b"))
    with pytest.raises(ws.StackError, match=f"belongs to the existing checkout {root / 'b'}"):
        ws.prune(root, run=fake, out=lambda _l: None, project="meetingminer-b")
    assert _downs(fake) == []


def test_prune_project_filter_errors_on_an_unknown_layout(tmp_path: Path) -> None:
    root = tmp_path / "meetingminer-wt"
    root.mkdir()
    fake = _FakeDocker("", "meetingminer-b_scratch\tmeetingminer-b")
    with pytest.raises(ws.StackError, match="does not recognise"):
        ws.prune(root, run=fake, out=lambda _l: None, project="meetingminer-b")
    assert _downs(fake) == []


def test_prune_project_filter_is_a_no_op_for_an_absent_project(tmp_path: Path) -> None:
    fake = _FakeDocker("", _our_volumes("meetingminer-a"))
    lines: list[str] = []
    assert ws.prune(tmp_path, run=fake, out=lines.append, project="meetingminer-zzz") == []
    assert _downs(fake) == []
    assert lines == ["no stale stack meetingminer-zzz"]


def test_prune_reports_docker_unavailable_by_name(tmp_path: Path) -> None:
    with pytest.raises(ws.StackError, match="docker unavailable"):
        ws.prune(tmp_path, run=_FakeDocker("", "", fail=True), out=lambda _line: None)


def test_run_docker_names_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(argv, **_kwargs):
        raise subprocess.TimeoutExpired(argv, ws.DOCKER_TIMEOUT_SECONDS)

    monkeypatch.setattr(ws.subprocess, "run", hang)
    with pytest.raises(ws.StackError, match=f"did not finish within {ws.DOCKER_TIMEOUT_SECONDS}s"):
        ws.run_docker(["docker", "ps"])


def test_cli_prune_exit_code_names_the_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(ws, "run_docker", _FakeDocker("", "", fail=True))
    assert ws.main(["prune", "--worktree-root", str(tmp_path)]) == 1
    assert "error: docker unavailable" in capsys.readouterr().err


def test_cli_prune_passes_the_project_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    tmp_path.joinpath("wt").mkdir()
    fake = _FakeDocker("", _our_volumes("meetingminer-a") + "\n" + _our_volumes("meetingminer-b"))
    monkeypatch.setattr(ws, "run_docker", fake)
    assert ws.main(["prune", "--worktree-root", str(tmp_path / "wt"), "--project", "meetingminer-a"]) == 0
    assert _downs(fake) == ["meetingminer-a"]
    assert "removed stack meetingminer-a" in capsys.readouterr().out


def test_cli_provision_prints_the_stack_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(ws, "port_is_free", ALL_FREE)
    worktree = tmp_path / "11-2-probe"
    worktree.mkdir()
    rc = ws.main(
        ["provision", "--slug", "11-2-probe", "--worktree", str(worktree), "--worktree-root", str(tmp_path)]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert ".env.worktree written:" in out
    assert "MM_STACK_NAME=meetingminer-11-2-probe" in out
    assert "MM_TEST_MEILI_URL=http://localhost:" in out


# --- the conftest side: reading the file, refusing a worktree without one --


def test_twin_endpoints_defaults_and_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MM_TEST_NEO4J_URI", raising=False)
    monkeypatch.delenv("MM_TEST_MEILI_URL", raising=False)
    assert twin_endpoints({}) == ("bolt://localhost:7688", "http://localhost:7701")
    assert twin_endpoints({"MM_TEST_NEO4J_URI": "", "MM_TEST_MEILI_URL": ""}) == (
        "bolt://localhost:7688",
        "http://localhost:7701",
    )
    envfile = tmp_path / ".env"
    envfile.write_text("POSTGRES_PASSWORD=x\n", encoding="utf-8")
    (tmp_path / ".env.worktree").write_text(
        ws.render_env("probe", ws.ports_for_base(20000), GOOD_STACK_ID), encoding="utf-8"
    )
    assert twin_endpoints(merged_env(envfile)) == ("bolt://localhost:20006", "http://localhost:20007")
    monkeypatch.setenv("MM_TEST_MEILI_URL", "http://localhost:30007")
    assert twin_endpoints(merged_env(envfile)) == ("bolt://localhost:20006", "http://localhost:30007")



# --- remediation 2026-08-30: .env.worktree is one validated ownership record

GOOD_STACK_ID = "0123456789ab"


def good_stack_lines(slug: str = "probe", base: int = 20000) -> list[str]:
    """The exact KEY=value lines a rendered file carries, in STACK_KEYS order."""
    ports = ws.ports_for_base(base)
    return [
        f"MM_STACK_NAME=meetingminer-{slug}",
        *(f"{name}={ports[name]}" for name in ws.PORT_NAMES),
        f"MM_STACK_ID={GOOD_STACK_ID}",
        f"MM_TEST_NEO4J_URI=bolt://localhost:{ports['MM_NEO4J_TEST_BOLT_PORT']}",
        f"MM_TEST_MEILI_URL=http://localhost:{ports['MM_MEILI_TEST_PORT']}",
    ]


def good_stack_text(slug: str = "probe", base: int = 20000) -> str:
    return "\n".join(good_stack_lines(slug, base)) + "\n"


def _truncated(lines: list[str], key: str) -> list[str]:
    index = next(n for n, line in enumerate(lines) if line.startswith(f"{key}="))
    return lines[:index]


def _replaced(lines: list[str], key: str, value: str) -> list[str]:
    return [f"{key}={value}" if line.startswith(f"{key}=") else line for line in lines]


_GOOD = good_stack_lines()

#: (case id, file lines for slug `probe`, the key every refusal must name,
#: whether the loader — which does not know the checkout directory — also
#: rejects it; a file naming another slug is caught by the directory-keyed
#: validators only).
BAD_STACK_FILES: list[tuple[str, list[str], str, bool]] = [
    ("truncated-before-id", _truncated(_GOOD, "MM_STACK_ID"), "MM_STACK_ID", True),
    ("truncated-before-neo4j-twin", _truncated(_GOOD, "MM_TEST_NEO4J_URI"), "MM_TEST_NEO4J_URI", True),
    ("truncated-before-meili-twin", _truncated(_GOOD, "MM_TEST_MEILI_URL"), "MM_TEST_MEILI_URL", True),
    ("name-only", [_GOOD[0]], "MM_POSTGRES_PORT", True),
    ("another-slugs-name", _replaced(_GOOD, "MM_STACK_NAME", "meetingminer-other"), "MM_STACK_NAME", False),
    ("the-main-project-as-name", _replaced(_GOOD, "MM_STACK_NAME", "meetingminer"), "MM_STACK_NAME", True),
    ("port-not-a-number", _replaced(_GOOD, "MM_POSTGRES_PORT", "abc"), "MM_POSTGRES_PORT", True),
    ("port-zero", _replaced(_GOOD, "MM_POSTGRES_PORT", "0"), "MM_POSTGRES_PORT", True),
    ("port-out-of-range", _replaced(_GOOD, "MM_POSTGRES_PORT", "70000"), "MM_POSTGRES_PORT", True),
    ("port-with-sign", _replaced(_GOOD, "MM_POSTGRES_PORT", "+5"), "MM_POSTGRES_PORT", True),
    ("port-with-underscore", _replaced(_GOOD, "MM_POSTGRES_PORT", "1_000"), "MM_POSTGRES_PORT", True),
    ("two-equal-ports", _replaced(_GOOD, "MM_MEILI_PORT", "20001"), "MM_MEILI_PORT", True),
    ("a-main-default-port", _replaced(_GOOD, "MM_NEO4J_TEST_BOLT_PORT", "7688"), "MM_NEO4J_TEST_BOLT_PORT", True),
    ("bad-stack-id", _replaced(_GOOD, "MM_STACK_ID", "XYZ"), "MM_STACK_ID", True),
    ("incoherent-neo4j-twin", _replaced(_GOOD, "MM_TEST_NEO4J_URI", "bolt://localhost:9999"), "MM_TEST_NEO4J_URI", True),
    ("incoherent-meili-twin", _replaced(_GOOD, "MM_TEST_MEILI_URL", "http://localhost:9999"), "MM_TEST_MEILI_URL", True),
    ("foreign-key", [*_GOOD, "POSTGRES_PASSWORD=x"], "POSTGRES_PASSWORD", True),
    ("blank-value", _replaced(_GOOD, "MM_MEILI_PORT", ""), "MM_MEILI_PORT", True),
]
BAD_STACK_IDS = [case for case, _lines, _key, _loader in BAD_STACK_FILES]


def _linked(tmp_path: Path, slug: str, text: str | None) -> Path:
    """A directory that looks like a linked git worktree, optionally with a
    stack file."""
    linked = tmp_path / slug
    linked.mkdir(parents=True, exist_ok=True)
    (linked / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n", encoding="utf-8")
    if text is not None:
        (linked / ".env.worktree").write_text(text, encoding="utf-8")
    return linked


def test_stack_keys_carry_the_stack_id_in_order() -> None:
    """The incarnation identity (MM_STACK_ID) is the tenth stack key."""
    assert ws.STACK_KEYS == (
        "MM_STACK_NAME",
        *ws.PORT_NAMES,
        "MM_STACK_ID",
        "MM_TEST_NEO4J_URI",
        "MM_TEST_MEILI_URL",
    )


def test_validate_env_file_accepts_a_rendered_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.worktree"
    env_file.write_text(good_stack_text(), encoding="utf-8")
    values = ws.validate_env_file(env_file, "probe")
    assert values["MM_STACK_NAME"] == "meetingminer-probe"
    assert values["MM_STACK_ID"] == GOOD_STACK_ID


@pytest.mark.parametrize(
    ("case", "lines", "key", "loader_rejects"), BAD_STACK_FILES, ids=BAD_STACK_IDS
)
def test_bad_stack_file_is_refused_by_validate_and_provision(
    tmp_path: Path, case: str, lines: list[str], key: str, loader_rejects: bool
) -> None:
    """One schema: every reader refuses the same file naming the same key,
    and provision never rewrites a bad file."""
    text = "\n".join(lines) + "\n"
    worktree = tmp_path / "probe"
    worktree.mkdir()
    env_file = worktree / ".env.worktree"
    env_file.write_text(text, encoding="utf-8")
    with pytest.raises(ws.StackError) as validate_error:
        ws.validate_env_file(env_file, "probe")
    assert key in str(validate_error.value)
    assert "delete" in str(validate_error.value)  # the remedy is executable
    with pytest.raises(ws.StackError) as provision_error:
        ws.provision("probe", worktree, tmp_path, ALL_FREE)
    assert key in str(provision_error.value)
    assert env_file.read_text(encoding="utf-8") == text  # kept byte-identical


@pytest.mark.parametrize(
    ("case", "lines", "key", "loader_rejects"), BAD_STACK_FILES, ids=BAD_STACK_IDS
)
def test_bad_stack_file_is_refused_by_the_test_session_guard(
    tmp_path: Path, case: str, lines: list[str], key: str, loader_rejects: bool
) -> None:
    from conftest import linked_worktree_refusal

    linked = _linked(tmp_path, "probe", "\n".join(lines) + "\n")
    message = linked_worktree_refusal(linked)
    assert message is not None
    assert key in message


def test_linked_worktree_refusal_semantics(tmp_path: Path) -> None:
    """No file: refused naming worktree-provision. A rendered file for this
    directory: fine. A rendered file for another slug: refused. A main
    checkout carrying the file: refused."""
    from conftest import linked_worktree_refusal

    bare = _linked(tmp_path, "linked", None)
    message = linked_worktree_refusal(bare)
    assert message is not None and "make worktree-provision" in message

    good = _linked(tmp_path / "good-root", "linked", good_stack_text("linked"))
    assert linked_worktree_refusal(good) is None

    wrong = _linked(tmp_path / "wrong-root", "linked", good_stack_text("other"))
    message = linked_worktree_refusal(wrong)
    assert message is not None and "MM_STACK_NAME" in message

    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)
    assert linked_worktree_refusal(main) is None
    (main / ".env.worktree").write_text(good_stack_text("main"), encoding="utf-8")
    message = linked_worktree_refusal(main)
    assert message is not None and "main checkout" in message


def test_provision_publication_is_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupted publication must never leave an accepted (or partial)
    .env.worktree behind — not even a temp file."""
    worktree = tmp_path / "probe"
    worktree.mkdir()

    def boom(_src: object, _dst: object) -> None:
        raise OSError("simulated publication failure")

    monkeypatch.setattr(ws.os, "replace", boom)
    with pytest.raises(ws.StackError, match="cannot write"):
        ws.provision("probe", worktree, tmp_path, ALL_FREE)
    assert list(worktree.iterdir()) == []


def test_provision_refuses_a_file_naming_another_slug(tmp_path: Path) -> None:
    """A copied file must never be kept for a different worktree."""
    worktree = tmp_path / "probe"
    worktree.mkdir()
    text = good_stack_text("other")
    (worktree / ".env.worktree").write_text(text, encoding="utf-8")
    with pytest.raises(ws.StackError, match="MM_STACK_NAME"):
        ws.provision("probe", worktree, tmp_path, ALL_FREE)
    assert (worktree / ".env.worktree").read_text(encoding="utf-8") == text


def test_check_subcommand_validates_the_directorys_own_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`check --worktree <dir>`: the slug is the directory name, so a renamed
    or moved worktree is refused by name."""
    worktree = tmp_path / "probe"
    worktree.mkdir()
    (worktree / ".env.worktree").write_text(good_stack_text("probe"), encoding="utf-8")
    assert ws.main(["check", "--worktree", str(worktree)]) == 0
    assert capsys.readouterr().out == ""

    renamed = tmp_path / "renamed"
    worktree.rename(renamed)
    assert ws.main(["check", "--worktree", str(renamed)]) == 1
    assert "MM_STACK_NAME" in capsys.readouterr().err


def test_declared_owners_counts_only_valid_worktree_stack_names(tmp_path: Path) -> None:
    """A sibling file whose MM_STACK_NAME is not meetingminer-<slug> must not
    grant ownership of anything."""
    root = tmp_path / "wt"
    good = root / "good"
    good.mkdir(parents=True)
    (good / ".env.worktree").write_text(good_stack_text("good"), encoding="utf-8")
    bad = root / "bad"
    bad.mkdir()
    (bad / ".env.worktree").write_text(
        "MM_STACK_NAME=meetingminer-Foo\n", encoding="utf-8"
    )
    main_name = root / "mainish"
    main_name.mkdir()
    (main_name / ".env.worktree").write_text("MM_STACK_NAME=meetingminer\n", encoding="utf-8")
    owners = ws.declared_owners(root)
    assert owners == {"meetingminer-good": good}


# --- remediation 2026-08-30: the pruner proves ownership (findings 2, 3) ----


@pytest.mark.parametrize(
    "project",
    ["meetingminer-Foo", "meetingminer-", "meetingminer-.backup", "meetingminer-UPPER"],
)
def test_a_prefix_with_an_invalid_slug_is_not_a_worktree_project(project: str) -> None:
    """Only meetingminer-<valid slug> can be a stack this tool provisioned."""
    assert not ws._is_worktree_project(project)


def test_prune_reports_a_malformed_prefix_project_as_foreign_and_never_removes_it(
    tmp_path: Path,
) -> None:
    """`meetingminer-Foo` with a missing working-dir owner cannot be ours —
    it must be reported and skipped, never torn down."""
    root = tmp_path / "wt"
    root.mkdir()
    gone = tmp_path / "nowhere" / "Foo" / "infra"
    ps = f"meetingminer-Foo\t{gone}\t"
    volumes = "meetingminer-Foo_postgres-data\tmeetingminer-Foo\t"
    fake = _FakeDocker(ps, volumes)
    lines: list[str] = []
    assert ws.prune(root, run=fake, out=lines.append) == []
    assert _downs(fake) == []
    assert any(line.startswith("skipped foreign meetingminer-Foo") for line in lines)


def test_prune_container_backed_project_with_a_foreign_volume_is_unknown(
    tmp_path: Path,
) -> None:
    """A container label must not bypass volume recognition: a valid-prefix
    project with a missing owner and a foreign volume is unknown, in the
    general sweep and in --project mode."""
    root = tmp_path / "wt"
    root.mkdir()
    gone = root / "probe" / "infra"  # missing
    ps = f"meetingminer-probe\t{gone}\t"
    volumes = (
        _our_volumes("meetingminer-probe")
        + "\nmeetingminer-probe_foreign-data\tmeetingminer-probe\t"
    )
    fake = _FakeDocker(ps, volumes)
    lines: list[str] = []
    assert ws.prune(root, run=fake, out=lines.append) == []
    assert _downs(fake) == []
    assert "skipped unknown meetingminer-probe" in lines

    fake2 = _FakeDocker(ps, volumes)
    with pytest.raises(ws.StackError, match="does not recognise"):
        ws.prune(root, run=fake2, out=lambda _l: None, project="meetingminer-probe")
    assert _downs(fake2) == []


def test_worktree_stacks_carries_container_and_volume_ids(tmp_path: Path) -> None:
    """The third label column: container ids and volume ids are collected
    separately, an unlabeled volume as the empty string."""
    root = tmp_path / "wt"
    root.mkdir()
    ps = f"meetingminer-probe\t{root / 'probe' / 'infra'}\tdeadbeef0001"
    volumes = _our_volumes("meetingminer-probe", "deadbeef0001") + (
        "\nmeetingminer-probe_postgres-data\tmeetingminer-probe\t"
    )
    stacks, foreign = ws.worktree_stacks(ps, volumes, root)
    assert foreign == []
    stack = stacks["meetingminer-probe"]
    assert stack.ids == {"deadbeef0001"}
    assert stack.volume_ids == {"deadbeef0001", ""}


# --- remediation 2026-08-30: claim — one safe start path (findings 4, 5) ----


def _claim_worktree(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "wt"
    worktree = root / "probe"
    worktree.mkdir(parents=True)
    env_file = worktree / ".env.worktree"
    env_file.write_text(good_stack_text("probe"), encoding="utf-8")
    return root, worktree, env_file


def test_claim_notes_an_absent_project(tmp_path: Path) -> None:
    root, worktree, _env = _claim_worktree(tmp_path)
    fake = _FakeDocker("", "")
    lines: list[str] = []
    ws.claim(worktree, root, run=fake, out=lines.append)
    assert _downs(fake) == []
    assert lines == ["no stale stack meetingminer-probe"]


def test_claim_keeps_a_stack_carrying_this_files_id(tmp_path: Path) -> None:
    root, worktree, _env = _claim_worktree(tmp_path)
    ps = f"meetingminer-probe\t{worktree / 'infra'}\t{GOOD_STACK_ID}"
    fake = _FakeDocker(ps, _our_volumes("meetingminer-probe", GOOD_STACK_ID))
    lines: list[str] = []
    ws.claim(worktree, root, run=fake, out=lines.append)
    assert _downs(fake) == []
    assert lines == ["kept stack meetingminer-probe (this worktree's)"]


@pytest.mark.parametrize(
    ("container_id", "volume_id"),
    [
        ("", ""),  # a pre-remediation, id-less incarnation
        ("aaaaaaaaaaaa", "aaaaaaaaaaaa"),  # another incarnation's id
        (GOOD_STACK_ID, ""),  # a mix: our containers over stale volumes
    ],
    ids=["id-less", "other-id", "mixed"],
)
def test_claim_tears_down_a_stale_incarnation(
    tmp_path: Path, container_id: str, volume_id: str
) -> None:
    """Anything under this name that does not carry the file's MM_STACK_ID on
    every container and volume is stale: torn down, never attached to."""
    root, worktree, env_file = _claim_worktree(tmp_path)
    ps = f"meetingminer-probe\t{worktree / 'infra'}\t{container_id}"
    fake = _FakeDocker(ps, _our_volumes("meetingminer-probe", volume_id))
    lines: list[str] = []
    ws.claim(worktree, root, run=fake, out=lines.append)
    assert _downs(fake) == ["meetingminer-probe"]
    assert lines == [
        f"removed stale stack meetingminer-probe (not started from {env_file})"
    ]


def test_claim_errors_when_another_existing_checkout_owns_the_name(tmp_path: Path) -> None:
    root, worktree, _env = _claim_worktree(tmp_path)
    other = root / "other"
    (other / "infra").mkdir(parents=True)
    ps = f"meetingminer-probe\t{other / 'infra'}\t{GOOD_STACK_ID}"
    fake = _FakeDocker(ps, "")
    with pytest.raises(ws.StackError, match=f"belongs to the existing checkout {other}"):
        ws.claim(worktree, root, run=fake, out=lambda _l: None)
    assert _downs(fake) == []


def test_claim_errors_on_an_unknown_layout(tmp_path: Path) -> None:
    root, worktree, _env = _claim_worktree(tmp_path)
    volumes = (
        _our_volumes("meetingminer-probe", GOOD_STACK_ID)
        + f"\nmeetingminer-probe_foreign-data\tmeetingminer-probe\t{GOOD_STACK_ID}"
    )
    fake = _FakeDocker("", volumes)
    with pytest.raises(ws.StackError, match="does not recognise"):
        ws.claim(worktree, root, run=fake, out=lambda _l: None)
    assert _downs(fake) == []


def test_claim_validates_the_file_before_touching_docker(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    worktree = root / "probe"
    worktree.mkdir(parents=True)
    (worktree / ".env.worktree").write_text(good_stack_text("other"), encoding="utf-8")
    fake = _FakeDocker("", "")
    with pytest.raises(ws.StackError, match="MM_STACK_NAME"):
        ws.claim(worktree, root, run=fake, out=lambda _l: None)
    assert fake.calls == []


def test_cli_claim_reports_the_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    root, worktree, _env = _claim_worktree(tmp_path)
    monkeypatch.setattr(ws, "run_docker", _FakeDocker("", ""))
    rc = ws.main(
        ["claim", "--worktree", str(worktree), "--worktree-root", str(root)]
    )
    assert rc == 0
    assert "no stale stack meetingminer-probe" in capsys.readouterr().out
