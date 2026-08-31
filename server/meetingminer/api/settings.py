"""The model-selection surface: serve each role's catalog, persist a choice (story 8.2).

Story 8.1 made ``config.yaml`` declare, per LLM role, the ``catalog[]`` a user
may choose from and the ``default`` among them — and nothing served it, so the
declaration existed only in the file (AD-10, FR38). These two routes close that:

* ``GET /settings/models`` serves every role's catalog together with the binding
  actually in force and where it came from.
* ``PUT /settings/roles/{role}`` persists a choice, refusing any binding the
  role's catalog does not offer.

The catalog is read from the running configuration on every request and the
selection from Postgres on every request; neither is cached. A config edit is
visible as soon as a fresh process reads the file, and a selection change is
visible on the next call — the same "no separate publish step" property
``api/extraction.py`` records for the prompts.

**This module writes ``app_setting`` and nothing else writes it** (AD-5): the
worker only reads it, when it resolves a role for a job. The membership rule,
the resolution, and the store access all live in
:mod:`meetingminer.domain.model_selection`, so this router decides no policy —
it maps one domain refusal onto one RFC 9457 problem and serializes the result.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, StringConstraints
from pydantic.alias_generators import to_camel

from meetingminer import logs
from meetingminer.api.problems import Problem
from meetingminer.domain import model_selection

router = APIRouter()

# A binding is a model tag, not prose: stripped, non-empty, and short enough
# that a pasted document cannot become a settings row. The longest tag in any
# shipped catalog is far under this.
SelectedBinding = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class CatalogEntryView(BaseModel):
    """One binding a role may be served by, as a picker renders it."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    binding: str
    label: str
    #: Derived by the one shared spelling rule (`domain/model_providers.py`),
    #: never authored — so a picker cannot display a provider the call would
    #: not use. `None` only for a spelling that rule cannot identify, which the
    #: loader already refuses.
    provider: str | None


class RoleSelectionView(BaseModel):
    """One role's catalog, the binding in force, and how it was arrived at."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    role: str
    catalog: list[CatalogEntryView]
    #: What `config.yaml` says on its own: the role's `default`, and the
    #: still-declared `model`. Served *beside* the effective binding rather
    #: than replaced by it, so a reader can always see both halves.
    default: str
    file_model: str
    #: What is stored for this role, whether or not it is still selectable.
    selected: str | None
    effective_binding: str
    provider: str | None
    #: `"selection"` or `"file-default"`. A stale selection reads as
    #: `"file-default"` with `staleSelection` set — the two are told apart
    #: there, never by this field alone.
    source: str
    stale_selection: str | None
    stale_reason: str | None


class ModelSettingsResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    roles: list[RoleSelectionView]


class RoleSelectionRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    binding: SelectedBinding


def _role_names(config: Any) -> tuple[str, ...]:
    """Every LLM role, taken from the config model rather than a list here.

    A second list of role names would drift the first time a role is added,
    and would do it quietly: the new role would simply be missing from this
    surface while `config.yaml` happily declared its catalog.
    """
    return tuple(type(config.settings.llm.roles).model_fields)


def _binding_for(config: Any, role: str) -> Any:
    return getattr(config.settings.llm.roles, role)


def _require_role(config: Any, role: str) -> Any:
    known = _role_names(config)
    if role not in known:
        raise Problem(
            404,
            "unknown-role",
            f"there is no LLM role named {role!r}; `config.yaml` declares"
            f" {', '.join(repr(name) for name in known)}",
        )
    return _binding_for(config, role)


def _view(role: str, role_binding: Any, selected: str | None) -> RoleSelectionView:
    effective = model_selection.resolve(role, role_binding, selected)
    return RoleSelectionView(
        role=role,
        catalog=[
            CatalogEntryView(
                binding=entry.binding,
                # `label` is filled in from `binding` by the loader, so it is
                # never None here; the fallback keeps a hand-built binding
                # displayable rather than serializing null into a picker.
                label=entry.label or entry.binding,
                provider=entry.provider,
            )
            for entry in role_binding.catalog
        ],
        default=effective.default_binding,
        file_model=effective.file_model,
        selected=effective.selected,
        effective_binding=effective.binding,
        provider=effective.provider,
        source=effective.source,
        stale_selection=effective.stale_selection,
        stale_reason=effective.stale_reason,
    )


@router.get(
    "/settings/models",
    operation_id="getModelSettings",
    response_model=ModelSettingsResponse,
)
def get_model_settings(request: Request) -> ModelSettingsResponse:
    """Every role's catalog with the binding actually in force."""
    config = request.app.state.config
    roles = _role_names(config)
    with request.app.state.pool.connection() as conn:
        stored = model_selection.read_selections(conn, roles)
    return ModelSettingsResponse(
        roles=[
            _view(role, _binding_for(config, role), stored.get(role))
            for role in roles
        ]
    )


@router.put(
    "/settings/roles/{role}",
    operation_id="selectRoleBinding",
    response_model=RoleSelectionView,
    responses={
        404: {
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                }
            },
            "description": "`unknown-role` — no LLM role has that name.",
        },
        422: {
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                }
            },
            "description": "`binding-not-in-catalog` — the role exists but"
            " its catalog does not offer the requested binding."
            " `invalid-request` — the request body failed validation.",
        },
    },
)
def select_role_binding(
    request: Request, role: str, body: RoleSelectionRequest
) -> RoleSelectionView:
    """Persist ``role``'s binding choice, bounded by that role's catalog."""
    config = request.app.state.config
    role_binding = _require_role(config, role)

    try:
        model_selection.check_selectable(role, body.binding, role_binding)
    except model_selection.SelectionNotInCatalogError as exc:
        # 422, not 404: the role exists and the request is well-formed; the
        # value it carries is the thing this api will not accept.
        raise Problem(
            422,
            "binding-not-in-catalog",
            str(exc),
            role=role,
            binding=body.binding,
            catalog=list(exc.offered),
        ) from exc

    with request.app.state.pool.connection() as conn:
        model_selection.write_selection(conn, role, body.binding)
    logs.log_event("llm.selection_written", role=role, binding=body.binding)

    # Re-resolved rather than assumed: the response says what the *next call*
    # will use, which is the same question `GET /settings/models` answers, and
    # it is answered by the same function.
    return _view(role, role_binding, body.binding)
