"""AD-16 made falsifiable: the harness is a client, never a housemate.

The eval harness may mutate the running system only through the public API,
and may assert only through API reads and read-only store access. As prose
that is unenforceable — one `from meetingminer.projections import ...` in a
check would let the harness write the very store it is supposed to be
auditing, and the publish-gate check (5.3) would then be asserting against
state it produced itself.

This file is the mechanism that complains. It is deliberately import
inspection rather than convention: it costs nothing, needs no store and no
api, and it survives somebody who never read AD-16.

Modelled on server/tests/test_projections_single_writer.py, including the
guard on the guard — an empty walk would make the assertion vacuous.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

EVALS_ROOT = Path(__file__).resolve().parents[1]
HARNESS_ROOT = EVALS_ROOT / "harness"

# The server package root, and the four subpackages whose import would make the
# harness a housemate: the pipeline and worker run the work under test, the
# projections module is the single writer to both retrieval stores, and `db`
# opens a connection pool with write access. The bare root is listed too: it is
# how the four would be reached by attribute access without naming them.
FORBIDDEN = (
    "meetingminer",
    "meetingminer.pipeline",
    "meetingminer.projections",
    "meetingminer.worker",
    "meetingminer.db",
)

# The named allowances. AD-16 bans imports that let the harness *change*
# state; neither module here does.
#
# `meetingminer.config` (story 5.2): it parses `config.yaml` and `.env` and
# mutates nothing, and a run's configuration snapshot has to be the resolved
# configuration rather than the harness's own re-parse of the same two files.
# Re-implementing that parse here would duplicate the whole `.env` resolution
# contract (`MM_ENV_PATH`, expansion, the config-anchored search), which is
# more surface to drift than the import is coupling.
#
# `meetingminer.adapters.llm` (story 5.4): rubric-2.7 scoring and the bake-off
# are built on the `Llm` port precisely because AD-8 makes that port the one
# place model interaction is expressed — reimplementing `build_llm`,
# `FallbackLlm`, and the LiteLLM completer here would be a second, drifting
# copy of exactly the code path `pipeline/stages/extract.py` already calls.
# The port answers completions; it does not read or write any evidence store,
# so importing it does not make the harness a housemate the way
# `.pipeline`/`.projections`/`.worker`/`.db` would.
#
# `meetingminer.db` stays forbidden even though `corpus.py`'s conninfo shape
# mirrors it, because that module's job is opening write pools.
ALLOWED = ("meetingminer.config", "meetingminer.adapters.llm")


def is_forbidden(module: str) -> bool:
    """Whether importing ``module`` would make the harness a housemate."""
    if module in ALLOWED or any(module.startswith(f"{name}.") for name in ALLOWED):
        return False
    return module in FORBIDDEN or any(
        module.startswith(f"{root}.") for root in FORBIDDEN
    )


def python_files(root: Path = EVALS_ROOT) -> list[Path]:
    return sorted(root.rglob("*.py"))


def imported_modules(path: Path) -> set[str]:
    """Every module this file imports, however the import is spelled.

    Covers ``import x.y``, ``from x.y import z`` (recording both ``x.y`` and
    ``x.y.z``, so ``from meetingminer import db`` is caught), and aliases. A
    relative import has no module root to leak through, so it is ignored.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_the_walk_actually_reaches_the_harness() -> None:
    """A guard on the guard: no files walked would pass for the wrong reason."""
    walked = {path.relative_to(EVALS_ROOT).as_posix() for path in python_files()}
    for expected in (
        "conftest.py",
        "checks/gate_probe.py",
        "checks/test_capture_checks.py",
        "checks/test_publish_gate.py",
        "checks/test_retrieval_checks.py",
        "harness/bakeoff.py",
        "harness/checks.py",
        "harness/corpus.py",
        "harness/groundtruth.py",
        "harness/judge.py",
        "harness/retrieval.py",
        "harness/run.py",
        "harness/stores.py",
        "harness/subjects.py",
        "tests/test_harness_boundary.py",
    ):
        assert expected in walked, f"the import walk never reached {expected}"


@pytest.mark.parametrize(
    "path", python_files(), ids=lambda p: p.relative_to(EVALS_ROOT).as_posix()
)
def test_no_eval_module_imports_the_server_package(path: Path) -> None:
    offenders = sorted(
        module for module in imported_modules(path) if is_forbidden(module)
    )
    assert not offenders, (
        f"{path.relative_to(EVALS_ROOT)} imports {offenders} — AD-16: the eval"
        " harness reads the corpus through the public API and imports no server"
        f" module except {', '.join(ALLOWED)}"
    )


@pytest.mark.parametrize(
    "module",
    [
        "meetingminer",
        "meetingminer.db",
        "meetingminer.pipeline",
        "meetingminer.projections",
        "meetingminer.worker",
        "meetingminer.api.meetings",
        # The `meetingminer.adapters.llm` allowance is scoped to that one
        # package, not to `.adapters` as a whole: a sibling adapter (OCR,
        # embedding) has no business in a harness that scores rubric-2.7 text.
        "meetingminer.adapters",
        "meetingminer.adapters.ocr",
        "meetingminer.adapters.embed",
    ],
)
def test_the_allowance_did_not_open_the_package(module: str) -> None:
    """Widening the guard for `config`/`adapters.llm` must not have widened it
    for anything else.

    `meetingminer.db` is the pointed case: its `conninfo` helper is exactly the
    shape `harness/corpus.py` mirrors, and it stays refused because that
    module's job is opening write pools.
    """
    assert is_forbidden(module)


@pytest.mark.parametrize(
    "module",
    [
        "meetingminer.config",
        "meetingminer.config.load_config",
        "meetingminer.config.LlmRoleBinding",
        "meetingminer.adapters.llm",
        "meetingminer.adapters.llm.build_llm",
        "meetingminer.adapters.llm.LlmError",
        "meetingminer.adapters.llm.LlmUnavailableError",
        "meetingminer.adapters.llm.port",
    ],
)
def test_the_allowance_is_exactly_the_config_and_llm_modules(module: str) -> None:
    assert not is_forbidden(module)


def test_nothing_in_the_harness_imports_the_server_beyond_the_allowance() -> None:
    """The allowance is a door, not a doorway: two modules, three importers.

    A guard that merely permitted the two allowances would let a later story
    import them in five more places and then reach for a sibling. This pins
    the *production* set of server imports — `conftest.py` plus `harness/` —
    to the exact modules and symbols the run's configuration snapshot, the
    rubric-2.7 scorer, and the bake-off need.

    Deliberately not every file under `evals/`: `tests/test_judge_scoring.py`
    and `tests/test_bakeoff.py` legitimately import `LlmError`/
    `LlmUnavailableError` to raise them from a fake `Llm`, the same reason
    `checks/test_capture_checks.py` imports `psycopg` directly for its
    write-probe test rather than reaching for a harness helper that does not
    exist. `test_no_eval_module_imports_the_server_package` above still runs
    over every file and still refuses `.pipeline`/`.projections`/`.worker`/
    `.db` everywhere, test files included — only the two allowances are wider
    than "harness plus conftest".
    """
    scope = [EVALS_ROOT / "conftest.py", *python_files(HARNESS_ROOT)]
    reached: dict[str, set[str]] = {}
    for path in scope:
        server = {
            module
            for module in imported_modules(path)
            if module == "meetingminer" or module.startswith("meetingminer.")
        }
        if server:
            reached[path.relative_to(EVALS_ROOT).as_posix()] = server
    assert reached == {
        "conftest.py": {"meetingminer.config", "meetingminer.config.load_config"},
        "harness/judge.py": {
            "meetingminer.adapters.llm",
            "meetingminer.adapters.llm.LlmError",
            "meetingminer.adapters.llm.build_llm",
            "meetingminer.config",
            "meetingminer.config.load_config",
        },
        "harness/bakeoff.py": {
            "meetingminer.config",
            "meetingminer.config.LlmRoleBinding",
            "meetingminer.config.load_config",
            "meetingminer.adapters.llm",
            "meetingminer.adapters.llm.LlmError",
            "meetingminer.adapters.llm.build_llm",
        },
    }


def test_the_only_network_call_lives_in_one_harness_module() -> None:
    """`httpx` is reachable from exactly three modules of the harness package.

    Loading, validation and selection stay pure so the suite runs with no api
    up; concentrating the api calls in named modules keeps that property
    checkable rather than hoped for. `judge.py` joins `subjects.py` here in
    story 5.4: `POST /chat` is the only way it can read a real Q&A answer plus
    its citations, and AD-16 permits it exactly the way `GET /meetings`
    already is — a public-api read, no server module imported. `retrieval.py`
    joins in story 5.3: check 2.10 rides the public `GET /search` (the route
    is the surface under test) and check 2.11's approval is the harness's one
    sanctioned mutation, `POST /moments/{id}/approve`.

    Scoped to `harness/` rather than all of `evals/` on purpose: tests that
    exercise these calls offline must import httpx themselves to build a
    MockTransport / fake client, and a walk that forbade it would have forced
    the network calls to stay untested to keep a guard green — which is the
    guard defeating the thing it exists to protect.
    """
    users = {
        path.relative_to(HARNESS_ROOT).as_posix()
        for path in python_files(HARNESS_ROOT)
        if "httpx" in imported_modules(path)
    }
    assert users == {"subjects.py", "judge.py", "retrieval.py"}


def test_the_only_database_connection_lives_in_one_harness_module() -> None:
    """`psycopg` is reachable from exactly one module of the harness package.

    The same shape as the network guard above, and for a sharper reason. The
    check algorithms are pure functions over rows so they can be exercised
    with no Docker store; the moment a second module opens a connection, that
    property is gone and the matrix in `tests/test_checks.py` starts needing
    a live corpus to run.

    Scoped to `harness/` for the same reason the network guard is: the
    store-backed suite legitimately imports `psycopg` to assert that a write
    through the harness's connection is refused, and a walk that forbade it
    would have made the read-only guarantee untestable.
    """
    users = {
        path.relative_to(HARNESS_ROOT).as_posix()
        for path in python_files(HARNESS_ROOT)
        if "psycopg" in imported_modules(path)
    }
    assert users == {"corpus.py"}


@pytest.mark.parametrize(
    ("driver", "expected"),
    [
        # `checks/gate_probe.py` (story 11.3) is the one sanctioned second
        # importer, and only of the *error* family: telling "absent" from
        # "broken" when the probe's erasure is verified needs
        # `MeilisearchApiError`, and faking that distinction at any other
        # seam would leave the verification untestable. Its store calls are
        # pinned delete-only below — the probe layer can erase the run's own
        # probe and can never fabricate the membership the check asserts.
        ("meilisearch", {"harness/stores.py", "checks/gate_probe.py"}),
        # The graph erasure needs no `neo4j` import at all: the driver
        # handle is duck-typed, so `harness/stores.py` stays the single
        # module that can even construct one.
        ("neo4j", {"harness/stores.py"}),
    ],
)
def test_the_only_store_read_connection_lives_in_one_harness_module(
    driver: str, expected: set[str]
) -> None:
    """`meilisearch` and `neo4j` are reachable from exactly the named modules.

    Same shape as the psycopg guard, scoped *wider* on purpose — the whole
    `evals/` tree, tests included — because unlike psycopg (which the
    write-probe test legitimately imports) nothing else in `evals/` has any
    business holding a store driver: the store-backed publish-gate test
    observes through `stores.py`'s read-only functions, and the store-free
    suite fakes at that seam rather than at the driver.
    """
    users = {
        path.relative_to(EVALS_ROOT).as_posix()
        for path in python_files()
        if any(
            module == driver or module.startswith(f"{driver}.")
            for module in imported_modules(path)
        )
    }
    assert users == expected


#: Write-method *stems* `harness/stores.py` must never reference. Stems, not
#: exact names, because the real Meilisearch surface is a family per stem —
#: `add_documents`, `add_documents_in_batches`, `update_documents`,
#: `update_settings`, `delete_document`, `delete_documents`, `delete_index`,
#: `create_index` — and an underscore is a word character, so an exact
#: `\bdelete\b` never matches `delete_documents`. Each stem is matched with a
#: left word boundary and any `\w*` suffix, which also refuses the prose
#: forms ("deleting", "updated"): deliberately strict, because a false
#: positive costs a reworded comment while a false negative costs the
#: read-only guarantee. Checked textually rather than by AST, the same
#: reasoning as the media-root guard below: the rule is "this name never
#: appears", however it would be reached.
_STORE_WRITE_STEMS = (
    "add_document",
    "delete",
    "update",
    "create_index",
    "execute_write",
)


def store_write_references(text: str) -> list[str]:
    """Every write-method-shaped token in ``text``, or an empty list."""
    found: list[str] = []
    for stem in _STORE_WRITE_STEMS:
        found.extend(re.findall(rf"\b{stem}\w*", text))
    return found


def test_the_store_reads_module_never_references_a_write_method() -> None:
    """AD-16's read-only half, pinned on the one module that could break it.

    2.11 is meaningless if the harness can write the stores it audits — a
    check that seeded its own membership would be asserting against state it
    produced. The Neo4j session is additionally opened `default_access_mode=
    READ`; this pin is the belt to that brace, and it runs store-free.
    """
    text = (HARNESS_ROOT / "stores.py").read_text(encoding="utf-8")
    offenders = store_write_references(text)
    assert not offenders, (
        f"harness/stores.py references {offenders} — the store-reads module is"
        " pinned to read-only usage (AD-16): the publish-gate check must never"
        " be able to write the membership it asserts"
    )


@pytest.mark.parametrize(
    "call",
    [
        "client.index(x).add_documents([doc])",
        "index.add_documents_in_batches(docs)",
        "index.update_documents([doc])",
        "index.update_settings(settings)",
        "index.delete_document(doc_id)",
        "index.delete_documents([doc_id])",
        "client.delete_index(uid)",
        "client.create_index(uid)",
        "session.execute_write(work)",
    ],
)
def test_the_write_method_pin_catches_the_real_store_surface(call: str) -> None:
    """The guard on the guard: the porous first version of this pin used
    exact names with `\\b...\\b`, which matched none of the suffixed forms —
    an underscore is a word character — so `update_documents` would have
    sailed through a "read-only" module."""
    assert store_write_references(call), f"the pin missed {call!r}"


def test_the_write_method_pin_leaves_read_vocabulary_alone() -> None:
    for benign in (
        "client.index(x).get_document(doc_id)",
        "session.run(query)",
        "READ_ACCESS",
        "additional documentation",
        "the membership read",
    ):
        assert not store_write_references(benign), benign


#: Store-write stems `checks/gate_probe.py` must never reference — every
#: stem of `harness/stores.py`'s pin *except* `delete`. Story 11.3's
#: sanction is exactly one direction wide: the probe layer erases the run's
#: own probe (`delete_document`, `DETACH DELETE`, and the Postgres row it
#: minted) and can never create or reshape store state — a probe that could
#: put a document *into* a store would be fabricating the membership the
#: check asserts, which is the AD-16 failure mode this whole suite exists
#: to refuse.
_PROBE_FORBIDDEN_STEMS = tuple(
    stem for stem in _STORE_WRITE_STEMS if stem != "delete"
)

#: Raw query-clause vocabulary the probe module must never carry — the
#: channel its writes actually travel. The driver-method stems above cannot
#: see inside a `session.run("MERGE …")` string, and the module's sanctioned
#: writes are themselves raw text (`DETACH DELETE`, `DELETE FROM artifact`,
#: `INSERT INTO artifact` — the mint, sanctioned by the seeding convention),
#: so the same textual scan covers the clause forms: Cypher's creation and
#: mutation keywords plus SQL's uppercase `UPDATE`, which the lowercase
#: `update` stem cannot match. Uppercase-exact on purpose — `SET` must not
#: fire on "settled", and a query keyword is always written uppercase here.
_PROBE_FORBIDDEN_QUERY_CLAUSES = (
    "MERGE",
    "CREATE",
    "SET",
    "REMOVE",
    "FOREACH",
    "UPDATE",
)

_ALLOWED_PROBE_QUERIES = {
    "INSERT INTO artifact (moment_id, meeting_id, kind, title, body) VALUES (%s, %s, %s, %s, %s) RETURNING id",
    "DELETE FROM artifact WHERE id = %s",
    "MATCH (a {id: $id}) DETACH DELETE a",
}


def normalized_query(query: str) -> str:
    return " ".join(query.split())


def unsafe_probe_query(query: str) -> bool:
    """Whether a write-shaped SQL/Cypher query exceeds the exact sanction."""
    normalized = normalized_query(query)
    if normalized in _ALLOWED_PROBE_QUERIES:
        return False
    return bool(
        re.search(
            r"\b(?:insert|delete|merge|create|set|remove|foreach|update)\b",
            normalized,
            flags=re.IGNORECASE,
        )
    )


def probe_write_references(text: str) -> list[str]:
    """Every creation-shaped store token in ``text``, or an empty list."""
    found: list[str] = []
    for stem in _PROBE_FORBIDDEN_STEMS:
        found.extend(re.findall(rf"\b{stem}\w*", text))
    for clause in _PROBE_FORBIDDEN_QUERY_CLAUSES:
        found.extend(re.findall(rf"\b{clause}\b", text))
    return found


def test_the_probe_module_is_pinned_to_the_erasure_direction() -> None:
    """The 11.3 sanction's width, checked textually like the stores pin."""
    text = (EVALS_ROOT / "checks" / "gate_probe.py").read_text(encoding="utf-8")
    offenders = probe_write_references(text)
    assert not offenders, (
        f"checks/gate_probe.py references {offenders} — the probe layer is"
        " sanctioned for erasure only: it deletes the run's own probe and"
        " never creates or reshapes store state (story 11.3, AD-16)"
    )


def test_the_probe_pin_still_catches_the_creation_surface() -> None:
    """The guard on the guard: dropping `delete` must not have dropped the
    stems that matter — and the raw-query channel the module actually
    writes through is covered too, since a `session.run("MERGE …")` never
    names a driver method."""
    for call in (
        "client.index(x).add_documents([doc])",
        "index.add_documents_in_batches(docs)",
        "index.update_documents([doc])",
        "index.update_settings(settings)",
        "client.create_index(uid)",
        "session.execute_write(work)",
        'session.run("MERGE (a {id: $id})")',
        'session.run("CREATE (a:Artifact {id: $id})")',
        'session.run("MATCH (a {id: $id}) SET a.state = \'published\'")',
        'session.run("MATCH (a {id: $id}) REMOVE a.state")',
        'conn.execute("UPDATE artifact SET state = %s")',
    ):
        assert probe_write_references(call), f"the probe pin missed {call!r}"


@pytest.mark.parametrize(
    "query",
    [
        "match (a {id: $id}) set a.state = 'published'",
        "mErGe (a:Artifact {id: $id})",
        "INSERT INTO artifact (moment_id, meeting_id, kind, title, body, state) VALUES (%s, %s, %s, %s, %s, 'published') RETURNING id",
        "INSERT INTO artifact (moment_id, meeting_id, kind, title, body) VALUES (%s, %s, %s, %s, %s), (%s, %s, %s, %s, %s) RETURNING id",
        "DELETE FROM artifact",
        "MATCH (a) DETACH DELETE a",
    ],
)
def test_the_probe_query_allowlist_rejects_mutation_canaries(query: str) -> None:
    assert unsafe_probe_query(query), f"the exact query pin admitted {query!r}"


def test_the_probe_query_allowlist_is_exactly_the_three_sanctioned_shapes() -> None:
    source = (EVALS_ROOT / "checks" / "gate_probe.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assigned: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            if isinstance(value, str):
                assigned[node.targets[0].id] = normalized_query(value)

    actual = {
        assigned["_INSERT_PROBE"],
        assigned["_DELETE_PROBE"],
        assigned["_ERASE_NODE"],
    }
    assert actual == _ALLOWED_PROBE_QUERIES
    assert all(not unsafe_probe_query(query) for query in actual)


def test_the_probe_cleanup_delegates_every_store_read_to_stores() -> None:
    """F9: the delete exception does not create a second read boundary."""
    text = (EVALS_ROOT / "checks" / "gate_probe.py").read_text(encoding="utf-8")
    assert ".get_document(" not in text
    assert "_NODE_PRESENT" not in text
    assert "stores.artifact_in_search(search, artifact_id)" in text
    assert "stores.artifact_in_graph(graph, artifact_id)" in text


def test_operational_docs_keep_evals_single_flight_until_live_acceptance() -> None:
    """F11: fake-proven concurrency is not yet an operator permission."""
    repo = EVALS_ROOT.parent
    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    dispatch = (repo / ".claude/skills/integrate/dispatch.md").read_text(
        encoding="utf-8"
    )
    runbook = (EVALS_ROOT / "RUNBOOK.md").read_text(encoding="utf-8")

    assert "**`make evals-run` is still one at a time.**" in agents
    assert "may overlap another eval run" not in agents
    assert "must not overlap another eval run" in dispatch
    assert "Run only one `make evals-run` at a time" in runbook
    assert "do not contend" not in runbook


def test_the_probe_pin_leaves_the_erasure_vocabulary_alone() -> None:
    for benign in (
        "index.delete_document(doc_id)",
        "MATCH (a {id: $id}) DETACH DELETE a",
        "DELETE FROM artifact WHERE id = %s",
        "INSERT INTO artifact (moment_id) VALUES (%s) RETURNING id",
        "the erasure verification",
        "a settled stage's newest checkpoint",
    ):
        assert not probe_write_references(benign), benign


def test_the_harness_connection_is_read_only_by_construction() -> None:
    """AD-16's read-only half is a libpq option, not a reviewer's vigilance.

    The store-backed suite pins that Postgres actually refuses the write; this
    pins that the option is on the conninfo at all, with no store running — so
    dropping it cannot pass unnoticed until somebody next brings the stack up.
    """
    from evals.harness.corpus import read_only_conninfo

    class Postgres:
        host, port, database, user = "localhost", 5433, "meetingminer", "meetingminer"

    class Config:
        settings = type("S", (), {"stores": type("T", (), {"postgres": Postgres})})
        secrets = type("Secrets", (), {"postgres_password": "pw-not-from-env"})

    conninfo = read_only_conninfo(Config())
    assert "default_transaction_read_only=on" in conninfo
    assert "dbname=meetingminer" in conninfo


#: The two evidence-root environment variables AD-12's judge-scoped egress
#: rule forbids the judge/bake-off modules from ever reading. Both name real
#: filesystem roots holding drop material and pipeline-produced media; a
#: judge or candidate call may see only text already derived in Postgres or
#: via the public API (transcript segments, `qa` answers, `artifact.title`/
#: `body`) — never a recording path or media bytes.
_MEDIA_ROOT_ENV_VARS = ("MM_CONTENT_ROOT", "MM_DROPS_ROOT")


@pytest.mark.parametrize("name", ["judge.py", "bakeoff.py"])
def test_the_judge_and_bakeoff_modules_never_reach_for_media_roots(name: str) -> None:
    """AD-12's judge-scoped egress rule, checked textually rather than trusted.

    Scanning the source text rather than the AST: the rule is "this string
    never appears", regardless of whether it would arrive via `os.environ`,
    `os.getenv`, an f-string, or a constant nobody has written yet — the same
    reasoning `run.py`'s `SECRET_KEY_HINTS` scrub applies to config values.
    """
    text = (HARNESS_ROOT / name).read_text(encoding="utf-8")
    offenders = [var for var in _MEDIA_ROOT_ENV_VARS if var in text]
    assert not offenders, (
        f"harness/{name} references {offenders} — AD-12's judge-scoped egress"
        " rule: a judge/candidate call may see only text already derived in"
        " Postgres or via the public API, never a recording path or media bytes"
    )
