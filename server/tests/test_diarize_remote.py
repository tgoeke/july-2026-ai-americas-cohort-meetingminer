"""The remote-http engine behind the `Diarizer` port (backlog B-36, diarizer half).

Offline by construction. Every transport path runs against a scripted
`BaseHTTPRequestHandler` bound to `127.0.0.1:0` in a daemon thread — the same
trick `test_embed_adapter.py` uses — so the multipart encoding, the
`Content-Length`, the status codes and the socket failures are all real while
the LAN GPU host stays untouched. `DEAD_PORT` supplies a refused connection.

**What matters here is that the engine never degrades quietly.** The host is
operator-scheduled (VM120 is `onboot=0` and shares its GPU), so "down" is a
normal state, and the owner has rejected silent fallback: every failure has to
surface as a :class:`DiarizerError` carrying the endpoint and the host's own
words, never as an empty turn list that looks like success. An *empty* list
from a healthy host is the one legitimate no-signal answer, and the difference
between the two is pinned below.

The one live test against the LAN host is env-flagged and skipped by default.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import wave
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
from pydantic import ValidationError

from meetingminer.adapters.diarize import (
    ENGINE_CHOICES,
    PYANNOTE_ENGINE,
    REMOTE_HTTP_ENGINE,
    DiarizationTurn,
    DiarizerError,
    NoopDiarizer,
    RemoteHttpDiarizer,
    build_diarizer,
)
from meetingminer.adapters.diarize.remote_http import MAX_PLACEHOLDER_SPEAKERS
from meetingminer.config import AppConfig, DiarizerConfig
from meetingminer.pipeline.speakers import is_placeholder_label

# A port nothing listens on: connecting fails immediately with a refusal, which
# is exactly the "the operator has not started VM120" case.
DEAD_PORT = 1

NETWORK_FLAG = "MM_DIARIZE_REMOTE_NETWORK_TEST"

HOST_MODEL = "ClusteringDiarizer(vad_multilingual_marblenet+titanet_large)"


# --- a local HTTP stub, so the transport is real ---------------------------


@dataclass
class Received:
    """One request the stub actually saw, decoded."""

    path: str
    method: str
    content_length: int
    content_type: str
    body: bytes
    fields: dict[str, tuple[str, bytes]] = field(default_factory=dict)


def _parse_multipart(content_type: str, body: bytes) -> dict[str, tuple[str, bytes]]:
    """`{name: (filename, payload)}` from one multipart/form-data body."""
    boundary = content_type.split("boundary=", 1)[1].strip().strip('"')
    marker = b"--" + boundary.encode("ascii")
    fields: dict[str, tuple[str, bytes]] = {}
    for chunk in body.split(marker)[1:-1]:
        part = chunk[2:] if chunk.startswith(b"\r\n") else chunk
        head, _, payload = part.partition(b"\r\n\r\n")
        headers = head.decode("utf-8", errors="replace")
        name = re.search(r'name="([^"]*)"', headers)
        filename = re.search(r'filename="([^"]*)"', headers)
        if name is None:
            continue
        fields[name.group(1)] = (
            filename.group(1) if filename else "",
            payload[:-2] if payload.endswith(b"\r\n") else payload,
        )
    return fields


class _QuietServer(HTTPServer):
    """An HTTPServer that does not print a traceback when a client walks away.

    The timeout test abandons a request mid-flight on purpose; the handler
    thread then writes to a closed socket, and the default handler dumps a
    traceback into the test output.
    """

    def handle_error(self, request: Any, client_address: Any) -> None:
        return


def _serve(
    responder: Callable[[Received], tuple[int, bytes]], received: list[Received]
) -> Iterator[str]:
    """Run a one-route HTTP server that answers however `responder` says."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "")
            request = Received(
                path=self.path,
                method=self.command,
                content_length=length,
                content_type=content_type,
                body=body,
                fields=(
                    _parse_multipart(content_type, body)
                    if "boundary=" in content_type
                    else {}
                ),
            )
            received.append(request)
            status, payload = responder(request)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args: Any) -> None:
            return  # keep the test output clean

    server = _QuietServer(("127.0.0.1", 0), Handler)
    # `serve_forever`'s default 0.5s poll interval is 0.5s of teardown per
    # stub, and this module installs one per test.
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


Install = Callable[[Callable[[Received], tuple[int, bytes]]], tuple[str, list[Received]]]


@pytest.fixture()
def diarize_stub() -> Iterator[Install]:
    """Factory: install a scripted /diarize responder, get its base URL."""
    running: list[Iterator[str]] = []

    def _install(
        responder: Callable[[Received], tuple[int, bytes]],
    ) -> tuple[str, list[Received]]:
        received: list[Received] = []
        generator = _serve(responder, received)
        running.append(generator)
        return next(generator), received

    yield _install
    for generator in running:
        with pytest.raises(StopIteration):
            next(generator)


def answers(
    payload: dict[str, Any] | list[Any] | str, status: int = 200
) -> Callable[[Received], tuple[int, bytes]]:
    """A responder that always sends this body (a `str` is sent verbatim)."""
    body = (
        payload.encode("utf-8")
        if isinstance(payload, str)
        else json.dumps(payload).encode("utf-8")
    )

    def _responder(_request: Received) -> tuple[int, bytes]:
        return status, body

    return _responder


def turns_body(*turns: dict[str, Any]) -> dict[str, Any]:
    return {"turns": list(turns), "model": HOST_MODEL}


def turn(start: float, end: float, speaker: str) -> dict[str, Any]:
    return {"start": start, "end": end, "speaker": speaker}


@pytest.fixture()
def audio(tmp_path: Path) -> Path:
    """A small file standing in for the recording; the stub never decodes it."""
    path = tmp_path / "meeting.wav"
    path.write_bytes(b"RIFF____WAVEfmt " + b"\x00" * 512)
    return path


@dataclass(frozen=True)
class Binding:
    """Structural stand-in for DiarizerConfig, this story's fields included."""

    # `model` and `token_env` belong to the in-process engine; this one must
    # ignore them, and the values below are deliberately not usable ones.
    engine: str = REMOTE_HTTP_ENGINE
    model: str = "not-this-engines-field"
    token_env: str = "MM_NOT_THIS_ENGINES_FIELD"
    base_url: str = f"http://127.0.0.1:{DEAD_PORT}"
    timeout_seconds: float = 5.0


# --- the happy path, and what the host actually receives --------------------


def test_seconds_become_integer_milliseconds(
    diarize_stub: Install, audio: Path
) -> None:
    base_url, received = diarize_stub(
        answers(
            turns_body(
                turn(0.46, 4.57, "SPEAKER_00"),
                turn(4.57, 9.0015, "SPEAKER_01"),
                turn(9.0015, 12.3456, "SPEAKER_00"),
            )
        )
    )
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    turns = engine.diarize(audio)

    assert turns == (
        DiarizationTurn(start_ms=460, end_ms=4570, speaker="SPEAKER_00"),
        DiarizationTurn(start_ms=4570, end_ms=9002, speaker="SPEAKER_01"),
        DiarizationTurn(start_ms=9002, end_ms=12346, speaker="SPEAKER_00"),
    )
    assert all(isinstance(one.start_ms, int) for one in turns)
    # Each boundary rounds independently: 9.0015 -> 9002 in BOTH turns, so the
    # tags stay adjacent rather than overlapping or leaving a gap.
    assert turns[1].end_ms == turns[2].start_ms

    assert len(received) == 1
    request = received[0]
    assert request.method == "POST"
    assert request.path == "/diarize"
    assert request.content_type.startswith("multipart/form-data; boundary=")
    assert set(request.fields) == {"file"}
    filename, payload = request.fields["file"]
    assert filename == "meeting.wav"
    assert payload == audio.read_bytes()
    # An honest Content-Length, i.e. the streamed body was measured, not
    # guessed: the server read exactly that many bytes and got the whole part.
    assert request.content_length == len(request.body)


def test_empty_turns_is_success_not_an_error(
    diarize_stub: Install, audio: Path
) -> None:
    # Verified live 2026-08-30: 3s of digital silence answers 200 with [].
    base_url, _ = diarize_stub(answers({"turns": [], "model": HOST_MODEL}))
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    assert engine.diarize(audio) == ()


def test_labels_are_canonicalized_by_first_appearance(
    diarize_stub: Install, audio: Path
) -> None:
    # Whatever the host calls them, the port promises recording-local
    # placeholders: `pipeline/speakers.py` must never resolve one to a person.
    base_url, _ = diarize_stub(
        answers(
            turns_body(
                turn(2.0, 3.0, "cluster-7"),
                turn(0.0, 1.0, "speaker_alpha"),
                turn(4.0, 5.0, "cluster-7"),
            )
        )
    )
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    turns = engine.diarize(audio)

    # First appearance is measured in TIMELINE order, not the host's order.
    assert [one.speaker for one in turns] == [
        "SPEAKER_00",
        "SPEAKER_01",
        "SPEAKER_01",
    ]
    assert all(is_placeholder_label(one.speaker) for one in turns)


def test_non_monotonic_turns_are_sorted_by_start(
    diarize_stub: Install, audio: Path
) -> None:
    base_url, _ = diarize_stub(
        answers(
            turns_body(
                turn(10.0, 11.0, "A"),
                turn(1.0, 2.0, "B"),
                turn(5.0, 6.0, "C"),
            )
        )
    )
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    turns = engine.diarize(audio)

    assert [one.start_ms for one in turns] == [1000, 5000, 10000]


def test_sub_millisecond_turn_is_dropped_before_it_claims_a_tag(
    diarize_stub: Install, audio: Path
) -> None:
    # A span that rounds to nothing cannot win `speaker_at`'s longest-overlap
    # comparison, so it must not consume a placeholder number either.
    base_url, _ = diarize_stub(
        answers(
            turns_body(
                turn(1.00001, 1.00002, "ghost"),
                turn(2.0, 3.0, "real"),
            )
        )
    )
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    turns = engine.diarize(audio)

    assert turns == (
        DiarizationTurn(start_ms=2000, end_ms=3000, speaker="SPEAKER_00"),
    )


# --- failures, every one of them named -------------------------------------


def test_reversed_turn_fails_rather_than_being_dropped(
    diarize_stub: Install, audio: Path
) -> None:
    # A host that inverts a span is not producing trustworthy output; dropping
    # it silently would be the quiet degradation this project rejects.
    base_url, _ = diarize_stub(answers(turns_body(turn(9.0, 4.0, "SPEAKER_00"))))
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    with pytest.raises(DiarizerError) as caught:
        engine.diarize(audio)

    message = str(caught.value)
    assert f"{base_url}/diarize" in message
    assert "9.0" in message and "4.0" in message


def test_busy_host_503_quotes_the_reason_verbatim(
    diarize_stub: Install, audio: Path
) -> None:
    reason = "GPU is held by VM116; diarization is unavailable until it stops"
    base_url, _ = diarize_stub(
        answers({"ok": False, "reason": reason, "model": HOST_MODEL}, status=503)
    )
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    with pytest.raises(DiarizerError) as caught:
        engine.diarize(audio)

    message = str(caught.value)
    assert reason in message
    assert f"{base_url}/diarize" in message
    assert "503" in message
    assert HOST_MODEL in message


def test_other_http_error_carries_the_hosts_reason(
    diarize_stub: Install, audio: Path
) -> None:
    # Verified live 2026-08-30: a non-audio upload answers 400, not 503, so the
    # failure taxonomy cannot be keyed on one status code.
    reason = "ffmpeg: Invalid data found when processing input"
    base_url, _ = diarize_stub(
        answers({"ok": False, "error": "ValueError", "reason": reason}, status=400)
    )
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    with pytest.raises(DiarizerError) as caught:
        engine.diarize(audio)

    message = str(caught.value)
    assert reason in message
    assert f"{base_url}/diarize" in message
    assert "400" in message


def test_unreachable_host_names_the_endpoint_and_the_os_reason(audio: Path) -> None:
    base_url = f"http://127.0.0.1:{DEAD_PORT}"
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    with pytest.raises(DiarizerError) as caught:
        engine.diarize(audio)

    message = str(caught.value)
    assert f"{base_url}/diarize" in message
    assert "operator-scheduled" in message
    assert "refus" in message.lower() or "connect" in message.lower()


def test_timeout_names_the_budget_and_the_setting(
    diarize_stub: Install, audio: Path
) -> None:
    def _never_answers(_request: Received) -> tuple[int, bytes]:
        time.sleep(0.5)
        return 200, b"{}"

    base_url, _ = diarize_stub(_never_answers)
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=0.15)

    with pytest.raises(DiarizerError) as caught:
        engine.diarize(audio)

    message = str(caught.value)
    assert f"{base_url}/diarize" in message
    assert "0.15" in message
    assert "diarizer.timeout_seconds" in message


def test_body_that_is_not_json_is_named(diarize_stub: Install, audio: Path) -> None:
    base_url, _ = diarize_stub(answers("<html>502 Bad Gateway</html>"))
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    with pytest.raises(DiarizerError) as caught:
        engine.diarize(audio)

    message = str(caught.value)
    assert f"{base_url}/diarize" in message
    assert "JSON" in message


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param({"model": HOST_MODEL}, "turns", id="turns-missing"),
        pytest.param({"turns": {"a": 1}}, "turns", id="turns-not-a-list"),
        pytest.param({"turns": "SPEAKER_00"}, "turns", id="turns-a-string"),
        pytest.param([], "turns", id="body-not-an-object"),
    ],
)
def test_a_body_without_a_turns_list_is_named(
    diarize_stub: Install, audio: Path, body: Any, expected: str
) -> None:
    base_url, _ = diarize_stub(answers(body))
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    with pytest.raises(DiarizerError) as caught:
        engine.diarize(audio)

    message = str(caught.value)
    assert f"{base_url}/diarize" in message
    assert expected in message


@pytest.mark.parametrize(
    "bad_turn",
    [
        pytest.param({"end": 2.0, "speaker": "A"}, id="no-start"),
        pytest.param({"start": 1.0, "speaker": "A"}, id="no-end"),
        pytest.param({"start": 1.0, "end": 2.0}, id="no-speaker"),
        pytest.param({"start": "1.0", "end": 2.0, "speaker": "A"}, id="start-a-string"),
        pytest.param({"start": 1.0, "end": None, "speaker": "A"}, id="end-null"),
        pytest.param({"start": 1.0, "end": 2.0, "speaker": 7}, id="speaker-a-number"),
        pytest.param({"start": True, "end": 2.0, "speaker": "A"}, id="start-a-bool"),
        pytest.param(["1.0", "2.0", "A"], id="turn-not-an-object"),
    ],
)
def test_a_malformed_turn_is_named(
    diarize_stub: Install, audio: Path, bad_turn: Any
) -> None:
    base_url, _ = diarize_stub(answers({"turns": [bad_turn], "model": HOST_MODEL}))
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    with pytest.raises(DiarizerError) as caught:
        engine.diarize(audio)

    assert f"{base_url}/diarize" in str(caught.value)


def test_more_speakers_than_the_placeholder_namespace_holds(
    diarize_stub: Install, audio: Path
) -> None:
    # `_PLACEHOLDER_LABEL` matches `speaker` plus at most three trailing
    # characters, so `SPEAKER_1000` would stop being a placeholder and could
    # resolve to a participant (AD-13). Refuse rather than emit one.
    over = MAX_PLACEHOLDER_SPEAKERS + 1
    base_url, _ = diarize_stub(
        answers(
            {
                "turns": [
                    turn(float(index), float(index) + 0.5, f"c{index}")
                    for index in range(over)
                ],
                "model": HOST_MODEL,
            }
        )
    )
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    with pytest.raises(DiarizerError) as caught:
        engine.diarize(audio)

    assert str(MAX_PLACEHOLDER_SPEAKERS) in str(caught.value)


def test_exactly_the_namespace_limit_still_succeeds(
    diarize_stub: Install, audio: Path
) -> None:
    base_url, _ = diarize_stub(
        answers(
            {
                "turns": [
                    turn(float(index), float(index) + 0.5, f"c{index}")
                    for index in range(MAX_PLACEHOLDER_SPEAKERS)
                ],
                "model": HOST_MODEL,
            }
        )
    )
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    turns = engine.diarize(audio)

    assert len(turns) == MAX_PLACEHOLDER_SPEAKERS
    assert turns[-1].speaker == f"SPEAKER_{MAX_PLACEHOLDER_SPEAKERS - 1}"
    assert all(is_placeholder_label(one.speaker) for one in turns)


def test_a_missing_audio_file_fails_by_name_without_a_request(
    diarize_stub: Install, tmp_path: Path
) -> None:
    base_url, received = diarize_stub(answers(turns_body()))
    engine = RemoteHttpDiarizer(base_url=base_url, timeout_seconds=5.0)

    with pytest.raises(DiarizerError) as caught:
        engine.diarize(tmp_path / "absent.wav")

    assert "absent.wav" in str(caught.value)
    assert received == []


# --- the binding: config.yaml is the only place an engine is named ---------


def test_build_returns_the_remote_engine_and_makes_no_request(
    diarize_stub: Install,
) -> None:
    base_url, received = diarize_stub(answers(turns_body()))

    engine = build_diarizer(Binding(base_url=base_url, timeout_seconds=42.5))

    assert isinstance(engine, RemoteHttpDiarizer)
    assert engine.name == REMOTE_HTTP_ENGINE == "remote-http"
    assert engine.base_url == base_url
    assert engine.timeout_seconds == 42.5
    # Building must not probe the host: a `/health` call here would make the
    # operator-scheduled box a build-time dependency of every transcribe run.
    assert received == []


def test_a_trailing_slash_in_the_base_url_does_not_double_up(
    diarize_stub: Install, audio: Path
) -> None:
    base_url, received = diarize_stub(answers(turns_body()))
    engine = build_diarizer(Binding(base_url=base_url + "/"))

    assert engine.diarize(audio) == ()
    assert received[0].path == "/diarize"


def test_unknown_engine_names_the_remote_choice() -> None:
    with pytest.raises(DiarizerError) as caught:
        build_diarizer(Binding(engine="whisper-x"))

    message = str(caught.value)
    assert "whisper-x" in message
    # The diagnostic stays exhaustive: the remote engine is special-cased in
    # `build_diarizer` rather than living in `ENGINES`, so nothing but this
    # would notice it dropping out of the list an operator is offered.
    assert REMOTE_HTTP_ENGINE in ENGINE_CHOICES
    assert set(ENGINE_CHOICES) == {NoopDiarizer.name, PYANNOTE_ENGINE, REMOTE_HTTP_ENGINE}
    for choice in ENGINE_CHOICES:
        assert choice in message


def test_shipped_config_still_binds_noop(app_config: AppConfig) -> None:
    # The owner picks the default engine, not this story: `noop` stays bound
    # in the committed config.yaml pending a capacity measurement.
    diarizer = app_config.settings.diarizer
    assert diarizer.engine == "noop"
    assert diarizer.base_url
    assert diarizer.timeout_seconds > 0


@pytest.mark.parametrize(
    "timeout",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1.0, id="negative"),
        pytest.param(float("inf"), id="infinite"),
        pytest.param(float("nan"), id="nan"),
    ],
)
def test_a_timeout_that_is_not_finite_and_positive_is_rejected(timeout: float) -> None:
    # "Finite" is a validated property of the binding, not a hope about it.
    with pytest.raises(ValidationError):
        DiarizerConfig(engine=REMOTE_HTTP_ENGINE, timeout_seconds=timeout)


def test_an_empty_base_url_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DiarizerConfig(engine=REMOTE_HTTP_ENGINE, base_url="   ")


def test_the_remote_engine_name_is_a_valid_binding() -> None:
    config = DiarizerConfig(engine=REMOTE_HTTP_ENGINE)
    assert config.engine == REMOTE_HTTP_ENGINE
    assert config.timeout_seconds == 900.0


# --- the one live test ------------------------------------------------------


# No `slow` mark, deliberately: the marker's registry in
# `test_compose_contract.py` pins an exact set of slow-marked tests, and this
# one is skipped by default anyway. It is the same shape story 6.2's network
# test has. Running it by hand outstrips the fast-test budget, so raise it for
# that run: `-o mm_fast_test_budget_seconds=120`.
@pytest.mark.skipif(
    os.environ.get(NETWORK_FLAG) != "1",
    reason=(
        "a real POST to the LAN diarization host (VM120, started by hand):"
        f" set {NETWORK_FLAG}=1 to run it"
    ),
)
def test_real_lan_host_diarizes_silence(tmp_path: Path, app_config: AppConfig) -> None:
    """Three seconds of digital silence, against the host in config.yaml.

    Silence is the one input whose answer is known without ground truth: the
    host returns 200 with no turns, which this engine must report as success.
    """
    path = tmp_path / "silence.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00" * (2 * 16000 * 3))

    binding = app_config.settings.diarizer
    engine = RemoteHttpDiarizer(
        base_url=binding.base_url, timeout_seconds=binding.timeout_seconds
    )

    assert engine.diarize(path) == ()
