"""The remote-http engine for the `Diarizer` port (backlog B-36, AD-8/AD-9).

A LAN GPU host serves ``POST /diarize`` — one multipart upload named ``file``,
answered with ``{"turns":[{"start","end","speaker"}],"model":...}`` in float
seconds — and needs no token, unlike the in-process ``pyannote`` engine's gated
model. Where inference runs is a config change, never a code change (AD-9), so
this module is a new adapter behind the unchanged port and nothing else moves.

Deliberately the standard library, the convention `adapters/embed/ollama.py`
set: the whole protocol is one POST, and a client dependency to reach it would
put a third HTTP stack in the server for no gain, while `urllib`'s failure
taxonomy already separates "the host answered" from "the host is not there".

**Every failure is named; none is survivable.** The host is operator-scheduled
(VM120 is ``onboot=0`` and shares its GPU), so being down is a normal state
rather than an exception — which is exactly why this engine must never
substitute another one. A meeting ingested with no speaker turns when the
operator asked for diarization is the silent degradation this project has
rejected by owner decision, and an empty ``turns`` list from a *healthy* host
is indistinguishable from it after the fact. So a healthy host's empty list is
success, and everything else raises :class:`DiarizerError` carrying the
endpoint, the model the host named, and the host's own ``reason`` verbatim.
"""

from __future__ import annotations

import http.client
import io
import json
import math
import os
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import IO, Any

from meetingminer.adapters.diarize.port import DiarizationTurn, DiarizerError

ENGINE_NAME = "remote-http"

# `pipeline/speakers.py`'s placeholder pattern matches `speaker` plus at most
# three trailing characters, so `SPEAKER_1000` would stop being a placeholder
# and could resolve to a participant — the wrong attribution the never-guess
# rule exists to prevent (AD-13). The same cap the pyannote engine applies, for
# the same reason; it is a correctness bound, not tidiness.
MAX_PLACEHOLDER_SPEAKERS = 1000

_UPLOAD_FIELD = "file"
_ROUTE = "/diarize"

# Response bodies are consumed in bounded blocks so the monotonic request
# deadline is re-checked throughout a slow response. The upload is likewise a
# reader that http.client pulls in its own blocks, so a 60-minute 16 kHz mono
# WAV (~115 MB) is never fully resident.
_BLOCK_SIZE = 1 << 16


class _MultipartBody:
    """A read-only stream chaining ``prefix -> file -> suffix``.

    `urllib` sends any object exposing ``read`` by pulling blocks from it, and
    uses the explicit ``Content-Length`` this class's :attr:`length` supplies
    rather than chunking — so the file is streamed off disk, once.
    """

    def __init__(
        self,
        prefix: bytes,
        handle: IO[bytes],
        file_size: int,
        suffix: bytes,
        *,
        deadline: float,
    ) -> None:
        self._parts: list[IO[bytes]] = [io.BytesIO(prefix), handle, io.BytesIO(suffix)]
        self._index = 0
        self._deadline = deadline
        self.length = len(prefix) + file_size + len(suffix)

    def read(self, size: int = -1) -> bytes:
        if time.monotonic() >= self._deadline:
            raise TimeoutError("request deadline expired while uploading audio")
        if size < 0:
            remaining = b"".join(part.read() for part in self._parts[self._index :])
            self._index = len(self._parts)
            return remaining
        while self._index < len(self._parts):
            chunk = self._parts[self._index].read(size)
            if chunk:
                return chunk
            self._index += 1
        return b""


def _quote_filename(name: str) -> str:
    """A filename safe to place inside a quoted header parameter."""
    cleaned = name.replace("\\", "_").replace('"', "_")
    return "".join(character for character in cleaned if character.isprintable())


def _reason_from(body: bytes) -> tuple[str, str | None]:
    """``(reason, model)`` out of an error body — the host's words, verbatim.

    The service answers failures as ``{"ok":false,"reason":...}`` (verified
    2026-08-30 for both a 503 with the GPU held elsewhere and a 400 on a
    non-audio upload), but a proxy or a crash can put anything on the wire, so
    an unparseable body degrades to its own decoded text rather than to a
    sentence this adapter invented.
    """
    text = body.decode("utf-8", errors="replace").strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        return text, None
    if not isinstance(parsed, dict):
        return text, None
    model = parsed.get("model")
    reason = parsed.get("reason") or parsed.get("error") or text
    return str(reason).strip(), str(model) if isinstance(model, str) else None


def _number(value: Any) -> float | None:
    """``value`` as float seconds, or ``None`` if it is not a JSON number.

    ``bool`` is excluded on purpose: it is an ``int`` subclass, so a ``true``
    in a timestamp field would otherwise silently become 1.0 second.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


class RemoteHttpDiarizer:
    """`Diarizer` over a LAN diarization service's ``POST /diarize``."""

    name = ENGINE_NAME

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.endpoint = f"{self.base_url}{_ROUTE}"

    # -- port -------------------------------------------------------------

    def diarize(self, path: Path) -> tuple[DiarizationTurn, ...]:
        body = self._post(path)
        parsed = self._parse(body)
        model = parsed.get("model") if isinstance(parsed.get("model"), str) else None
        raw_turns = parsed.get("turns")
        if not isinstance(raw_turns, list):
            raise DiarizerError(
                f"{self._who(model)} returned no `turns` list:"
                f" the body's `turns` is {type(raw_turns).__name__}"
            )
        return self._to_turns(raw_turns, model)

    # -- transport --------------------------------------------------------

    def _post(self, path: Path) -> bytes:
        boundary = f"----MeetingMiner{secrets.token_hex(16)}"
        prefix = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{_UPLOAD_FIELD}";'
            f' filename="{_quote_filename(path.name)}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        suffix = f"\r\n--{boundary}--\r\n".encode()

        handle: IO[bytes] | None = None
        try:
            handle = path.open("rb")
            file_size = os.fstat(handle.fileno()).st_size
        except OSError as exc:
            if handle is not None:
                handle.close()
            raise DiarizerError(
                f"the {ENGINE_NAME} diarizer cannot read the audio it was asked"
                f" to send to {self.endpoint}: {path} ({exc})"
            ) from exc

        started = time.monotonic()
        deadline = started + self.timeout_seconds
        try:
            stream = _MultipartBody(
                prefix,
                handle,
                file_size,
                suffix,
                deadline=deadline,
            )
            request = urllib.request.Request(  # noqa: S310 - config.yaml, http(s) only
                self.endpoint,
                data=stream,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(stream.length),
                    "Accept": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(  # noqa: S310 - config.yaml, http(s) only
                request, timeout=self._remaining(deadline)
            ) as response:
                return self._read_response(response, deadline)
        except urllib.error.HTTPError as exc:
            # The host answered and said no. Its own words, not ours: it
            # reports 503 when another VM holds the GPU and 400 when ffmpeg
            # rejects the upload, so the taxonomy is not one status code.
            try:
                error_body = self._read_response(exc, deadline)
            except TimeoutError as read_exc:
                raise self._timed_out(started, read_exc) from read_exc
            except http.client.HTTPException as read_exc:
                raise self._malformed_response(read_exc, status=exc.code) from read_exc
            reason, model = _reason_from(error_body)
            raise DiarizerError(
                f"{self._who(model)} refused the request (HTTP {exc.code}):"
                f" {reason or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise self._timed_out(started, exc) from exc
            raise self._unreachable(exc.reason) from exc
        except TimeoutError as exc:
            # The host accepted the upload and never answered: urllib does not
            # wrap a timeout raised while reading the response.
            raise self._timed_out(started, exc) from exc
        except http.client.HTTPException as exc:
            raise self._malformed_response(exc) from exc
        except OSError as exc:
            raise self._unreachable(exc) from exc
        finally:
            handle.close()

    def _parse(self, body: bytes) -> dict[str, Any]:
        try:
            parsed = json.loads(body)
        except ValueError as exc:
            raise DiarizerError(
                f"{self._who(None)} answered 200 with a body that is not JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise DiarizerError(
                f"{self._who(None)} answered 200 with a"
                f" {type(parsed).__name__} rather than an object carrying"
                " `turns`"
            )
        return parsed

    # -- the port's shape -------------------------------------------------

    def _to_turns(
        self, raw_turns: list[Any], model: str | None
    ) -> tuple[DiarizationTurn, ...]:
        """Validate, convert to milliseconds, order, and canonicalize labels."""
        measured: list[tuple[int, int, str]] = []
        for raw in raw_turns:
            if not isinstance(raw, dict):
                raise DiarizerError(
                    f"{self._who(model)} returned a turn that is not an"
                    f" object: {raw!r}"
                )
            start = _number(raw.get("start"))
            end = _number(raw.get("end"))
            speaker = raw.get("speaker")
            if start is None or end is None or not isinstance(speaker, str):
                raise DiarizerError(
                    f"{self._who(model)} returned a turn missing a numeric"
                    f" `start`/`end` or a text `speaker`: {raw!r}"
                )
            if end < start:
                # A host that inverts a span is not producing trustworthy
                # output. Dropping it quietly would leave the pipeline
                # attributing speech from a diarization it cannot trust.
                raise DiarizerError(
                    f"{self._who(model)} returned a turn whose end precedes its"
                    f" start: {raw!r}"
                )
            # The endpoint reports float seconds; `DiarizationTurn` carries
            # integer milliseconds. Each boundary rounds INDEPENDENTLY —
            # `round(x * 1000)`, never `start + round(duration)`, which would
            # accumulate — so a boundary two turns share lands on the same
            # millisecond in both. This is the rounding
            # `adapters/diarize/pyannote.py::_to_turns` already applies; the
            # `transcribe` stage assigns each segment the tag with the longest
            # overlap, so a systematic bias would mis-attribute speech.
            measured.append((round(start * 1000), round(end * 1000), speaker))

        canonical: dict[str, str] = {}
        turns: list[DiarizationTurn] = []
        # Sort BEFORE labelling so "first appearance" means first in the
        # timeline, and the tags a recording gets do not depend on the order
        # the host happened to emit its turns in.
        for start_ms, end_ms, speaker in sorted(measured, key=lambda one: one[0]):
            if end_ms <= start_ms:
                # Collapsed by rounding: it can never win `speaker_at`'s
                # longest-overlap comparison, so it must not consume a
                # placeholder number either.
                continue
            tag = canonical.get(speaker)
            if tag is None:
                if len(canonical) >= MAX_PLACEHOLDER_SPEAKERS:
                    raise DiarizerError(
                        f"{self._who(model)} returned more than"
                        f" {MAX_PLACEHOLDER_SPEAKERS} distinct speakers;"
                        " generated tags support at most"
                        f" {MAX_PLACEHOLDER_SPEAKERS} without leaving the"
                        " never-guess placeholder namespace"
                    )
                tag = f"SPEAKER_{len(canonical):02d}"
                canonical[speaker] = tag
            turns.append(DiarizationTurn(start_ms=start_ms, end_ms=end_ms, speaker=tag))
        return tuple(turns)

    # -- diagnostics ------------------------------------------------------

    def _read_response(self, response: Any, deadline: float) -> bytes:
        """Read one response while enforcing the request's wall-clock deadline."""
        framed = response.fp if isinstance(response, urllib.error.HTTPError) else response
        reader = getattr(response, "read1", response.read)
        chunks: list[bytes] = []
        while True:
            remaining = self._remaining(deadline)
            self._set_response_timeout(framed, remaining)
            chunk = reader(_BLOCK_SIZE)
            if not chunk:
                missing = getattr(framed, "length", None)
                if isinstance(missing, int) and missing > 0:
                    raise http.client.IncompleteRead(b"", missing)
                return b"".join(chunks)
            chunks.append(chunk)

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("request deadline expired")
        return remaining

    @staticmethod
    def _set_response_timeout(response: Any, timeout_seconds: float) -> None:
        buffered = getattr(response, "fp", None)
        raw = getattr(buffered, "raw", None)
        sock = getattr(raw, "_sock", None)
        if sock is not None:
            sock.settimeout(timeout_seconds)

    def _who(self, model: str | None) -> str:
        """The subject every message starts with: engine, endpoint, model."""
        named = f" (model {model!r})" if model else ""
        return f"the {ENGINE_NAME} diarizer at {self.endpoint}{named}"

    def _timed_out(self, started: float, exc: BaseException) -> DiarizerError:
        elapsed = time.monotonic() - started
        return DiarizerError(
            f"{self._who(None)} did not answer within"
            f" {self.timeout_seconds:g}s (waited {elapsed:.1f}s): {exc}."
            " /diarize and /transcribe share one inference lock on that host,"
            " so a call can queue behind a whole transcription — raise"
            " diarizer.timeout_seconds in config.yaml if the queue is real,"
            " and check the host if it is not"
        )

    def _unreachable(self, reason: object) -> DiarizerError:
        return DiarizerError(
            f"{self._who(None)} is unreachable ({reason}). That host is"
            " operator-scheduled — it is started by hand and shares its GPU —"
            " so start it, or bind diarizer.engine to another engine in"
            " config.yaml. No other engine is substituted here: a meeting"
            " ingested with no speaker turns would look exactly like a"
            " successful diarization of silence"
        )

    def _malformed_response(
        self, exc: http.client.HTTPException, *, status: int | None = None
    ) -> DiarizerError:
        status_text = f" after HTTP {status}" if status is not None else ""
        return DiarizerError(
            f"{self._who(None)} returned an incomplete or malformed HTTP"
            f" response{status_text}: {exc}"
        )
