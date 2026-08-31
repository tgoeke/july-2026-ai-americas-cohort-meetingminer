"""The one rule for which binding an LLM role is actually served by (story 8.2).

``config.yaml`` declares, per role, the ``catalog[]`` a user may choose from and
the ``default`` chosen when nothing else says (story 8.1, AD-10, FR38). A user's
pick is data, not configuration: it lives in the api-owned ``app_setting`` table
and is resolved at call time — by chat on every request, by the worker on every
job — so a change takes effect without editing a tracked file or restarting a
process.

This module is that resolution, and it lives in ``domain`` for the reason
``domain/jobs.py`` gives: the api (which never imports ``pipeline``) and the
worker (which never imports ``api``) both need it, and neither may own it.
Provider identity is **not** re-derived here — it comes from
:func:`~meetingminer.domain.model_providers.provider_for_model`, the single
dependency-neutral spelling rule that config, runtime routing and the status
surface already share. A second table of prefixes in this file is exactly the
drift story 8.1 removed.

Two rules do the work, and they are deliberately the same rule applied twice:

* **On write**, a selection naming a binding outside its role's catalog is
  refused (:func:`check_selectable`), so the boundary the file declares is the
  boundary the store holds.
* **On read**, the stored selection is checked again (:func:`resolve`), because
  ``config.yaml`` is edited independently of the database and a catalog can
  lose an entry after a row was written. A selection that is no longer offered
  is **not applied** — the role falls back to the file's own ``default`` — and
  it is **not hidden**: the discarded binding and the reason travel back on
  :class:`EffectiveBinding` so the api payload and the caller's log can name it.

That read-time discard is not the silent fallback this project rejects. The
rejected behaviour is answering from a *different model* after the selected one
failed at call time (see
:class:`~meetingminer.adapters.llm.port.LlmModelNotServedError`); here the file
withdrew the choice before any call was made, and the withdrawal is reported
wherever the choice is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal, Protocol, Sequence

from meetingminer.domain.model_providers import provider_for_model

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime driver import
    from psycopg import Connection

__all__ = [
    "EffectiveBinding",
    "SelectionNotInCatalogError",
    "bind",
    "catalog_bindings",
    "check_selectable",
    "log_stale_selection",
    "read_selection",
    "read_selections",
    "resolve",
    "resolve_role",
    "selection_key",
    "write_selection",
]

#: How a role's selection is spelled in ``app_setting``. Namespaced so the
#: table can hold settings of other kinds without a key collision, and stable:
#: changing it would orphan every stored choice, which reads to a user as their
#: selection silently reverting.
KEY_TEMPLATE = "llm.role.{role}.binding"

#: Where the effective binding came from. ``file-default`` covers both "nobody
#: has chosen" and "the choice is no longer offered" — the two are told apart by
#: :attr:`EffectiveBinding.stale_selection`, never by this field.
BindingSource = Literal["selection", "file-default"]


class RoleBinding(Protocol):
    """Structural stand-in for :class:`meetingminer.config.LlmRoleBinding`.

    Typed structurally, like ``adapters/llm``'s own ``RoleBinding``: this module
    stays free of imports from layers above it, and a test can hand it any
    object carrying these three members.
    """

    model: str
    default: str | None
    catalog: Sequence[Any]


class SelectionNotInCatalogError(ValueError):
    """A selection named a binding the role's catalog does not offer.

    Raised by :func:`check_selectable` on the write path. The api turns it into
    the refusal a client reads; the message names the role, the rejected
    binding, and every binding that *would* be accepted, because a refusal that
    does not say what is legal makes the caller guess.
    """

    def __init__(self, role: str, binding: str, offered: Sequence[str]) -> None:
        self.role = role
        self.binding = binding
        self.offered = tuple(offered)
        declared = ", ".join(repr(item) for item in offered) or "no bindings at all"
        super().__init__(
            f"binding {binding!r} is not in the {role!r} role's catalog, which"
            f" offers {declared} — a selection may only name a binding"
            " `config.yaml` declares for that role"
        )


@dataclass(frozen=True)
class EffectiveBinding:
    """Which model a role will actually call, and why that one.

    Everything a surface needs to explain the answer without re-deriving it:
    the binding in force, its provider, whether it came from the user or the
    file, what the file says on its own, and — when a stored choice was
    discarded — which one and why.
    """

    role: str
    #: The binding the next call will use.
    binding: str
    #: Derived by the shared spelling rule; ``None`` only for a spelling that
    #: rule cannot identify, which the loader already refuses.
    provider: str | None
    source: BindingSource
    #: The role's ``default`` (equal to ``model`` for a file that declares
    #: neither a catalog nor a default), and the role's still-declared
    #: ``model``. Both travel so the eval snapshot can record the effective
    #: binding *beside* the file value rather than in place of it.
    default_binding: str
    file_model: str
    #: What is stored for this role, whether or not it is still selectable.
    selected: str | None
    #: Set only when a stored selection was discarded on read.
    stale_selection: str | None = None
    stale_reason: str | None = None


def selection_key(role: str) -> str:
    """The ``app_setting`` key holding this role's selected binding."""
    return KEY_TEMPLATE.format(role=role)


def catalog_bindings(role_binding: RoleBinding) -> tuple[str, ...]:
    """Every binding this role's catalog offers, in the file's own order."""
    return tuple(entry.binding for entry in role_binding.catalog)


def check_selectable(role: str, binding: str, role_binding: RoleBinding) -> None:
    """Raise :class:`SelectionNotInCatalogError` unless the catalog offers ``binding``."""
    offered = catalog_bindings(role_binding)
    if binding not in offered:
        raise SelectionNotInCatalogError(role, binding, offered)


def resolve(
    role: str, role_binding: RoleBinding, selected: str | None
) -> EffectiveBinding:
    """Which binding ``role`` is served by, given whatever is stored for it.

    ``selected`` is the raw stored value — this function is where it is judged,
    so no caller can skip the re-check by reading the store directly and using
    what it found.
    """
    # `default` is populated by the loader for every file (it falls back to
    # `model`), but the annotation allows `None` and a structurally-typed
    # stand-in may leave it unset; fall back the same way rather than resolving
    # a role to `None`.
    default = role_binding.default or role_binding.model
    offered = catalog_bindings(role_binding)

    if selected is None:
        return EffectiveBinding(
            role=role,
            binding=default,
            provider=provider_for_model(default),
            source="file-default",
            default_binding=default,
            file_model=role_binding.model,
            selected=None,
        )

    if selected not in offered:
        declared = ", ".join(repr(item) for item in offered) or "no bindings at all"
        return EffectiveBinding(
            role=role,
            binding=default,
            provider=provider_for_model(default),
            source="file-default",
            default_binding=default,
            file_model=role_binding.model,
            selected=selected,
            stale_selection=selected,
            stale_reason=(
                f"the stored selection {selected!r} is no longer in the"
                f" {role!r} role's catalog, which now offers {declared};"
                f" `config.yaml`'s default {default!r} is in effect until a"
                " binding the catalog offers is selected"
            ),
        )

    return EffectiveBinding(
        role=role,
        binding=selected,
        provider=provider_for_model(selected),
        source="selection",
        default_binding=default,
        file_model=role_binding.model,
        selected=selected,
    )


def bind(role_binding: Any, effective: EffectiveBinding) -> Any:
    """A copy of ``role_binding`` whose active model is the effective binding.

    Only ``model`` changes. ``base_url``, ``fallback``, ``timeout_seconds`` and
    ``num_ctx`` are the *role's* call settings, and a selection replaces the
    role's primary model rather than the role: dropping ``base_url`` would move
    the call to ``providers.<prefix>.base_url`` — a different host — without
    anything saying so, which is the class of quiet re-routing this story
    exists to remove. When the role's endpoint does not serve the selected
    model, that now fails by name at call time
    (:class:`~meetingminer.adapters.llm.port.LlmModelNotServedError`) instead of
    being answered by the fallback.

    The configured object is never mutated: it is process-wide state shared by
    every request, and one request's selection must not become another's.
    """
    return role_binding.model_copy(update={"model": effective.binding})


# --- the store: read-only for the worker, written only by the api -----------

_SELECT_ONE = "SELECT value FROM app_setting WHERE key = %s"
_SELECT_MANY = "SELECT key, value FROM app_setting WHERE key LIKE 'llm.role.%%'"
_UPSERT = (
    "INSERT INTO app_setting (key, value) VALUES (%s, %s)"
    " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
)


def read_selection(conn: "Connection", role: str) -> str | None:
    """The binding stored for ``role``, or ``None`` when nobody has chosen one."""
    row = conn.execute(_SELECT_ONE, (selection_key(role),)).fetchone()
    return None if row is None else str(row[0])


def read_selections(conn: "Connection", roles: Sequence[str]) -> dict[str, str]:
    """Every stored role selection, keyed by role — one round trip for a listing."""
    stored = {
        str(key): str(value) for key, value in conn.execute(_SELECT_MANY).fetchall()
    }
    return {
        role: stored[selection_key(role)]
        for role in roles
        if selection_key(role) in stored
    }


def write_selection(conn: "Connection", role: str, binding: str) -> None:
    """Persist ``binding`` as ``role``'s selection. Api-only (AD-5)."""
    conn.execute(_UPSERT, (selection_key(role), binding))


def log_stale_selection(
    effective: EffectiveBinding, log: Callable[..., None] | None
) -> None:
    """Name a discarded stored selection with one event shape everywhere."""
    if log is None or effective.stale_selection is None:
        return
    log(
        "llm.selection_stale",
        role=effective.role,
        stale_selection=effective.stale_selection,
        effective_binding=effective.binding,
        reason=effective.stale_reason,
    )


def resolve_role(
    conn: "Connection",
    role: str,
    role_binding: Any,
    log: Callable[..., None] | None = None,
) -> tuple[Any, EffectiveBinding]:
    """Read this role's selection and return the binding to call, plus the why.

    The one function chat (per request) and the worker (per job) both call, so
    the two resolution points cannot drift. A discarded stale selection is
    logged here rather than at each call site, for the same reason.
    """
    effective = resolve(role, role_binding, read_selection(conn, role))
    log_stale_selection(effective, log)
    return bind(role_binding, effective), effective
