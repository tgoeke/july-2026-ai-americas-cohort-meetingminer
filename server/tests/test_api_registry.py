"""Auto-discovered route registration (story 2.8).

The four prose comments that used to sit on ``main.py``'s ``include_router``
block are assertions here: discovery finds every router module and only
router modules; events registers before jobs so ``/jobs/events`` is never
read as a malformed job UUID; media's recording route beats its own
catch-all; and ``main.py`` contains no hand registration to creep back.
"""

from __future__ import annotations

import pkgutil
import sys
import textwrap
import uuid
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Match

import meetingminer.api
from meetingminer.api.registry import discover_routers, register_routers


BASELINE_ROUTER_ORDER = [
    "ingests",
    "events",
    "jobs",
    "meetings",
    "moments",
    "search",
    "chat",
    "media",
    # Story 4.2: `extraction.py` declares no `ROUTER_ORDER`, so it sorts at
    # `DEFAULT_ROUTER_ORDER` (100) — after every module above, which all
    # declare an explicit order below that — with the module name as the
    # tie-break among default-order modules. `participants` (story 2-4) is
    # also default-order, so it sorts after `extraction` by name.
    # Story ui-1: `config_view.py` is default-order too, sorting before
    # `extraction` by name. `/config` has no parameterized sibling anywhere,
    # so its position carries no matching hazard.
    "config_view",
    "extraction",
    "participants",
    # Story 8.2: `settings.py` is default-order too, sorting between
    # `participants` and `speakers` by name. `/settings/models` is a literal
    # sibling of `/settings/roles/{role}`, but they diverge at the segment
    # after `/settings`, so neither can swallow the other and the two live in
    # one router regardless of position.
    "settings",
    # Story 7.2: `speakers.py` is default-order too, sorting between
    # `participants` and `stats` by name. `/meetings/{meeting_id}/speakers`
    # is a literal leaf under a parameterized meeting id — the same shape the
    # already-registered `/meetings/{meeting_id}/moments` has — and no
    # `/meetings/{meeting_id}/{anything}` catch-all exists, so its position
    # carries no matching hazard.
    "speakers",
    # Story ui-1: `/corpus/stats` — no parameterized sibling under `/corpus`
    # exists anywhere, so default order and the name sort are safe.
    "stats",
    # SPEC-system-status: `status.py` is also default-order, sorting after
    # `stats` by name. `/status` has no parameterized sibling anywhere,
    # so its position carries no matching hazard.
    "status",
    # Story 2.5: `structure` is also default-order, sorting after `status`
    # by name. `/structure` has no parameterized sibling anywhere, so its
    # position carries no matching hazard.
    "structure",
]


def _flat_routes(routes: list) -> list[APIRoute]:
    """The app's APIRoutes in dispatch order. FastAPI keeps an included router
    as a nested `_IncludedRouter` entry and matches into it in place, so the
    flattened sequence is the order first-FULL-match dispatch walks.

    Depends on `_IncludedRouter.original_router`, a private FastAPI attribute
    (0.141): an upgrade that renames it would make this return only the
    top-level routes, so callers assert the result is non-empty rather than
    letting a vacuous pass hide the breakage.
    """
    flat: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            flat.append(route)
        elif hasattr(route, "original_router"):
            flat.extend(_flat_routes(route.original_router.routes))
    return flat


def _first_matching_route(app: FastAPI, method: str, path: str) -> APIRoute:
    """The route FastAPI would dispatch to: the first FULL match in table order."""
    scope = {"type": "http", "method": method, "path": path, "root_path": ""}
    flat = _flat_routes(app.router.routes)
    assert flat, "flattening found no APIRoutes — private-attr dependency broke?"
    for route in flat:
        match, _ = route.matches(scope)
        if match is Match.FULL:
            return route
    raise AssertionError(f"no route matches {method} {path}")


def _router_modules() -> dict[str, APIRouter]:
    """Every module in the package exposing an APIRouter, found independently
    of the registry's own walk so the two can disagree loudly."""
    import importlib

    found: dict[str, APIRouter] = {}
    for info in pkgutil.iter_modules(meetingminer.api.__path__):
        if info.name == "main" or info.name.startswith("_"):
            continue
        module = importlib.import_module(f"meetingminer.api.{info.name}")
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            found[info.name] = router
    return found


def test_every_router_module_is_discovered() -> None:
    """A new endpoint file cannot be silently omitted: discovery returns
    exactly the modules that expose an APIRouter."""
    discovered = dict(discover_routers())
    assert discovered == _router_modules()
    # The eight known surfaces, as a floor (a ninth added later is fine).
    assert set(discovered) >= {
        "chat",
        "events",
        "ingests",
        "jobs",
        "media",
        "meetings",
        "moments",
        "search",
    }


def test_existing_routers_keep_the_baseline_registration_order() -> None:
    """Discovery replaces the hand-registration block without reordering its
    existing routes: FastAPI dispatches in registration order."""
    names = [name for name, _ in discover_routers()]
    assert names == BASELINE_ROUTER_ORDER


def test_non_router_modules_are_not_discovered() -> None:
    """Selection is by attribute and isinstance, never by name: `chat_router`
    is a question-to-template classifier, `problems` registers exception
    handlers, `citations` is a validator, and the entry module and the
    registry itself expose no router."""
    discovered = {name for name, _ in discover_routers()}
    for name in ("chat_router", "citations", "problems", "main", "registry", "__init__"):
        assert name not in discovered


def test_every_discovered_route_is_registered_on_the_app() -> None:
    """The app's route table carries every discovered route, path and methods."""
    import meetingminer.api.main as api_main

    flat = _flat_routes(api_main.app.router.routes)
    assert flat, "flattening found no APIRoutes — private-attr dependency broke?"
    table = {(route.path, frozenset(route.methods or ())) for route in flat}
    for name, router in discover_routers():
        for route in router.routes:
            assert isinstance(route, APIRoute)
            key = (route.path, frozenset(route.methods or ()))
            assert key in table, f"{name}: {key} missing from the app route table"


def test_jobs_events_beats_the_job_id_route() -> None:
    """`GET /jobs/events` reaches the SSE stream: events declares
    ROUTER_ORDER ahead of jobs, so `/jobs/{job_id}` can never swallow it and
    reject `events` as a malformed UUID."""
    import meetingminer.api.main as api_main

    route = _first_matching_route(api_main.app, "GET", "/jobs/events")
    assert route.endpoint.__module__ == "meetingminer.api.events"

    # And a real job id still reaches the jobs route.
    route = _first_matching_route(api_main.app, "GET", f"/jobs/{uuid.uuid4()}")
    assert route.endpoint.__module__ == "meetingminer.api.jobs"


def test_events_declares_its_order_ahead_of_jobs() -> None:
    """The ordering is declared, not inherited from the alphabet: a rename
    that sorts after `jobs` must not silently break the SSE stream."""
    names = [name for name, _ in discover_routers()]
    assert names.index("events") < names.index("jobs")

    import meetingminer.api.events as events
    import meetingminer.api.jobs as jobs

    from meetingminer.api.registry import DEFAULT_ROUTER_ORDER

    assert events.ROUTER_ORDER < getattr(jobs, "ROUTER_ORDER", DEFAULT_ROUTER_ORDER)


def test_media_recording_route_beats_the_catch_all() -> None:
    """The same hazard one level deeper, fixed inside media.py's own
    declaration order: a recording request must never fall through to the
    `/media/{path:path}` catch-all and be resolved as a file path."""
    import meetingminer.api.main as api_main

    route = _first_matching_route(
        api_main.app, "GET", f"/media/recordings/{uuid.uuid4()}"
    )
    assert route.path == "/media/recordings/{meeting_id}"

    route = _first_matching_route(api_main.app, "GET", "/media/meetings/x/1.jpg")
    assert route.path == "/media/{path:path}"


def test_a_dropped_in_module_is_discovered_without_editing_main(
    tmp_path: Path,
) -> None:
    """Adding an endpoint is adding a file: a module that appears in the
    package is discovered and served with no edit to main.py."""
    plugin = tmp_path / "zz_registry_probe.py"
    plugin.write_text(
        textwrap.dedent(
            """
            from fastapi import APIRouter

            router = APIRouter()


            @router.get("/registry-probe")
            def probe() -> dict[str, bool]:
                return {"probe": True}
            """
        )
    )
    meetingminer.api.__path__.append(str(tmp_path))
    try:
        discovered = dict(discover_routers())
        assert "zz_registry_probe" in discovered

        # A fresh app registered purely from discovery serves the new route.
        app = FastAPI()
        names = register_routers(app)
        assert "zz_registry_probe" in names
        client = TestClient(app)
        assert client.get("/registry-probe").json() == {"probe": True}
    finally:
        meetingminer.api.__path__.remove(str(tmp_path))
        sys.modules.pop("meetingminer.api.zz_registry_probe", None)


def test_discovery_names_a_module_whose_import_fails(tmp_path: Path) -> None:
    """A broken endpoint module must fail startup with its import path named,
    rather than an unattributed error from import machinery."""
    name = "aa_broken_registry_probe"
    (tmp_path / f"{name}.py").write_text('raise RuntimeError("synthetic import failure")\n')
    meetingminer.api.__path__.append(str(tmp_path))
    try:
        with pytest.raises(
            ImportError,
            match=rf"router discovery failed importing meetingminer\.api\.{name}",
        ) as exc_info:
            discover_routers()
        assert isinstance(exc_info.value.__cause__, RuntimeError)
    finally:
        meetingminer.api.__path__.remove(str(tmp_path))
        sys.modules.pop(f"meetingminer.api.{name}", None)


def test_main_contains_no_hand_registration() -> None:
    """Hand registration cannot creep back unnoticed: registry.register_routers
    is the only place routers are attached, and main.py's source never calls
    include_router."""
    import meetingminer.api.main as api_main

    source = Path(api_main.__file__).read_text()
    assert "include_router" not in source, (
        "main.py has regained an include_router call; routers are registered "
        "by meetingminer/api/registry.py discovery (story 2.8)"
    )
