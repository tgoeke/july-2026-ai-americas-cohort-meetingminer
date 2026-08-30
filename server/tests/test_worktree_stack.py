"""infra/worktree_stack.py (story 11.2): the per-worktree stack allocator,
the `.env.worktree` renderer and the orphan-stack pruner.

Pure-function coverage with a fake bind probe and a recording fake `docker`
runner -- no Docker, no store, no network. The module is stdlib-only and
lives under infra/ (the Makefile runs it with the system python3), so it is
loaded here by path rather than imported as a package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from dotenv import dotenv_values

from repo_paths import REPO_ROOT


def _load_module() -> ModuleType:
    path = REPO_ROOT / "infra" / "worktree_stack.py"
    spec = importlib.util.spec_from_file_location("worktree_stack", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ws = _load_module()

ALL_FREE = lambda port: True  # noqa: E731 - a probe that finds every port free
NONE_FREE = lambda port: False  # noqa: E731


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


@pytest.mark.parametrize("slug", ["Foo_Bar!", "-lead", "UPPER", "a b", "", "x/y"])
def test_bad_slug_is_refused_by_name(slug: str) -> None:
    with pytest.raises(ws.StackError, match=r"\[a-z0-9\]\[a-z0-9\._-\]\*"):
        ws.validate_slug(slug)


@pytest.mark.parametrize("slug", ["11-2", "1-7-remediation", "a.b_c", "0"])
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


def test_different_slugs_usually_differ() -> None:
    assert ws.allocate_ports("11-2", set(), ALL_FREE) != ws.allocate_ports(
        "11-3", set(), ALL_FREE
    )


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
        ws.render_env("other", home), encoding="utf-8"
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
        ws.render_env("mine", ws.ports_for_base(20000)), encoding="utf-8"
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


def test_rendered_file_round_trips_through_dotenv(tmp_path: Path) -> None:
    ports = ws.ports_for_base(20000)
    text = ws.render_env("11-2-probe", ports)
    env_file = tmp_path / ".env.worktree"
    env_file.write_text(text, encoding="utf-8")
    values = dotenv_values(env_file)
    assert values["MM_STACK_NAME"] == "meetingminer-11-2-probe"
    assert {name: int(values[name]) for name in ws.PORT_NAMES} == ports
    assert values["MM_TEST_NEO4J_URI"] == "bolt://localhost:20006"
    assert values["MM_TEST_MEILI_URL"] == "http://localhost:20007"
    # The module's own parser agrees with dotenv on what it wrote.
    assert ws.parse_env_lines(text) == {k: v for k, v in values.items() if v is not None}


def test_provision_writes_once_and_keeps_an_existing_file(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    worktree = root / "11-2-probe"
    worktree.mkdir(parents=True)
    env_file, written = ws.provision("11-2-probe", worktree, root, ALL_FREE)
    assert written and env_file == worktree / ".env.worktree"
    before = env_file.read_text(encoding="utf-8")
    # Every port now bound (the stack is up): re-provisioning keeps the file.
    env_file2, written2 = ws.provision("11-2-probe", worktree, root, NONE_FREE)
    assert (env_file2, written2) == (env_file, False)
    assert env_file.read_text(encoding="utf-8") == before


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


# --- prune -----------------------------------------------------------------


class _FakeDocker:
    """Answers `docker ps` and `docker volume ls`, records everything else."""

    def __init__(self, ps: str, volumes: str, fail: bool = False) -> None:
        self.ps = ps
        self.volumes = volumes
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(list(argv))
        if self.fail:
            raise ws.StackError("docker unavailable: simulated")
        if argv == ws.PS_ARGV:
            return self.ps
        if argv == ws.VOLUME_ARGV:
            return self.volumes
        return ""


def _downs(fake: _FakeDocker) -> list[str]:
    return [call[3] for call in fake.calls if call[:3] == ["docker", "compose", "-p"]]


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


def test_prune_volumes_only_stack_is_placed_under_the_worktree_root(tmp_path: Path) -> None:
    root = tmp_path / "meetingminer-wt"
    (root / "kept").mkdir(parents=True)
    volumes = "\n".join(
        [
            "meetingminer-kept_neo4j-data\tmeetingminer-kept",
            "meetingminer-x_neo4j-data\tmeetingminer-x",
            "meetingminer-x_postgres-data\tmeetingminer-x",
        ]
    )
    fake = _FakeDocker("", volumes)
    lines: list[str] = []
    removed = ws.prune(root, run=fake, out=lines.append)
    assert removed == ["meetingminer-x"]
    assert _downs(fake) == ["meetingminer-x"]
    assert f"skipped owned meetingminer-kept ({root / 'kept'})" in lines


def test_prune_never_touches_the_main_project_even_without_its_directory(tmp_path: Path) -> None:
    ps = f"meetingminer\t{tmp_path / 'nowhere' / 'infra'}"
    volumes = "meetingminer_postgres-data\tmeetingminer"
    fake = _FakeDocker(ps, volumes)
    lines: list[str] = []
    assert ws.prune(tmp_path, run=fake, out=lines.append) == []
    assert _downs(fake) == []
    assert lines == ["no worktree stacks found"]


def test_prune_reports_docker_unavailable_by_name(tmp_path: Path) -> None:
    with pytest.raises(ws.StackError, match="docker unavailable"):
        ws.prune(tmp_path, run=_FakeDocker("", "", fail=True), out=lambda _line: None)


def test_cli_prune_exit_code_names_the_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(ws, "run_docker", _FakeDocker("", "", fail=True))
    assert ws.main(["prune", "--worktree-root", str(tmp_path)]) == 1
    assert "error: docker unavailable" in capsys.readouterr().err


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
