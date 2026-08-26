"""Contract tests for GET /status (SPEC-system-status).

Three non-negotiables from the frozen contract, each pinned here:

* the payload is an explicit allowlist that carries no key material — asserted
  against a config whose secrets are known fake strings;
* an invalid key surfaces as ``keyState: "invalid"`` with the binding named
  ``llm.roles.<role>`` (CAP-3's copy contract with the chat panel) and a
  concrete remediation (CAP-2);
* probe results are cached: a second request inside the cache window does not
  re-probe the provider, so UI polling stays free.

A fourth, added when the stopped-worker row stopped guessing at money: that row
states facts and renders no cost verdict, under every extraction binding.

Every provider probe is stubbed — no network I/O toward any provider, paid or
free, happens in this file. Store probes for Neo4j/Meilisearch are stubbed the
same way so the suite does not depend on which containers happen to be up;
Postgres is real (the per-run test database the ``client`` fixture owns).
"""

from __future__ import annotations

from typing import Literal, NoReturn

import psycopg
import pytest
from fastapi import Request
from psycopg_pool import ConnectionPool

import meetingminer.api.main as api_main
from meetingminer import db
from meetingminer.api import status as status_module
from meetingminer.api.status import ProbeResult
from meetingminer.config import AppConfig

FAKE_SECRETS = {
    "anthropic_api_key": "sk-ant-FAKE-SECRET-anthropic-0000",
    "openai_api_key": "sk-FAKE-SECRET-openai-1111",
    "openrouter_api_key": "sk-or-FAKE-SECRET-openrouter-2222",
    "postgres_password": "FAKE-SECRET-postgres-3333",
    "neo4j_password": "FAKE-SECRET-neo4j-4444",
    "meili_master_key": "FAKE-SECRET-meili-5555",
}

RESPONSE_FIELDS = {"generatedAt", "overall", "api", "stores", "llmRoles", "worker"}
COMPONENT_FIELDS = {"id", "label", "state", "detail", "remediation"}
ROLE_FIELDS = {
    "role", "model", "fallback", "provider", "keyState", "state", "detail",
    "remediation",
}
WORKER_FIELDS = {"state", "jobs", "stageBacklog", "detail", "remediation"}

# The whole vocabulary of a cost claim, not one phrase of it. The row this
# guards once derived paid-vs-free from the provider prefix and failed open —
# every prefix outside `KEY_ENV_VARS` rendered as costing nothing — so what is
# pinned here is the absence of the judgement, not the wording of one version
# of it.
COST_VOCABULARY = ("spend", "paid", "free", "no money", "costs", "explicit yes")

# SPEC-system-status' read-only constraint, verbatim. Asserted in every branch
# that builds a worker remediation, not just one.
READ_ONLY_SENTENCE = (
    "This page only reports; it never starts, restarts, or resumes anything."
)


@pytest.fixture(autouse=True)
def _fresh_probe_cache():
    """Each test owns the module cache — cache behavior is itself under test."""
    status_module._PROBE_CACHE.clear()
    yield
    status_module._PROBE_CACHE.clear()


@pytest.fixture(autouse=True)
def _stores_up(monkeypatch: pytest.MonkeyPatch):
    """Neo4j/Meilisearch read as up without touching any real port."""
    monkeypatch.setattr(
        status_module, "_check_neo4j", lambda uri: (True, "stubbed up")
    )
    monkeypatch.setattr(
        status_module, "_check_meilisearch", lambda url: (True, "stubbed up")
    )


@pytest.fixture()
def fake_secret_config(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> AppConfig:
    """The committed config with every secret replaced by a known fake string,
    installed as the app's config for the duration of one test."""
    config = app_config.model_copy(
        update={"secrets": app_config.secrets.model_copy(update=FAKE_SECRETS)}
    )
    monkeypatch.setattr(api_main.app.state, "config", config)
    return config


def probe_stub(results: dict[str, ProbeResult], calls: list[tuple[str, str]]):
    def _probe(provider: str, base_url: str, api_key: str | None) -> ProbeResult:
        calls.append((provider, base_url))
        return results.get(provider, ProbeResult("ok", "stub ok"))

    return _probe


# --- the stopped-worker row ------------------------------------------------


def expected_worker_stopped_remediation(
    pending: int, model: str, fallback: str | None
) -> str:
    """The complete authored message, with identifiers inserted unchanged.

    Exact equality is intentional: a vocabulary list alone cannot reject an
    unlisted verdict such as "billable". Pinning all authored prose makes any
    added judgement fail while still allowing arbitrary configuration values.
    """
    paused = (
        "no work is currently paused"
        if pending == 0
        else f"{pending} job(s) are currently paused"
    )
    binding = f"`llm.roles.extraction` ({model})"
    if fallback is not None:
        binding += f" with `extraction.fallback` ({fallback})"
    return (
        f"leaving it stopped is the current deliberate state; {paused}."
        " For the worker's only `llm.roles.*` call,"
        f" this API process has loaded {binding}. A newly started worker"
        " reloads `config.yaml`, so its loaded binding may differ."
        f" {READ_ONLY_SENTENCE}"
    )


def assert_states_facts_without_a_cost_claim(
    remediation: str | None,
    *,
    pending: int,
    model: str,
    fallback: str | None,
) -> None:
    """The stopped-worker invariant, asserted identically in every case.

    The endpoint may report current paused work, which binding this API loaded,
    and that a new worker reloads config; it may not predict startup or say
    what that costs. The row stays non-null whatever the binding is — the
    indicator renders it (`status.test.tsx`) — and carries the read-only
    sentence verbatim.
    """
    assert remediation is not None, "a stopped worker must carry a remediation"
    assert remediation == expected_worker_stopped_remediation(
        pending, model, fallback
    )

    # Model identifiers are quoted configuration facts, not authored prose.
    # Remove their exact, unchanged values before applying the vocabulary ban.
    authored = remediation.replace(model, "<primary-model>")
    if fallback is not None:
        authored = authored.replace(fallback, "<fallback-model>")
    lowered = authored.lower()
    for word in COST_VOCABULARY:
        assert word not in lowered, (
            f"the worker remediation makes a cost claim ({word!r}): {remediation}"
        )


def bind_extraction(
    config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    fallback: str | None,
) -> AppConfig:
    """Install ``config`` with `llm.roles.extraction` rebound, and return it.

    Deep-copied first: ``app_config`` is session-scoped, so rebinding the role
    in place would leak the test's binding into every later test in the run.
    """
    rebound = config.model_copy(deep=True)
    roles = rebound.settings.llm.roles
    roles.extraction = roles.extraction.model_copy(
        update={"model": model, "fallback": fallback}
    )
    monkeypatch.setattr(api_main.app.state, "config", rebound)
    return rebound


def add_jobs(
    pool: ConnectionPool, count: int, status: Literal["queued", "running"]
) -> None:
    """Create jobs and stages in one paused-backlog status."""
    with pool.connection() as conn:
        for index in range(count):
            job_id = conn.execute(
                "INSERT INTO job (source_id, drop_path, corpus, status)"
                " VALUES (%s, %s, 'real', %s) RETURNING id",
                (
                    f"status-{status}-src-{index}",
                    f"/tmp/status-{status}-{index}",
                    status,
                ),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO job_stage (job_id, name, status)"
                " VALUES (%s, 'extract', %s)",
                (job_id, status),
            )


def remediation_must_not_be_built(pending: int, config: AppConfig) -> NoReturn:
    """Stand-in for the stopped-worker sentence where it must never be built.

    A raise rather than a sentinel string: the two cases that install this are
    about the branch not being *entered* at all, and a returned marker would
    still let a wrong branch pass its other assertions.
    """
    raise AssertionError(
        f"the stopped-worker remediation was built (pending={pending});"
        " this branch must not be entered"
    )


def postgres_down(request: Request) -> tuple[bool, str]:
    """`_check_postgres` for the store-is-down case: no real outage needed."""
    return False, "query failed: stubbed down"


def test_payload_is_an_allowlist_with_no_key_material(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, calls))

    response = client.get("/status")
    assert response.status_code == 200, response.text

    # No fragment of any secret — not the whole value, not a prefix long
    # enough to matter — appears anywhere in the serialized response.
    for secret in FAKE_SECRETS.values():
        assert secret not in response.text
        assert secret[:12] not in response.text

    body = response.json()
    assert set(body) == RESPONSE_FIELDS
    assert set(body["api"]) == COMPONENT_FIELDS
    assert {store["id"] for store in body["stores"]} == {
        "postgres", "neo4j", "meilisearch",
    }
    for store in body["stores"]:
        assert set(store) == COMPONENT_FIELDS
    assert {row["role"] for row in body["llmRoles"]} == {
        "extraction", "chat", "judge",
    }
    for row in body["llmRoles"]:
        assert set(row) == ROLE_FIELDS
    assert set(body["worker"]) == WORKER_FIELDS

    # The api row is trivially up: this response is the evidence.
    assert body["api"]["state"] == "ok"


def test_invalid_key_names_binding_and_remediation(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CAP-2 + CAP-3: the row states what is broken and what to do, naming the
    binding `llm.roles.chat` exactly the way the chat panel's 503 does."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        status_module,
        "_probe_provider",
        probe_stub(
            {"openai": ProbeResult("invalid-key", "the provider refused the key (HTTP 401)")},
            calls,
        ),
    )

    body = client.get("/status").json()
    chat = next(row for row in body["llmRoles"] if row["role"] == "chat")
    assert chat["keyState"] == "invalid"
    assert chat["state"] == "degraded"
    assert "`llm.roles.chat`" in chat["detail"]
    assert "OPENAI_API_KEY" in chat["detail"]
    assert "OPENAI_API_KEY" in chat["remediation"]
    assert ".env" in chat["remediation"]
    assert "restart the api" in chat["remediation"]
    # The committed chat binding has no fallback (owner decision of record).
    assert chat["fallback"] is None
    # One degraded row degrades the whole surface — no silent green.
    assert body["overall"] == "degraded"

    # judge shares the same binding style; the stub also marked it invalid.
    judge = next(row for row in body["llmRoles"] if row["role"] == "judge")
    assert judge["keyState"] == "invalid"
    assert "`llm.roles.judge`" in judge["detail"]


def test_missing_key_is_reported_without_probing(
    client, app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = app_config.model_copy(
        update={
            "secrets": app_config.secrets.model_copy(
                update={**FAKE_SECRETS, "openai_api_key": None}
            )
        }
    )
    monkeypatch.setattr(api_main.app.state, "config", config)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, calls))

    body = client.get("/status").json()
    chat = next(row for row in body["llmRoles"] if row["role"] == "chat")
    assert chat["keyState"] == "missing"
    assert chat["state"] == "degraded"
    assert "OPENAI_API_KEY" in chat["detail"]
    assert "set OPENAI_API_KEY in .env" in chat["remediation"]
    # A missing key is a fact, not something to probe: no openai probe ran.
    assert all(provider != "openai" for provider, _ in calls)


def test_probe_results_are_cached_between_polls(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second request inside PROBE_TTL_SECONDS re-probes nothing; once the
    window passes, each endpoint is probed exactly once more."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, calls))

    clock = {"now": 1000.0}
    monkeypatch.setattr(status_module, "_now", lambda: clock["now"])

    assert client.get("/status").status_code == 200
    first_round = list(calls)
    assert first_round, "expected the first request to probe at least one provider"

    # Second poll, one second later: entirely served from the cache.
    clock["now"] += 1.0
    assert client.get("/status").status_code == 200
    assert calls == first_round

    # Past the TTL: each cached endpoint is probed exactly once more.
    clock["now"] += status_module.PROBE_TTL_SECONDS
    assert client.get("/status").status_code == 200
    assert calls == first_round + first_round


def test_worker_stopped_with_an_empty_queue_reports_no_paused_work(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No worker runs during tests, so the advisory lock is free — and the
    ``client`` fixture truncates the job tables, so the backlog is genuinely
    empty. The sentence reports the observed queue, so an empty one must say
    no work is currently paused rather than predicting a future startup."""
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))
    extraction = fake_secret_config.settings.llm.roles.extraction

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert worker["jobs"] == {}
    assert "no work is currently paused" in worker["remediation"]
    assert f"`llm.roles.extraction` ({extraction.model})" in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"],
        pending=0,
        model=extraction.model,
        fallback=extraction.fallback,
    )
    # A stopped pipeline is not a green surface, backlog or no backlog.
    assert body["overall"] == "degraded"


def test_worker_stopped_reports_the_work_currently_paused(
    client,
    fake_secret_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    test_pool: ConnectionPool,
) -> None:
    """With work waiting, report the queue snapshot rather than predicting
    what a future worker start will claim or process."""
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))
    add_jobs(test_pool, 3, "queued")
    extraction = fake_secret_config.settings.llm.roles.extraction

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert worker["jobs"].get("queued") == 3
    assert worker["stageBacklog"].get("extract") == 3
    assert "3 paused job(s)" in worker["detail"]
    assert "3 job(s) are currently paused" in worker["remediation"]
    assert f"`llm.roles.extraction` ({extraction.model})" in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"],
        pending=3,
        model=extraction.model,
        fallback=extraction.fallback,
    )
    assert body["overall"] == "degraded"


def test_worker_stopped_counts_orphaned_running_jobs_as_currently_paused(
    client,
    fake_secret_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    test_pool: ConnectionPool,
) -> None:
    """Startup requeues crash-orphaned running jobs before claiming work.

    The paused-work snapshot must therefore include both queued and running
    rows. This mixed case fails if the remediation is fed only the queued count.
    """
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))
    add_jobs(test_pool, 2, "queued")
    add_jobs(test_pool, 1, "running")
    extraction = fake_secret_config.settings.llm.roles.extraction

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert worker["jobs"].get("queued") == 2
    assert worker["jobs"].get("running") == 1
    assert "3 job(s) are currently paused" in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"],
        pending=3,
        model=extraction.model,
        fallback=extraction.fallback,
    )
    assert body["overall"] == "degraded"


def test_worker_stopped_on_a_key_required_binding_makes_no_cost_claim(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: an extraction role bound to a key-required provider
    once made this row emit a spend gate. The row names the binding and says
    nothing about money — the owner reading ``openai/gpt-5.2`` knows the rest."""
    bind_extraction(fake_secret_config, monkeypatch, "openai/gpt-5.2", None)
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert "`llm.roles.extraction` (openai/gpt-5.2)" in worker["remediation"]
    # No fallback configured, so none is named.
    assert "`extraction.fallback`" not in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"],
        pending=0,
        model="openai/gpt-5.2",
        fallback=None,
    )
    assert body["overall"] == "degraded"


def test_worker_stopped_on_an_unrecognized_provider_makes_no_cost_claim(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect that ended the derived-cost approach: `KEY_ENV_VARS` answers
    "which env var holds this provider's key", and a prefix it does not carry
    got read as keyless — so `gemini/` rendered as costing nothing. Nothing in
    this row classifies a provider now, so an unknown prefix reads exactly like
    a known one."""
    bind_extraction(fake_secret_config, monkeypatch, "gemini/gemini-2.5-pro", None)
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert "`llm.roles.extraction` (gemini/gemini-2.5-pro)" in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"],
        pending=0,
        model="gemini/gemini-2.5-pro",
        fallback=None,
    )
    assert body["overall"] == "degraded"


def test_worker_stopped_preserves_vocabulary_bearing_model_identifier(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The prose-only invariant never sanitizes configuration facts."""
    model = "openrouter/example:free"
    bind_extraction(fake_secret_config, monkeypatch, model, None)
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert f"`llm.roles.extraction` ({model})" in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"], pending=0, model=model, fallback=None
    )
    assert body["overall"] == "degraded"


def test_worker_stopped_names_the_extraction_fallback_too(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`build_llm` engages `extraction.fallback` on any primary `LlmError`, so
    it is a binding a restarted worker can route to and the row names it. The
    pairing here is the second defect the derived-cost version missed: a local
    primary with a key-required fallback, which read as entirely local."""
    bind_extraction(
        fake_secret_config, monkeypatch, "ollama/gpt-oss:120b", "openai/gpt-5.2"
    )
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert (
        "`llm.roles.extraction` (ollama/gpt-oss:120b) with"
        " `extraction.fallback` (openai/gpt-5.2)" in worker["remediation"]
    )
    assert_states_facts_without_a_cost_claim(
        worker["remediation"],
        pending=0,
        model="ollama/gpt-oss:120b",
        fallback="openai/gpt-5.2",
    )
    assert body["overall"] == "degraded"


def test_worker_stopped_preserves_vocabulary_bearing_fallback_identifier(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fallback identifier stays exact even when it bears banned vocabulary.

    The explicit equality assertion is the sanitization regression guard: any
    rewrite of the fallback to remove ``free`` makes this endpoint case fail.
    """
    model = "ollama/gpt-oss:120b"
    fallback = "openrouter/example:free"
    bind_extraction(fake_secret_config, monkeypatch, model, fallback)
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert f"`extraction.fallback` ({fallback})" in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"], pending=0, model=model, fallback=fallback
    )
    assert body["overall"] == "degraded"


def test_worker_running_builds_no_stopped_remediation(
    client,
    app_config: AppConfig,
    test_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the worker's own advisory lock held, the stopped branch must not be
    entered at all — the raise-only stub is what proves it, rather than an
    assertion on the message it would have produced.

    ``app_config`` rather than ``fake_secret_config``: this case opens its own
    Postgres connection to take the lock, and ``FAKE_SECRETS`` replaces
    ``postgres_password``, so a fake-secret config could not authenticate
    against the test database. The ``client`` fixture already installs
    ``app_config`` as the app's config, and this row reads no secrets.
    """
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))
    monkeypatch.setattr(
        status_module, "_worker_stopped_remediation", remediation_must_not_be_built
    )

    # The exact call `worker/main.py` `acquire_worker_lock` makes. `try` rather
    # than a blocking acquire: a lock leaked by an earlier run then fails this
    # test loudly instead of hanging the suite on it.
    with psycopg.connect(db.conninfo(app_config, database=test_database)) as conn:
        held = bool(
            conn.execute(
                "SELECT pg_try_advisory_lock(hashtext('meetingminer-worker'))"
            ).fetchone()[0]
        )
        assert held, "the worker advisory lock was already held on the test database"
        worker = client.get("/status").json()["worker"]

    assert worker["state"] == "running"
    assert worker["remediation"] is None


def test_postgres_down_reports_the_stores_remediation_not_the_stopped_one(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker state is read through Postgres, so with Postgres down there is no
    lock to read and no queue to count: the row says ``unknown`` and points at
    the stores. The stopped sentence has nothing to compose from and must not
    be built — the raise-only stub proves the branch is not entered."""
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))
    monkeypatch.setattr(status_module, "_check_postgres", postgres_down)
    monkeypatch.setattr(
        status_module, "_worker_stopped_remediation", remediation_must_not_be_built
    )

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "unknown"
    assert worker["jobs"] == {}
    assert worker["remediation"] == status_module._STORES_REMEDIATION
    assert body["overall"] == "degraded"
