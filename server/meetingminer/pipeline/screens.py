"""The `screens` stage's decision logic, with no database and no OCR engine.

Segmentation, representative selection, view-type classification, and screen
identity are pure functions over a list of per-frame facts, so every rule the
Epic 5 harness will score is unit-testable without Postgres, ffmpeg, or an OCR
engine — and so none of them can quietly become a model call. Every threshold
arrives as :class:`~meetingminer.config.ScreensConfig`, never as a constant
here (AD-10).

The bias is NFR8's: an uncertain boundary produces an extra capture, never a
dropped one. Story 1.11 retuned what produces one. A capture is started when
the cropped region of the frame in hand differs enough from the last emitted
shot — one bounded diff of two frames, nothing summed — and it is emitted at
the frame where that region settles, not at the moment of change
(`capture-measurements.md` §2, §3). OCR text no longer decides captures at
all; it still decides screen *identity*, which is what it was always good at.

The pixel facts arrive as plain numbers measured in the I/O layer
(:mod:`meetingminer.pipeline.frameimage`), so nothing here opens an image and
this module stays importable without an imaging library.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence
from uuid import UUID

from meetingminer.config import ScreensConfig

# View types, in the order the classifier tests them.
VIEW_PARTICIPANT_GALLERY = "participant-gallery"
VIEW_SLIDE = "slide"
VIEW_UI_SCREEN = "ui-screen"
VIEW_TYPES = (VIEW_SLIDE, VIEW_UI_SCREEN, VIEW_PARTICIPANT_GALLERY)

# Capture cues recorded on `screenshot.capture_cues`.
CUE_FIRST_FRAME = "first-frame"
CUE_REGION_CHANGE = "region-change"
CUE_SETTLED_CHANGE = "settled-change"

# Tags recorded on `screenshot.classification_tags`. Both exist because the
# honest answer is "not separable" — §3 cannot cut loading frames without
# cutting real ones, and §4's pixel pair cannot tell avatar tiles from a
# screen. Per NFR8 the frame is kept and labelled, never dropped.
TAG_LIKELY_TRANSITION = "likely-transition"
TAG_AVATAR_GALLERY_UNRESOLVED = "avatar-gallery-unresolved"

# Everything that is not a word character in *any* script, plus the
# underscore, which `\W` counts as a word character. An ASCII-only class here
# would delete every accented, Cyrillic, or CJK letter and normalize a
# non-English slide to the empty string, which would then take a
# meeting-scoped identity and never gain lineage.
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def normalize_text(text: str) -> str:
    """Fold recognized text to the form screen identity is compared on.

    Unicode-normalized, case-folded, and reduced to word tokens separated by
    single spaces, in whatever script the screen is written in. Punctuation
    and layout whitespace are dropped because two engines (and two renderings
    of the same screen) disagree about them constantly, while the words
    themselves are stable.
    """
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    return " ".join(token for token in _NON_WORD.split(folded) if token)


def tokens(normalized: str) -> frozenset[str]:
    """The token set a Jaccard comparison runs over."""
    return frozenset(normalized.split())


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    """Jaccard similarity of two token sets.

    Two empty sets score 1.0: consecutive textless frames are *not* a
    text-change boundary — nothing changed. One empty set against a non-empty
    one scores 0.0, which is a boundary, correctly.
    """
    a, b = frozenset(left), frozenset(right)
    if not a and not b:
        return 1.0
    union = a | b
    if not union:  # pragma: no cover - unreachable given the check above
        return 1.0
    return len(a & b) / len(union)


@dataclass(frozen=True)
class FrameFacts:
    """One sampled frame as the segmenter sees it.

    Everything here is already *cropped*: the pixel numbers are measured over
    the share region, and the block geometry is this frame's `frame_ocr` row
    recomputed on that same region. ``normalized_text`` stays whole-frame —
    it feeds screen identity, not segmentation, and the webcam column
    contributes no text worth excluding.

    ``change_fraction_vs_previous`` is the fraction of the region's pixels
    that moved since the previous sampled frame; the first frame of a
    recording has no predecessor and so reports 0.0.
    """

    frame_id: UUID | str
    offset_ms: int
    normalized_text: str
    block_count: int
    text_density: float
    mean_block_height: float
    # No defaults. A default-constructed frame would read white_fraction 0.0,
    # which already satisfies half the camera rule — a classifier decision
    # region is the last place a forgotten field should land. The stage
    # always measures all three.
    change_fraction_vs_previous: float
    white_fraction: float
    mean_saturation: float

    @property
    def token_set(self) -> frozenset[str]:
        return tokens(self.normalized_text)


@dataclass(frozen=True)
class Capture:
    """One screenshot-to-be: a run of frames, its cues, and its representative."""

    ordinal: int
    start_offset_ms: int
    end_offset_ms: int
    frame_count: int
    representative: FrameFacts
    cues: tuple[str, ...]
    view_type: str
    signature: str
    tags: tuple[str, ...] = ()


# How much the share region changed between two frames, measured in the I/O
# layer. Segmentation asks this about the *emitted* shot and the frame in
# hand, which is a question no per-frame number can answer — which frame was
# emitted is a decision this module has not made yet when the facts are built.
ChangeSinceEmitted = Callable[[FrameFacts, FrameFacts], float]


class _OpenCapture:
    """A capture still accumulating frames, and its settle state.

    ``emitted`` is the frame the region settled on — the screenshot this
    capture will store, and the reference every later change is measured
    against. It stays ``None`` while the capture is still inside the
    transition burst its cue opened, which is what makes the timeout
    reachable.
    """

    __slots__ = ("anchor", "cues", "frames", "emitted", "timed_out")

    def __init__(self, anchor: FrameFacts, cues: list[str], settled: bool) -> None:
        self.anchor = anchor
        self.cues = cues
        self.frames: list[FrameFacts] = [anchor]
        self.emitted: FrameFacts | None = anchor if settled else None
        self.timed_out = False

    def force_emit(self) -> None:
        """Give up waiting for a settle: emit the window's richest frame.

        A transition frame is half the old screen and half the new, so it is
        never the richest — which is exactly why the fallback is
        :func:`choose_representative` rather than "whatever frame the clock
        landed on".
        """
        self.emitted = choose_representative(self.frames)
        self.timed_out = True


def choose_representative(frames: Sequence[FrameFacts]) -> FrameFacts:
    """The most text-rich frame of a capture, earliest on a tie.

    Richness is token count first, then raw text length. A transition frame —
    half the old screen, half the new — is never the richest, so it never
    represents the screen.
    """
    return max(
        frames,
        key=lambda frame: (
            len(frame.token_set),
            len(frame.normalized_text),
            -frame.offset_ms,
        ),
    )


def classify_view_type(
    frame: FrameFacts, config: ScreensConfig
) -> tuple[str, tuple[str, ...]]:
    """Classify a representative frame; returns ``(view_type, tags)``.

    First match wins, and the *pixel* pair is tested first (§4). Camera and
    gallery video is dark and saturated where screen share is bright and
    desaturated, and over 63 hand-labelled shots those two metrics separated
    the two classes perfectly — so a frame that reads as camera is a
    participant gallery whatever its text geometry says. That ordering is the
    point of the retune: text geometry used to decide, and a camera frame with
    a few incidental OCR boxes could be called a slide.

    Below that, the story-1.4 geometry rules are unchanged, with one honest
    label added. A textless frame with a handful of boxes is a participant
    gallery, but §4's known gap is that Teams gallery rendered as *initial-
    avatar tiles* on a light background is bright and desaturated, so it
    cannot be told from a near-empty screen on pixels. That case is still
    ``participant-gallery`` — never ``ui-screen`` or ``slide``, whose failure
    mode is silently calling a gallery a screen — and carries
    ``avatar-gallery-unresolved`` so the ambiguity is visible rather than
    asserted away. It is not a fourth view type, so the migration-0003 CHECK
    and every downstream consumer stay valid.
    """
    if (
        frame.white_fraction <= config.camera_max_white_fraction
        and frame.mean_saturation >= config.camera_min_saturation
    ):
        return VIEW_PARTICIPANT_GALLERY, ()
    if (
        frame.block_count <= config.gallery_max_blocks
        and frame.text_density < config.gallery_max_text_density
    ):
        return VIEW_PARTICIPANT_GALLERY, (TAG_AVATAR_GALLERY_UNRESOLVED,)
    if (
        frame.mean_block_height >= config.slide_min_block_height
        and frame.block_count <= config.slide_max_blocks
    ):
        return VIEW_SLIDE, ()
    return VIEW_UI_SCREEN, ()


def signature_for(representative: FrameFacts) -> str:
    """The text a screen is identified by: its representative's normalized text."""
    return representative.normalized_text


def identity_key_for(
    signature: str, meeting_id: UUID | str, ordinal: int, config: ScreensConfig
) -> str:
    """The key a Screen is upserted by (AD-5).

    A signature with real text hashes to a corpus-wide key, so the same screen
    shown in two meetings lands on one row. A signature below
    ``min_signature_tokens`` carries no evidence, so its key is scoped to this
    meeting — otherwise every textless screen in the corpus (camera galleries,
    video) would collapse onto a single row.
    """
    if len(tokens(signature)) < config.min_signature_tokens:
        return f"meeting:{meeting_id}:{ordinal}"
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def is_scoped_identity(identity_key: str) -> bool:
    """Whether this key is meeting-scoped (and therefore ineligible for lineage)."""
    return identity_key.startswith("meeting:")


def segment_captures(
    frames: Sequence[FrameFacts],
    config: ScreensConfig,
    change_since_emitted: ChangeSinceEmitted,
) -> list[Capture]:
    """Group frames in offset order into captures (`capture-measurements.md` §2-§4).

    Two rules, deliberately separate, because *when did something change* and
    *which frame should be kept* are different questions:

    **The cue decides when.** ``change_since_emitted`` measures the cropped
    region of the frame in hand against the last *emitted* shot, and a capture
    starts once that reaches ``change_threshold`` (`region-change`). The first
    frame always starts one (`first-frame`). Measuring against the emission
    rather than against the previous frame is what makes slow drift — a form
    being filled in, a page being scrolled — eventually cross the line, which
    is what the removed dwell-drift cue existed for, with no second knob. It
    is also why a slide held for half an hour is one capture: a static region
    never differs from the shot already taken of it.

    **The settled-change cue is the lower gate for same-chrome screens.** Two
    dense UI pages that share a browser and app frame can genuinely differ by
    less than ``change_threshold`` at analysis scale: on demo-001, three
    successive settled screens sat 0.047-0.081 from the emitted shot at 320px
    while the shipped gate was 0.10, so 176 seconds of paging collapsed into
    one capture. What separates a real page change from noise is not the size
    of the step but its shape: a change that *arrives and stays* — the region
    goes pixel-quiet at a new sustained distance from the emitted shot —
    against transient blips (a menu, a cursor, a tooltip) that spike and
    return to ~0. So a frame at or above ``settled_change_threshold`` from the
    emitted shot that is itself pixel-quiet counts toward a run, and
    ``settled_change_frames`` consecutive such frames cue a capture
    (`settled-change`). A frame that is not quiet, or that falls back under
    the floor, resets the run — which is precisely what a transient does.

    **The opening title card is not a view.** A recording's first frame always
    opens a capture, but when that capture still holds only the first frame,
    emitted at its own anchor, the second sample already cues away, *and* the
    frame is dark and desaturated — failing both of §4's pixel classes, where
    a real share is bright and camera video is saturated — it is the
    recorder's injected title slate, on screen for less than one sampling
    interval. The capture that replaces it takes its place — carrying the
    first-frame cue — and the slate frame is discarded rather than stored as
    a screen the meeting never showed (a slate is text-rich, so folding it
    into the next capture would hand the settle-timeout fallback exactly the
    frame this rule exists to unstore). A bright or saturated opening frame
    that lasted one sample is kept as its own capture (NFR8).

    **The settle rule decides which.** After a cue, the emitted frame is the
    first one whose change against its predecessor has fallen to
    ``settle_threshold`` or below *and* whose text has stopped painting in
    (``settle_text_growth_ratio`` — see :func:`has_settled` below, where the
    reason a pixel test alone is not enough is recorded). Emitting at the
    cue instead would systematically keep spinners and blank mid-load pages,
    because a blank page mid-load is the single largest possible difference
    from a populated one (§3). If the region has still not settled ``settle_timeout_seconds``
    after the cue, the capture is emitted anyway — tagged
    ``likely-transition``, never dropped (NFR8) — falling back to
    :func:`choose_representative`.

    Nothing is compared while a capture is still settling: the reference stays
    the previous capture's emitted shot until this one has something worth
    comparing against.
    """
    ordered = sorted(frames, key=lambda frame: frame.offset_ms)
    open_captures: list[_OpenCapture] = []
    settle_timeout_ms = config.settle_timeout_seconds * 1000.0

    def has_settled(index: int) -> bool:
        """Whether the region is done moving *and* done painting at ``index``.

        Pixel quiet alone is not enough at this sampling interval. A skeleton
        page holds perfectly still between two samples while its text has not
        arrived, so the pixel test calls it settled and the loading state
        becomes the stored screen — the very inversion the settle rule exists
        to prevent (§3). The cropped block count is already measured for the
        view-type rules, and it is the signal that is still climbing while a
        page paints, so a frame the next one overtakes by
        ``settle_text_growth_ratio`` has not settled yet.
        """
        frame = ordered[index]
        if frame.change_fraction_vs_previous > config.settle_threshold:
            return False
        following = index + 1
        if following >= len(ordered):
            return True
        arriving = ordered[following].block_count
        if arriving <= config.gallery_max_blocks:
            # Nothing meaningful is arriving. Without this the ratio test
            # cannot be satisfied at all from a textless frame — zero times
            # any ratio is still zero — so a camera gallery with a few blocks
            # of OCR noise after it would never settle and every such capture
            # would time out wearing a `likely-transition` tag it has not
            # earned. `gallery_max_blocks` is already the measured line for
            # "this frame carries no text".
            return True
        return frame.block_count * config.settle_text_growth_ratio >= arriving

    # Consecutive settled frames at or above `settled_change_threshold` from
    # the emitted shot. Reset by any cue, by an unsettled frame, and by a
    # frame back under the floor — the reset is what tells a page change
    # (arrives and stays) from a transient (spikes and returns).
    sustained = 0

    def open_capture(frame: FrameFacts, cue: str, index: int) -> None:
        opened = _OpenCapture(frame, [cue], settled=has_settled(index))
        opening = open_captures[-1].anchor
        if (
            cue == CUE_REGION_CHANGE
            and len(open_captures) == 1
            and len(open_captures[-1].frames) == 1
            and open_captures[-1].emitted is opening
            # A recorder slate is dark *and* desaturated — it fails both of
            # §4's classes at once, where a real share is bright and camera
            # video is saturated (demo-001's Teams title card measured white
            # 0.010, saturation 0.139). A bright or saturated opening frame
            # is a real view even if it lasted one sample, and stays its own
            # capture (NFR8).
            and opening.white_fraction <= config.camera_max_white_fraction
            and opening.mean_saturation < config.camera_min_saturation
        ):
            # The recording's opening frame was replaced by the very next
            # sample: on screen for less than one sampling interval, it is
            # the recorder's injected title slate, not a view the meeting
            # held. The replacing capture takes its place (and records the
            # first-frame door it arrived through); the slate frame itself is
            # discarded rather than folded in — a slate is the text-richest
            # frame in any transition window, so keeping it would hand the
            # settle-timeout fallback the very screen this exists to unstore.
            opened.cues.insert(0, CUE_FIRST_FRAME)
            open_captures[-1] = opened
        else:
            open_captures.append(opened)

    for index, frame in enumerate(ordered):
        if not open_captures:
            open_captures.append(
                _OpenCapture(frame, [CUE_FIRST_FRAME], settled=has_settled(index))
            )
            continue

        current = open_captures[-1]
        if current.emitted is None:
            # Still inside the transition burst this capture's cue opened.
            current.frames.append(frame)
            if has_settled(index):
                current.emitted = frame
            elif frame.offset_ms - current.anchor.offset_ms >= settle_timeout_ms:
                current.force_emit()
            continue

        change = change_since_emitted(current.emitted, frame)
        if change >= config.change_threshold:
            # A cue. The frame may already be quiet — that is what slow drift
            # looks like — in which case there is nothing to settle and it is
            # the emitted shot straight away.
            sustained = 0
            open_capture(frame, CUE_REGION_CHANGE, index)
            continue

        if (
            change >= config.settled_change_threshold
            and frame.change_fraction_vs_previous <= config.settle_threshold
        ):
            sustained += 1
            if sustained >= config.settled_change_frames:
                # The region went quiet at a new sustained distance from the
                # emitted shot: a same-chrome screen change too small for
                # `change_threshold` but too steady to be a transient.
                sustained = 0
                open_capture(frame, CUE_SETTLED_CHANGE, index)
                continue
        else:
            sustained = 0
        current.frames.append(frame)

    captures: list[Capture] = []
    # `pending`, not `open_capture`: that name now belongs to the nested
    # cue-handling function above, and shadowing it here would make the loop
    # body read as though it could still open captures.
    for ordinal, pending in enumerate(open_captures, start=1):
        if pending.emitted is None:
            # The frames ran out mid-transition: the timeout case arriving by
            # a different door, and the evidence for "this is a settled
            # screen" is equally absent, so it gets the same fallback and tag.
            pending.force_emit()
        # Not an `assert`: that vanishes under `python -O` and would let a
        # None reach signature_for as an AttributeError with no stage name on
        # it. force_emit always sets one, so this is unreachable by design.
        representative = pending.emitted
        if representative is None:  # pragma: no cover - force_emit always sets one
            raise RuntimeError(
                f"capture {ordinal} has no representative frame after force_emit"
            )
        signature = signature_for(representative)
        view_type, tags = classify_view_type(representative, config)
        if pending.timed_out:
            tags = (TAG_LIKELY_TRANSITION, *tags)
        captures.append(
            Capture(
                ordinal=ordinal,
                start_offset_ms=pending.frames[0].offset_ms,
                end_offset_ms=pending.frames[-1].offset_ms,
                frame_count=len(pending.frames),
                representative=representative,
                cues=tuple(pending.cues),
                view_type=view_type,
                signature=signature,
                tags=tags,
            )
        )
    return captures


def best_lineage_match(
    signature: str,
    candidates: Sequence[tuple[UUID | str, str]],
    config: ScreensConfig,
) -> UUID | str | None:
    """The existing screen this signature belongs to, or ``None``.

    ``candidates`` is ``(screen_id, signature)`` for every existing screen
    eligible for lineage. The best score at or above ``lineage_threshold``
    wins; ties break on the lowest id, so the answer does not depend on row
    order.
    """
    signature_tokens = tokens(signature)
    scored = (
        (jaccard(signature_tokens, tokens(candidate_signature)), str(screen_id), screen_id)
        for screen_id, candidate_signature in candidates
    )
    eligible = [item for item in scored if item[0] >= config.lineage_threshold]
    if not eligible:
        return None
    # Highest score wins; the lowest id breaks a tie, so the answer never
    # depends on the order the rows came back in.
    return min(eligible, key=lambda item: (-item[0], item[1]))[2]
