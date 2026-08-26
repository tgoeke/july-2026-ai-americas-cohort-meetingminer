"""MeetingMiner API process.

Loads configuration via the shared loader at import time; a missing or
invalid config.yaml — or an unusable ``MM_DROPS_ROOT``, the anchor every
stored drop path is relative to — aborts startup with a non-zero exit, no
partial boot.
The lifespan opens the Postgres pool and refuses to boot while database
migrations are pending (same fail-fast contract: named error, no traceback).
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from meetingminer import db, logs
from meetingminer.config import (
    AppConfig,
    ConfigError,
    load_config,
    require_drops_root,
    require_publish_root,
)


def _load_or_die() -> AppConfig:
    try:
        return load_config()
    except ConfigError as exc:
        print(f"fatal: api startup aborted: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


CONFIG = _load_or_die()

# The drops-root gate (story 2.1a). Unlike MM_CONTENT_ROOT — which the api only
# reads and the worker creates — every stored drop path is *relative* to this
# root, so without it intake cannot convert a posted path, the augmentation
# door cannot re-read a target drop, and replay cannot find a recording. That
# is a named startup failure, not three different first-use ones.
try:
    require_drops_root(CONFIG)
except ConfigError as exc:
    print(f"fatal: api startup aborted: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc

# The publish-root gate (story 4.3). Unlike the two roots above, the api both
# creates and writes into this location: `POST /moments/{moment_id}/approve`
# exports every approved artifact here and, for ADRs, commits it to a git
# repository rooted here. A folder that is unset, uncreatable, or read-only
# must fail startup, not the first publish gesture a human makes.
try:
    PUBLISH_ROOT = require_publish_root(CONFIG)
except ConfigError as exc:
    print(f"fatal: api startup aborted: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc

# Imported after the config gate on purpose: the source-drop schema is
# anchored to the config we just loaded, so a broken config must surface as
# the config error, not a schema-path error.
from meetingminer.adapters.embed import (  # noqa: E402
    EmbedderError,
    build_embedder,
)
# Only the two startup gates are imported by name: `ingests` for the drop
# schema, `problems` for exception handlers (handlers, not a router — it must
# not be swept into discovery). Route registration is discovered, below.
from meetingminer.api import (  # noqa: E402
    ingests,
    problems,
)
from meetingminer.api.registry import register_routers  # noqa: E402

# Fail-fast on an unreadable/invalid drop schema at startup, not at first use.
ingests.load_drop_schema(CONFIG)

# The `Embedder` binding, resolved once (AD-8). Constructing it contacts no
# host — it only reads `embedder.model`/`dimension` and the provider endpoint
# from config.yaml — so a failure here is a *config* error and belongs with
# the other startup gates. A host that is merely down surfaces later, from the
# port, as EmbedderUnavailableError, and `/search` degrades to keyword-only
# rather than failing.
try:
    EMBEDDER = build_embedder(CONFIG, logs.log_event)
except EmbedderError as exc:
    print(f"fatal: api startup aborted: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the Postgres pool; refuse to boot on pending migrations.

    Failure exits via os._exit(1) after printing the named error: raising
    inside a lifespan would make the server print a traceback, breaking the
    fail-fast contract (named error, no traceback).
    """
    pool = db.create_pool(CONFIG)
    try:
        pool.open(wait=True, timeout=10.0)
        with pool.connection() as conn:
            db.check_migrations_current(conn)
    except (db.MigrationsPendingError, db.MigrationError, psycopg.Error) as exc:
        print(f"fatal: api startup aborted: {exc}", file=sys.stderr)
        sys.stderr.flush()
        try:
            pool.close()
        finally:
            os._exit(1)
    app.state.pool = pool
    try:
        yield
    finally:
        pool.close()


app = FastAPI(title="MeetingMiner API", version="0.1.0", lifespan=lifespan)
problems.register_handlers(app)
# Routes reach configuration through the app rather than by importing this
# module (which would be circular): the job-event stream reads its poll and
# heartbeat intervals from here.
app.state.config = CONFIG
# Same reasoning: `/search` reaches the embedder through the app rather than
# by importing this module.
app.state.embedder = EMBEDDER
# Same reasoning again: the approve route reaches the validated publish
# folder through the app rather than importing this module.
app.state.publish_root = PUBLISH_ROOT

# The Vite dev server (:5173) calls the api directly during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every module in `meetingminer.api` exposing an `APIRouter` is discovered
# and registered here (story 2.8) — adding an endpoint is adding a file, not
# editing this one. The registration-order contracts that used to live as
# comments on this block (events before jobs; media registered whole) are
# documented in registry.py and asserted by tests/test_api_registry.py.
register_routers(app)


class HealthResponse(BaseModel):
    """Config-derived service identity (serialized camelCase at the API boundary)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    status: str
    service: str
    config_version: int


@app.get("/health", response_model=HealthResponse, operation_id="getHealth")
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=f"{CONFIG.settings.service}-api",
        config_version=CONFIG.settings.config_version,
    )
