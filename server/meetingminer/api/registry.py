"""Auto-discovery of API routers (story 2.8).

Any module in ``meetingminer.api`` exposing a module-level ``router`` that is
a ``fastapi.APIRouter`` is registered on the app — adding an endpoint is
adding a file, with no edit to ``main.py``. Selection is by attribute and
type, never by module name: ``chat_router.py`` is a question-to-template
classifier, not an HTTP router, and must stay a non-event. ``main`` and
underscore-prefixed names are excluded before import so discovery cannot
re-import the entry module that is running it.

Registration order is a matching contract, not a cosmetic one: FastAPI
matches routes in registration order, so a parameterized route registered
before a literal sibling swallows it. Concretely, ``/jobs/{job_id}`` would
swallow ``/jobs/events`` and reject ``events`` as a malformed UUID unless the
events router is registered first. A module declares its position with a
module-level ``ROUTER_ORDER`` (lower registers earlier; default
``DEFAULT_ROUTER_ORDER``), with the module name as tie-break — so the
events-before-jobs contract is declared in ``events.py`` rather than
inherited from the alphabet. The same hazard one level deeper —
``/media/recordings/{meeting_id}`` versus the ``/media/{path:path}``
catch-all — is resolved *inside* ``media.py`` by its internal declaration
order, which is why a router is registered whole and never split.

The hazard is also the checklist for future routes: a literal path under a
parameterized sibling's prefix must register before it. ``/moments/{moment_id}``
is safe today because no literal sibling exists anywhere in the app, but a
future ``/moments/recent`` would be swallowed and rejected as a malformed
UUID unless it registers ahead of ``moments`` — declare the literal route
before the parameterized one inside the same router (the ``media.py`` way),
or give its module a ``ROUTER_ORDER`` below the parameterized module's.

The scan is deliberately non-recursive: ``pkgutil.iter_modules`` walks only
the top level of ``meetingminer.api``, so a router defined in a *subpackage*
is not discovered. Every endpoint module is a flat file in the package today;
if a subpackage ever grows a router, discovery must be extended (and tested)
first.

Both ordering contracts are asserted by ``tests/test_api_registry.py``.
"""

from __future__ import annotations

import importlib
import pkgutil

from fastapi import APIRouter, FastAPI

import meetingminer.api

# The order a module gets when it declares none. Modules that must register
# ahead of a sibling declare a smaller `ROUTER_ORDER`.
DEFAULT_ROUTER_ORDER = 100


def discover_routers() -> list[tuple[str, APIRouter]]:
    """Return every (module name, router) in ``meetingminer.api``, in registration order.

    The name travels with the router so a failed import or an ordering
    assertion names the file rather than an anonymous router object.
    """
    found: list[tuple[int, str, APIRouter]] = []
    for info in pkgutil.iter_modules(meetingminer.api.__path__):
        name = info.name
        if name == "main" or name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"meetingminer.api.{name}")
        except Exception as exc:
            # One broken file must abort startup with an error naming the
            # module, not an unattributed traceback from the import machinery.
            raise ImportError(
                f"router discovery failed importing meetingminer.api.{name}: {exc}"
            ) from exc
        router = getattr(module, "router", None)
        if not isinstance(router, APIRouter):
            continue
        order = getattr(module, "ROUTER_ORDER", DEFAULT_ROUTER_ORDER)
        found.append((order, name, router))
    found.sort(key=lambda item: (item[0], item[1]))
    return [(name, router) for _, name, router in found]


def register_routers(app: FastAPI) -> list[str]:
    """Register every discovered router on ``app``; return the module names in order.

    This is the only place routers are attached to the app: ``main.py``
    contains no ``include_router`` call at all, and a test pins that, so hand
    registration cannot creep back unnoticed.
    """
    names: list[str] = []
    for name, router in discover_routers():
        app.include_router(router)
        names.append(name)
    return names
