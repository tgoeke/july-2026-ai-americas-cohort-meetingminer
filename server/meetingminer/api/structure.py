"""POST/GET /series|/products|/projects, PATCH /projects/{id},
PUT /meetings/{id}/series|project (story 2.5).

AD-5's user-declared structure: "The API writes user-declared data (series
membership, project/product assignment)." All five tables this router writes
(`series`, `product`, `project`, `meeting_series`, `meeting_project`) are
API-owned end to end — the worker never reads or writes them, and no
worker-owned table gained a column. Membership is declared row by row by a
human (FR25): no inference, no bulk auto-assignment, no name matching.

The at-most-one cardinality the ERD draws (`MEETING }o--o| SERIES`,
`PROJECT ||--o{ MEETING`) is enforced by schema, not code: `meeting_series`
and `meeting_project` key on `meeting_id`, so assignment is an upsert and
`null` clears via DELETE of the row.

No Neo4j write happens here (AD-4/AD-5,
`test_the_api_package_never_reaches_a_store`): an assignment reaches the
graph's `Series`/`Project`/`Product` nodes only at the next projection run or
`rebuild` (`projections/graph.py:_write_structure`) — the same documented lag
as participant renames.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

import psycopg.errors
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from pydantic.alias_generators import to_camel

from meetingminer import logs
from meetingminer.api.problems import Problem

router = APIRouter()

# Same idiom as `participants.py`'s DisplayName: an entity name is a sentence
# fragment, not free text, and `strip_whitespace` before `min_length` is what
# makes a whitespace-only name a 422 rather than a blank row.
NAME_MAX_LENGTH = 200
EntityName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH),
]

# Each series/project row in a list carries the ids of its assigned meetings,
# ordered by when the meeting happened (then id, for a stable order between
# meetings sharing a start). Aggregated in SQL so a list is one statement,
# not one query per row.
_LIST_SERIES = (
    "SELECT s.id, s.name, s.created_at, s.updated_at,"
    " coalesce(array_agg(m.id ORDER BY m.started_at, m.id)"
    "          FILTER (WHERE m.id IS NOT NULL), '{}') AS meeting_ids"
    " FROM series s"
    " LEFT JOIN meeting_series ms ON ms.series_id = s.id"
    " LEFT JOIN meeting m ON m.id = ms.meeting_id"
    " GROUP BY s.id ORDER BY s.name, s.id"
)

_LIST_PRODUCTS = (
    "SELECT id, name, created_at, updated_at FROM product ORDER BY name, id"
)

_LIST_PROJECTS = (
    "SELECT p.id, p.name, p.product_id, p.created_at, p.updated_at,"
    " coalesce(array_agg(m.id ORDER BY m.started_at, m.id)"
    "          FILTER (WHERE m.id IS NOT NULL), '{}') AS meeting_ids"
    " FROM project p"
    " LEFT JOIN meeting_project mp ON mp.project_id = p.id"
    " LEFT JOIN meeting m ON m.id = mp.meeting_id"
    " GROUP BY p.id ORDER BY p.name, p.id"
)

# The assignment upsert: `meeting_id` is the primary key, so a re-assignment
# replaces the single row instead of accumulating a second membership — the
# schema shape is what enforces the ERD's at-most-one.
_UPSERT_MEETING_SERIES = (
    "INSERT INTO meeting_series (meeting_id, series_id) VALUES (%s, %s)"
    " ON CONFLICT (meeting_id) DO UPDATE SET series_id = EXCLUDED.series_id"
)
_CLEAR_MEETING_SERIES = "DELETE FROM meeting_series WHERE meeting_id = %s"
_UPSERT_MEETING_PROJECT = (
    "INSERT INTO meeting_project (meeting_id, project_id) VALUES (%s, %s)"
    " ON CONFLICT (meeting_id) DO UPDATE SET project_id = EXCLUDED.project_id"
)
_CLEAR_MEETING_PROJECT = "DELETE FROM meeting_project WHERE meeting_id = %s"


class SeriesRow(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class SeriesListRow(SeriesRow):
    """A series plus its assigned meetings, ordered by meeting start."""

    meeting_ids: list[UUID]


class ProductRow(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class ProjectRow(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: UUID
    name: str
    product_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ProjectListRow(ProjectRow):
    """A project plus its assigned meetings, ordered by meeting start."""

    meeting_ids: list[UUID]


class CreateNamedEntityRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: EntityName

    @field_validator("name")
    @classmethod
    def name_cannot_contain_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("name cannot contain a NUL character")
        return value


class CreateProjectRequest(CreateNamedEntityRequest):
    product_id: UUID | None = None


class AssignProjectProductRequest(BaseModel):
    """`productId` is required but nullable: `null` clears the assignment."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    product_id: UUID | None


class AssignMeetingSeriesRequest(BaseModel):
    """`seriesId` is required but nullable: `null` clears the assignment."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    series_id: UUID | None


class AssignMeetingProjectRequest(BaseModel):
    """`projectId` is required but nullable: `null` clears the assignment."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    project_id: UUID | None


class MeetingSeriesAssignment(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    meeting_id: UUID
    series_id: UUID | None


class MeetingProjectAssignment(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    meeting_id: UUID
    project_id: UUID | None


# One body per status, assembled into per-route subsets by
# `_problem_responses` below. A single dict attached to every route would
# advertise impossible errors in OpenAPI — a 404 on `createSeries`, a 409
# `name-taken` on the assignment PUTs — and the generated client's error
# typing follows what is declared here.
_PROBLEM_BODIES = {
    422: {
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`invalid-request` — a route parameter or body id is"
        " not a UUID, a required field is absent, or the entity name is"
        " blank, longer than 200 characters, or contains a NUL character.",
    },
    404: {
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`not-found` — no such meeting, series, project, or"
        " product row.",
    },
    409: {
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
        "description": "`name-taken` — another row of the same entity type"
        " already carries this name (names are UNIQUE per type).",
    },
}


def _problem_responses(*statuses: int) -> dict:
    return {status: _PROBLEM_BODIES[status] for status in statuses}


# `createSeries`/`createProduct` can only refuse a bad name; `createProject`
# can additionally miss its `productId`; the assignment routes reference
# existing rows by id and never mint a name.
_CREATE_RESPONSES = _problem_responses(409, 422)
_CREATE_PROJECT_RESPONSES = _problem_responses(404, 409, 422)
_ASSIGN_RESPONSES = _problem_responses(404, 422)


def _require_exists(conn, table: str, entity_id: UUID) -> None:
    """404 by name when a referenced row is absent.

    `table` is always one of this module's own literals, never input — the
    f-string interpolates an identifier the route chose, not the client.
    """
    row = conn.execute(f"SELECT 1 FROM {table} WHERE id = %s", (entity_id,)).fetchone()
    if row is None:
        raise Problem(404, "not-found", f"no {table} with id {entity_id}")


def _create_named(conn, table: str, name: str):
    """INSERT one named entity row; a duplicate name is a 409 `name-taken`.

    The UNIQUE constraint is the arbiter, not a pre-check: two concurrent
    creates of the same name race to the index and the loser refuses cleanly.
    """
    try:
        return conn.execute(
            f"INSERT INTO {table} (name) VALUES (%s)"
            " RETURNING id, name, created_at, updated_at",
            (name,),
        ).fetchone()
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        raise Problem(
            409, "name-taken", f"a {table} named {name!r} already exists"
        ) from None


@router.post(
    "/series",
    operation_id="createSeries",
    status_code=201,
    response_model=SeriesRow,
    responses=_CREATE_RESPONSES,
)
def create_series(body: CreateNamedEntityRequest, request: Request) -> SeriesRow:
    pool = request.app.state.pool
    with pool.connection() as conn:
        row = _create_named(conn, "series", body.name)
    logs.log_event("structure.series_created", series_id=row[0])
    return SeriesRow(id=row[0], name=row[1], created_at=row[2], updated_at=row[3])


@router.get(
    "/series",
    operation_id="listSeries",
    response_model=list[SeriesListRow],
)
def list_series(request: Request) -> list[SeriesListRow]:
    pool = request.app.state.pool
    with pool.connection() as conn:
        rows = conn.execute(_LIST_SERIES).fetchall()
    result = [
        SeriesListRow(
            id=r[0], name=r[1], created_at=r[2], updated_at=r[3], meeting_ids=r[4]
        )
        for r in rows
    ]
    logs.log_event("structure.series_listed", series=len(result))
    return result


@router.post(
    "/products",
    operation_id="createProduct",
    status_code=201,
    response_model=ProductRow,
    responses=_CREATE_RESPONSES,
)
def create_product(body: CreateNamedEntityRequest, request: Request) -> ProductRow:
    pool = request.app.state.pool
    with pool.connection() as conn:
        row = _create_named(conn, "product", body.name)
    logs.log_event("structure.product_created", product_id=row[0])
    return ProductRow(id=row[0], name=row[1], created_at=row[2], updated_at=row[3])


@router.get(
    "/products",
    operation_id="listProducts",
    response_model=list[ProductRow],
)
def list_products(request: Request) -> list[ProductRow]:
    pool = request.app.state.pool
    with pool.connection() as conn:
        rows = conn.execute(_LIST_PRODUCTS).fetchall()
    result = [
        ProductRow(id=r[0], name=r[1], created_at=r[2], updated_at=r[3]) for r in rows
    ]
    logs.log_event("structure.products_listed", products=len(result))
    return result


@router.post(
    "/projects",
    operation_id="createProject",
    status_code=201,
    response_model=ProjectRow,
    responses=_CREATE_PROJECT_RESPONSES,
)
def create_project(body: CreateProjectRequest, request: Request) -> ProjectRow:
    pool = request.app.state.pool
    with pool.connection() as conn:
        if body.product_id is not None:
            _require_exists(conn, "product", body.product_id)
        try:
            row = conn.execute(
                "INSERT INTO project (name, product_id) VALUES (%s, %s)"
                " RETURNING id, name, product_id, created_at, updated_at",
                (body.name, body.product_id),
            ).fetchone()
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            raise Problem(
                409, "name-taken", f"a project named {body.name!r} already exists"
            ) from None
        except psycopg.errors.ForeignKeyViolation:
            # Lost a race with a concurrent product deletion path (none exists
            # today, but the refusal is cheap and named rather than a 500).
            conn.rollback()
            raise Problem(
                404, "not-found", f"no product with id {body.product_id}"
            ) from None
    logs.log_event("structure.project_created", project_id=row[0])
    return ProjectRow(
        id=row[0], name=row[1], product_id=row[2], created_at=row[3], updated_at=row[4]
    )


@router.patch(
    "/projects/{project_id}",
    operation_id="assignProjectProduct",
    response_model=ProjectRow,
    responses=_ASSIGN_RESPONSES,
)
def assign_project_product(
    project_id: UUID, body: AssignProjectProductRequest, request: Request
) -> ProjectRow:
    """Assign a project to a product, or clear it (`productId: null`).

    `PRODUCT ||--o{ PROJECT`: the assignment is a single nullable column on
    the project row, so this is an UPDATE, never a second row.
    """
    pool = request.app.state.pool
    with pool.connection() as conn:
        _require_exists(conn, "project", project_id)
        if body.product_id is not None:
            _require_exists(conn, "product", body.product_id)
        try:
            row = conn.execute(
                "UPDATE project SET product_id = %s WHERE id = %s"
                " RETURNING id, name, product_id, created_at, updated_at",
                (body.product_id, project_id),
            ).fetchone()
        except psycopg.errors.ForeignKeyViolation:
            # The product vanished between the check and the UPDATE (no
            # deletion path exists today, but the refusal is cheap and named
            # rather than a 500).
            conn.rollback()
            raise Problem(
                404, "not-found", f"no product with id {body.product_id}"
            ) from None
        if row is None:
            # The project vanished between the check and the UPDATE.
            raise Problem(404, "not-found", f"no project with id {project_id}")
    logs.log_event(
        "structure.project_product_assigned",
        project_id=project_id,
        product_id=body.product_id,
    )
    return ProjectRow(
        id=row[0], name=row[1], product_id=row[2], created_at=row[3], updated_at=row[4]
    )


@router.get(
    "/projects",
    operation_id="listProjects",
    response_model=list[ProjectListRow],
)
def list_projects(request: Request) -> list[ProjectListRow]:
    pool = request.app.state.pool
    with pool.connection() as conn:
        rows = conn.execute(_LIST_PROJECTS).fetchall()
    result = [
        ProjectListRow(
            id=r[0],
            name=r[1],
            product_id=r[2],
            created_at=r[3],
            updated_at=r[4],
            meeting_ids=r[5],
        )
        for r in rows
    ]
    logs.log_event("structure.projects_listed", projects=len(result))
    return result


@router.put(
    "/meetings/{meeting_id}/series",
    operation_id="assignMeetingSeries",
    response_model=MeetingSeriesAssignment,
    responses=_ASSIGN_RESPONSES,
)
def assign_meeting_series(
    meeting_id: UUID, body: AssignMeetingSeriesRequest, request: Request
) -> MeetingSeriesAssignment:
    """Declare (or clear) which series this meeting belongs to.

    PUT with a nullable id: membership is a single-valued property of the
    meeting, so PUT replaces it idempotently and `null` clears it — no second
    DELETE route per relation. The `meeting_series` PRIMARY KEY makes the
    replace an upsert of one row.
    """
    pool = request.app.state.pool
    with pool.connection() as conn:
        _require_exists(conn, "meeting", meeting_id)
        if body.series_id is None:
            conn.execute(_CLEAR_MEETING_SERIES, (meeting_id,))
        else:
            _require_exists(conn, "series", body.series_id)
            try:
                conn.execute(_UPSERT_MEETING_SERIES, (meeting_id, body.series_id))
            except psycopg.errors.ForeignKeyViolation:
                # A referenced row vanished between the checks and the INSERT
                # — same named refusal as `create_project`'s, never a 500.
                conn.rollback()
                raise Problem(
                    404,
                    "not-found",
                    f"meeting {meeting_id} or series {body.series_id} no"
                    " longer exists",
                ) from None
    logs.log_event(
        "structure.meeting_series_assigned",
        meeting_id=meeting_id,
        series_id=body.series_id,
    )
    return MeetingSeriesAssignment(meeting_id=meeting_id, series_id=body.series_id)


@router.put(
    "/meetings/{meeting_id}/project",
    operation_id="assignMeetingProject",
    response_model=MeetingProjectAssignment,
    responses=_ASSIGN_RESPONSES,
)
def assign_meeting_project(
    meeting_id: UUID, body: AssignMeetingProjectRequest, request: Request
) -> MeetingProjectAssignment:
    """Declare (or clear) which project scopes this meeting.

    Same PUT-with-nullable-id shape as the series assignment above.
    """
    pool = request.app.state.pool
    with pool.connection() as conn:
        _require_exists(conn, "meeting", meeting_id)
        if body.project_id is None:
            conn.execute(_CLEAR_MEETING_PROJECT, (meeting_id,))
        else:
            _require_exists(conn, "project", body.project_id)
            try:
                conn.execute(_UPSERT_MEETING_PROJECT, (meeting_id, body.project_id))
            except psycopg.errors.ForeignKeyViolation:
                # Same race guard as the series assignment above.
                conn.rollback()
                raise Problem(
                    404,
                    "not-found",
                    f"meeting {meeting_id} or project {body.project_id} no"
                    " longer exists",
                ) from None
    logs.log_event(
        "structure.meeting_project_assigned",
        meeting_id=meeting_id,
        project_id=body.project_id,
    )
    return MeetingProjectAssignment(meeting_id=meeting_id, project_id=body.project_id)
