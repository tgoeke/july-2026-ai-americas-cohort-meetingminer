"""The `Embedder` port and its Ollama binding — pure units, no store, no model.

Mirrors `test_ocr_adapter.py`: the adapter is exercised directly rather than
through the projection module, because every projection test injects a
stand-in and a stand-in cannot get the thing that matters wrong.

**What matters here is the two-error split**, and it is load-bearing rather
than tidy. The whole structural/embedding design rests on it
(`retrieval-prior-art.md` §3 rule 4): an *unreachable* host must raise
:class:`EmbedderUnavailableError`, which leaves a structurally projected,
BM25-searchable meeting that a later pass resumes; anything else must raise
:class:`EmbedderError`, which is a configuration failure no retry fixes.
Collapsing the two ``except`` blocks in ``ollama.py`` would keep every other
suite green while turning a stopped Ollama into a failed ingest — so the split
is pinned here, against a real socket.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Iterator

import pytest

from meetingminer.adapters.embed import (
    EmbedderError,
    EmbedderUnavailableError,
    OllamaEmbedder,
    build_embedder,
)
from meetingminer.adapters.embed.port import check_dimension
from meetingminer.config import AppConfig

# A port nothing listens on: connecting fails immediately with a refusal,
# which is exactly the "Ollama is not running" case (same trick as
# test_migrations.py's unreachable Postgres).
DEAD_PORT = 1


# --- a local HTTP stub, so the transport is real ---------------------------


def _serve(handler: Callable[[dict[str, Any]], tuple[int, bytes]]) -> Iterator[str]:
    """Run a one-route HTTP server that answers /api/embed however told to."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            status, payload = handler(body)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args: Any) -> None:
            return  # keep the test output clean

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def ollama_stub() -> Callable[[Callable[[dict[str, Any]], tuple[int, bytes]]], Any]:
    """Factory: install a scripted /api/embed responder, get its base URL."""
    running: list[Iterator[str]] = []

    def _install(handler: Callable[[dict[str, Any]], tuple[int, bytes]]) -> str:
        generator = _serve(handler)
        running.append(generator)
        return next(generator)

    yield _install
    for generator in running:
        with pytest.raises(StopIteration):
            next(generator)


def ok_response(dimension: int = 8) -> Callable[[dict[str, Any]], tuple[int, bytes]]:
    def _handler(body: dict[str, Any]) -> tuple[int, bytes]:
        vectors = [[0.5] * dimension for _ in body["input"]]
        return 200, json.dumps({"embeddings": vectors}).encode()

    return _handler


# --- the happy path -------------------------------------------------------


def test_a_batch_comes_back_in_input_order_as_tuples(ollama_stub: Any) -> None:
    def _handler(body: dict[str, Any]) -> tuple[int, bytes]:
        # One distinguishable vector per input, so order is actually checked.
        vectors = [[float(index)] * 4 for index, _ in enumerate(body["input"])]
        return 200, json.dumps({"embeddings": vectors}).encode()

    embedder = OllamaEmbedder(ollama_stub(_handler), "test-model", 4)
    vectors = embedder.embed_documents(["first", "second", "third"])
    assert vectors == ((0.0,) * 4, (1.0,) * 4, (2.0,) * 4)
    # Tuples, not lists: a vector is a value nothing downstream may mutate.
    assert all(isinstance(vector, tuple) for vector in vectors)


def test_an_empty_batch_never_reaches_the_host(ollama_stub: Any) -> None:
    def _handler(_body: dict[str, Any]) -> tuple[int, bytes]:  # pragma: no cover
        raise AssertionError("an empty batch must not be sent")

    embedder = OllamaEmbedder(ollama_stub(_handler), "test-model", 4)
    assert embedder.embed_documents([]) == ()


def test_embed_query_is_one_document(ollama_stub: Any) -> None:
    embedder = OllamaEmbedder(ollama_stub(ok_response(4)), "test-model", 4)
    assert embedder.embed_query("what did we decide") == (0.5, 0.5, 0.5, 0.5)


def test_the_configured_model_is_what_is_asked_for(ollama_stub: Any) -> None:
    seen: list[dict[str, Any]] = []

    def _handler(body: dict[str, Any]) -> tuple[int, bytes]:
        seen.append(body)
        return 200, json.dumps({"embeddings": [[0.1] * 4]}).encode()

    OllamaEmbedder(ollama_stub(_handler), "qwen3-embedding:0.6b", 4).embed_query("hi")
    assert seen == [{"model": "qwen3-embedding:0.6b", "input": ["hi"]}]


# --- unreachable: the failure the structural pass must survive -------------


def test_a_refused_connection_is_unavailable_not_fatal() -> None:
    embedder = OllamaEmbedder(f"http://127.0.0.1:{DEAD_PORT}", "test-model", 4)
    with pytest.raises(EmbedderUnavailableError) as excinfo:
        embedder.embed_documents(["anything"])
    # The message has to tell an operator what to do, not only that it failed.
    assert "unreachable" in str(excinfo.value)
    assert "rebuild --embed-only" in str(excinfo.value)


def test_an_unresolvable_host_is_unavailable_not_fatal() -> None:
    embedder = OllamaEmbedder("http://ollama.invalid.test:11434", "test-model", 4)
    with pytest.raises(EmbedderUnavailableError):
        embedder.embed_documents(["anything"])


def test_unavailable_is_a_subclass_so_a_broad_catch_still_sees_it() -> None:
    """The projection module catches the narrow case first, then the broad one."""
    assert issubclass(EmbedderUnavailableError, EmbedderError)


# --- answered, but not usably: the failure that must NOT be retried --------


def test_an_http_error_is_fatal_not_unavailable(ollama_stub: Any) -> None:
    """A model the host does not have. This is the exact 404 the shipped
    config produced before its model id was corrected — retrying never fixes it."""

    def _handler(_body: dict[str, Any]) -> tuple[int, bytes]:
        return 404, json.dumps({"error": 'model "nope" not found'}).encode()

    embedder = OllamaEmbedder(ollama_stub(_handler), "nope", 4)
    with pytest.raises(EmbedderError) as excinfo:
        embedder.embed_documents(["anything"])
    assert not isinstance(excinfo.value, EmbedderUnavailableError)
    message = str(excinfo.value)
    assert "404" in message and "not found" in message
    # The one failure an operator fixes in a single command, so the message is
    # that command. Nothing else in the repo states this prerequisite.
    assert "ollama pull nope" in message


def test_a_non_json_body_is_fatal(ollama_stub: Any) -> None:
    def _handler(_body: dict[str, Any]) -> tuple[int, bytes]:
        return 200, b"<html>not json</html>"

    embedder = OllamaEmbedder(ollama_stub(_handler), "test-model", 4)
    with pytest.raises(EmbedderError, match="not JSON"):
        embedder.embed_documents(["anything"])


def test_a_wrong_embedding_count_is_fatal(ollama_stub: Any) -> None:
    """Silently shifting vectors onto the wrong passages is worse than failing."""

    def _handler(_body: dict[str, Any]) -> tuple[int, bytes]:
        return 200, json.dumps({"embeddings": [[0.1] * 4]}).encode()

    embedder = OllamaEmbedder(ollama_stub(_handler), "test-model", 4)
    with pytest.raises(EmbedderError, match="1 embeddings for 3 inputs"):
        embedder.embed_documents(["a", "b", "c"])


def test_a_missing_embeddings_key_is_fatal(ollama_stub: Any) -> None:
    def _handler(_body: dict[str, Any]) -> tuple[int, bytes]:
        return 200, json.dumps({"data": []}).encode()

    embedder = OllamaEmbedder(ollama_stub(_handler), "test-model", 4)
    with pytest.raises(EmbedderError, match="no embeddings"):
        embedder.embed_documents(["a"])


def test_a_non_list_embedding_is_fatal(ollama_stub: Any) -> None:
    def _handler(_body: dict[str, Any]) -> tuple[int, bytes]:
        return 200, json.dumps({"embeddings": ["not-a-vector"]}).encode()

    embedder = OllamaEmbedder(ollama_stub(_handler), "test-model", 4)
    with pytest.raises(EmbedderError, match="non-list embedding"):
        embedder.embed_documents(["a"])


def test_a_non_numeric_component_is_fatal(ollama_stub: Any) -> None:
    def _handler(_body: dict[str, Any]) -> tuple[int, bytes]:
        return 200, json.dumps({"embeddings": [[0.1, "banana", 0.3, 0.4]]}).encode()

    embedder = OllamaEmbedder(ollama_stub(_handler), "test-model", 4)
    with pytest.raises(EmbedderError, match="non-numeric"):
        embedder.embed_documents(["a"])


def test_a_wrong_width_is_refused_before_it_reaches_a_store(ollama_stub: Any) -> None:
    """§3 rule 3 / AD-8: width is baked into the index, so a mismatch is caught."""
    embedder = OllamaEmbedder(ollama_stub(ok_response(768)), "test-model", 1024)
    with pytest.raises(EmbedderError) as excinfo:
        embedder.embed_documents(["a"])
    message = str(excinfo.value)
    assert "768" in message and "1024" in message
    assert "rebuild" in message


# --- the width check itself ------------------------------------------------


def test_check_dimension_accepts_a_matching_batch() -> None:
    check_dimension([[0.0] * 4, [1.0] * 4], 4, "test-model")


def test_check_dimension_names_the_offending_input() -> None:
    with pytest.raises(EmbedderError) as excinfo:
        check_dimension([[0.0] * 4, [1.0] * 3], 4, "test-model")
    assert "input 1" in str(excinfo.value)
    assert "test-model" in str(excinfo.value)


# --- the binding -----------------------------------------------------------


def test_build_embedder_binds_the_configured_model_and_width(
    app_config: AppConfig,
) -> None:
    embedder = build_embedder(app_config)
    assert embedder.model == app_config.settings.embedder.model
    assert embedder.dimension == app_config.settings.embedder.dimension
    assert embedder.base_url == app_config.settings.providers["ollama"].base_url


def test_build_embedder_logs_what_it_bound(app_config: AppConfig) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    build_embedder(app_config, lambda event, **fields: events.append((event, fields)))
    assert events[0][0] == "embedder.bound"
    assert events[0][1]["model"] == app_config.settings.embedder.model


def test_build_embedder_refuses_when_no_provider_serves_it(
    app_config: AppConfig,
) -> None:
    """A binding that cannot be *constructed* is a config error, distinct from
    a host that is merely down — only the second is survivable."""
    without_ollama = app_config.model_copy(deep=True)
    del without_ollama.settings.providers["ollama"]
    with pytest.raises(EmbedderError, match="providers.ollama"):
        build_embedder(without_ollama)


# --- the shipped binding ---------------------------------------------------


def test_the_shipped_config_names_a_model_the_local_host_can_serve() -> None:
    """The regression this exists for: ``embedder.model`` was ``qwen3-embedding``
    with no tag. Ollama resolves an untagged name to ``:latest``, no such tag
    exists, and every embedding pass 404'd — silently, because the structural
    half still succeeded. Nothing in the suite would have caught its return, so
    the shipped binding is asserted the way the OCR binding already is.

    Deliberately a *shape* assertion, not a live call: `make test` must not
    depend on Ollama running. What it pins is that the id is fully qualified.
    """
    from conftest import REPO_ROOT
    from meetingminer.config import load_config

    embedder = load_config(REPO_ROOT / "config.yaml", REPO_ROOT / ".env").settings.embedder
    assert ":" in embedder.model, (
        f"embedder.model {embedder.model!r} carries no tag — Ollama will resolve"
        " it to ':latest', which is not what is pulled on the host"
    )
    # AD-8 fixes the vector space at 1024; a change here forces a full rebuild.
    assert embedder.dimension == 1024


def test_the_shipped_config_serves_the_embedder_from_ollama() -> None:
    """AD-9 puts the model host on the Mac, not in a container."""
    from conftest import REPO_ROOT
    from meetingminer.config import load_config

    settings = load_config(REPO_ROOT / "config.yaml", REPO_ROOT / ".env").settings
    assert "ollama" in settings.providers
    assert build_embedder(
        load_config(REPO_ROOT / "config.yaml", REPO_ROOT / ".env")
    ).base_url == settings.providers["ollama"].base_url
