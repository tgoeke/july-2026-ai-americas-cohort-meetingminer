"""Ground-truth manifests: the recall denominator, validated in two layers.

One YAML file per scripted meeting under ``evals/ground-truth/`` declares what
the pipeline should produce (eval-design.md §1). The manifest is authored from
the meeting *script*; nothing here derives an anchor, an entry or a count from
pipeline output. A denominator built from what the extractor emitted cannot
contain a screen it missed, so it would report 100% recall while measuring
nothing.

Validation is two-layer on purpose:

* ``ground-truth.schema.json`` carries shape, enumerations and required-ness,
  including the ``archetype`` -> section binding.
* This module carries every rule that spans entries and that JSON Schema
  cannot express: anchors that are non-empty *after* normalization and unique,
  id uniqueness, ``qa.expected_moment`` resolving to a planted item,
  participant segments not repeating a moment, timestamps being real clock
  times inside ``duration_minutes``, and (across files) ``source_id`` and
  ``meeting.id`` uniqueness.

Both layers report through one :func:`validate_manifest` list, schema errors
first, so an author sees every problem in a single pass instead of peeling
them off one run at a time. That promise is why the loader rules are written
to survive schema-invalid input, and why they walk a section the archetype did
not declare rather than ignoring it.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

EVALS_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = EVALS_ROOT / "ground-truth.schema.json"
GROUND_TRUTH_DIR = EVALS_ROOT / "ground-truth"

SCHEMA: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(
    SCHEMA, format_checker=jsonschema.FormatChecker()
)

#: Which manifest section holds the expected captures, per archetype.
SECTION_FOR_ARCHETYPE = {"ui-demo": "screens", "slide-deck": "slides"}
#: The three planted kinds. One tuple, used by the id walk, the reference
#: resolver and the timestamp range check, so none of them can quietly cover
#: fewer kinds than the others.
PLANTED_SECTIONS = ("action_items", "decisions", "phrases")

#: What counts as a manifest file. Matched case-insensitively so a `.YAML`
#: written by a different editor is loaded rather than silently ignored — a
#: skipped manifest is a shrunken recall denominator that no test would notice.
MANIFEST_SUFFIXES = {".yaml", ".yml"}

_TIMESTAMP = re.compile(r"^(\d{2}):(\d{2}):(\d{2})$")
# Everything that is not a word character or whitespace. Replaced with a
# space rather than removed, so "tax-table" and "tax table" normalize alike.
# `\w` is unicode-aware here: accented letters survive, an underscore survives
# (it is a word character), and non-ASCII punctuation — em dashes, curly
# quotes — is folded away like the ASCII kind.
_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)


class GroundTruthError(Exception):
    """A manifest (or the corpus of them) failed validation, or could not be read."""


def parse_timestamp(value: Any, *, field: str = "timestamp") -> int:
    """``HH:MM:SS`` -> offset in whole seconds from meeting start.

    The schema already asserts the *shape*; this additionally rejects clock
    times that cannot exist, which a digit pattern cannot express: ``00:99:00``
    matches ``\\d{2}:\\d{2}:\\d{2}`` and is still not a time.
    """
    if not isinstance(value, str) or not _TIMESTAMP.match(value):
        raise GroundTruthError(f"{field}: {value!r} is not an HH:MM:SS timestamp")
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    if minutes > 59 or seconds > 59:
        raise GroundTruthError(
            f"{field}: {value!r} is not a real clock time"
            " (minutes and seconds are 00-59)"
        )
    return hours * 3600 + minutes * 60 + seconds


def normalize_anchor(text: str) -> str:
    """Fold an OCR anchor the way capture-recall matching will fold it.

    eval-design §2.1 lowercases, strips punctuation and collapses whitespace
    before comparing OCR text to an anchor. Uniqueness uses the identical
    normalization, so two anchors that check 2.1 could not tell apart are
    rejected at authoring time rather than silently colliding during a run.

    "Punctuation" is precisely ``[^\\w\\s]``: an underscore is a word
    character and survives, as do non-ASCII letters. Both are pinned by tests
    so the exact folding is a contract rather than an implementation detail —
    check 2.1 has to fold OCR text identically or the comparison is meaningless.
    """
    return " ".join(_PUNCTUATION.sub(" ", str(text).lower()).split())


@dataclass(frozen=True)
class Manifest:
    """One validated ground-truth file.

    Holds the parsed mapping rather than a mirrored field-per-key model: the
    schema is the contract, and a second hand-maintained copy of it would be
    one more place for the two to disagree.
    """

    data: Mapping[str, Any]
    path: Path | None = None

    @property
    def meeting(self) -> Mapping[str, Any]:
        return self.data["meeting"]

    @property
    def id(self) -> str:
        return self.meeting["id"]

    @property
    def source_id(self) -> str:
        return self.meeting["source_id"]

    @property
    def title(self) -> str:
        return self.meeting["title"]

    @property
    def archetype(self) -> str:
        return self.meeting["archetype"]

    @property
    def duration_minutes(self) -> float:
        return self.meeting["duration_minutes"]

    @property
    def section(self) -> str:
        """``screens`` or ``slides`` — whichever this archetype declares."""
        return SECTION_FOR_ARCHETYPE[self.archetype]

    @property
    def entries(self) -> tuple[Mapping[str, Any], ...]:
        """The slide or screen entries, whichever the archetype declares."""
        return tuple(self.data.get(self.section, ()))

    @property
    def participant_segments(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.data.get("participant_segments", ()))

    @property
    def anchors(self) -> tuple[str, ...]:
        """Every entry's anchor, normalized — the capture-recall match keys."""
        return tuple(normalize_anchor(entry["ocr_anchor"]) for entry in self.entries)

    @property
    def planted(self) -> Mapping[str, Any]:
        return self.data.get("planted", {})

    @property
    def qa(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.data.get("qa", ()))

    @property
    def expected_screenshot_count(self) -> int:
        """The recall denominator: slides (or screens) + participant segments.

        One formula, one implementation. Every check that needs the count asks
        this property rather than re-deriving it.
        """
        return len(self.entries) + len(self.participant_segments)


def _schema_messages(data: Any) -> list[str]:
    errors = sorted(VALIDATOR.iter_errors(data), key=lambda e: (list(e.path), e.message))
    return [
        f"{_location(e.path)}: {e.message}" if list(e.path) else e.message
        for e in errors
    ]


def _location(path: Iterable[Any]) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _capture_sections(data: Mapping[str, Any]) -> list[tuple[str, list[Any]]]:
    """Every slide/screen section actually present, the archetype's own first.

    A ui-demo manifest that also carries ``slides`` is already a schema error,
    but its slide entries can carry duplicate ids and anchors of their own. If
    the loader rules only walked the declared section, an author would fix the
    archetype and immediately be handed a second round of problems — which is
    exactly the one-pass promise :func:`validate_manifest` makes.
    """
    meeting = data.get("meeting")
    archetype = meeting.get("archetype") if isinstance(meeting, Mapping) else None
    declared = SECTION_FOR_ARCHETYPE.get(archetype if isinstance(archetype, str) else "")
    order = [declared] if declared else []
    order += [name for name in ("screens", "slides") if name != declared]
    return [(name, data[name]) for name in order if isinstance(data.get(name), list)]


def _identified(items: Iterable[Any], label: str) -> Iterator[tuple[str, Any]]:
    """Yield ``(location, item)`` for the mapping items of a list section."""
    for index, item in enumerate(items):
        if isinstance(item, Mapping):
            yield f"{label}[{index}]", item


def _entry_label(where: str, entry: Mapping[str, Any]) -> str:
    return f"{where} (id {entry.get('id', '?')!r})"


def _anchor_problems(sections: list[tuple[str, list[Any]]]) -> list[str]:
    """Anchors must survive normalization and be unique across the manifest."""
    problems: list[str] = []
    seen: dict[str, list[str]] = {}
    for section, entries in sections:
        for where, entry in _identified(entries, section):
            anchor = entry.get("ocr_anchor")
            if not isinstance(anchor, str) or not anchor:
                continue  # missing or empty-string is the schema's to report
                # Whitespace-only is NOT skipped: it clears `minLength: 1`, so
                # the schema never sees it, and it normalizes to nothing.
            normalized = normalize_anchor(anchor)
            if not normalized:
                # Clears `minLength: 1` and still cannot be matched: capture
                # recall compares normalized OCR text against this, so an
                # anchor of "---" or "..." makes the entry permanently unrecallable.
                problems.append(
                    f"{_entry_label(where, entry)}: ocr_anchor {anchor!r} normalizes"
                    " to nothing — it is punctuation only, so no capture can ever"
                    " match it"
                )
                continue
            seen.setdefault(normalized, []).append(_entry_label(where, entry))
    problems += [
        f"duplicate ocr_anchor after normalization ({normalized!r}):"
        f" {', '.join(wheres)} — anchors must be unique within a manifest,"
        " because capture-recall matching cannot tell two identical anchors apart"
        for normalized, wheres in seen.items()
        if len(wheres) > 1
    ]
    return problems


def _id_problems(
    data: Mapping[str, Any], sections: list[tuple[str, list[Any]]]
) -> list[str]:
    """Ids are unique across the whole manifest, not merely within a list.

    ``qa.expected_moment`` resolves against planted ids, and reports name
    entries by id, so one id meaning two things is ambiguous wherever it is
    read — not only inside the list that declared it twice.
    """
    seen: dict[str, list[str]] = {}
    labelled: list[tuple[str, Any]] = list(sections) + [("qa", data.get("qa"))]
    planted = data.get("planted")
    if isinstance(planted, Mapping):
        labelled += [
            (f"planted.{name}", planted.get(name)) for name in PLANTED_SECTIONS
        ]
    for label, items in labelled:
        if not isinstance(items, list):
            continue
        for where, item in _identified(items, label):
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id:
                seen.setdefault(item_id, []).append(where)
    return [
        f"duplicate id {item_id!r}: {', '.join(wheres)} — ids identify one thing"
        " per manifest"
        for item_id, wheres in seen.items()
        if len(wheres) > 1
    ]



def _planted_ids(data: Mapping[str, Any]) -> set[str]:
    planted = data.get("planted")
    if not isinstance(planted, Mapping):
        return set()
    ids: set[str] = set()
    for name in PLANTED_SECTIONS:
        items = planted.get(name)
        if isinstance(items, list):
            ids.update(
                item["id"]
                for _, item in _identified(items, name)
                if isinstance(item.get("id"), str)
            )
    return ids


def _reference_problems(data: Mapping[str, Any]) -> list[str]:
    known = _planted_ids(data)
    problems: list[str] = []
    qa = data.get("qa")
    if not isinstance(qa, list):
        return problems
    for where, entry in _identified(qa, "qa"):
        moment = entry.get("expected_moment")
        if isinstance(moment, str) and moment and moment not in known:
            problems.append(
                f"{_entry_label(where, entry)}: expected_moment"
                f" {moment!r} names no planted action item, decision or phrase"
            )
    return problems


def _segment_problems(data: Mapping[str, Any]) -> list[str]:
    """Two participant segments at one moment inflate the recall denominator.

    The count is the denominator, so a repeated ``at`` demands two captures of
    a single instant. Recall could then never reach the 1.0 threshold, and the
    run would fail against the ground truth rather than against the pipeline.
    """
    segments = data.get("participant_segments")
    if not isinstance(segments, list):
        return []
    seen: dict[str, list[str]] = {}
    for where, segment in _identified(segments, "participant_segments"):
        at = segment.get("at")
        if isinstance(at, str) and at:
            seen.setdefault(at, []).append(where)
    return [
        f"duplicate participant_segments at {at!r}: {', '.join(wheres)} — one"
        " moment is one expected capture, so repeating it inflates the recall"
        " denominator and makes 100% unreachable"
        for at, wheres in seen.items()
        if len(wheres) > 1
    ]


def _timestamps(
    data: Mapping[str, Any], sections: list[tuple[str, list[Any]]]
) -> list[tuple[str, Any]]:
    """Every ``(field path, value)`` a manifest timestamps, in report order."""
    stamped: list[tuple[str, Any]] = [
        (f"{where}.shown_at", entry["shown_at"])
        for section, entries in sections
        for where, entry in _identified(entries, section)
        if "shown_at" in entry
    ]
    segments = data.get("participant_segments")
    if isinstance(segments, list):
        stamped += [
            (f"{where}.at", entry["at"])
            for where, entry in _identified(segments, "participant_segments")
            if "at" in entry
        ]
    planted = data.get("planted")
    if isinstance(planted, Mapping):
        for name in PLANTED_SECTIONS:
            items = planted.get(name)
            if isinstance(items, list):
                stamped += [
                    (f"{where}.at", entry["at"])
                    for where, entry in _identified(items, f"planted.{name}")
                    if "at" in entry
                ]
    return stamped


def _timestamp_problems(
    data: Mapping[str, Any], sections: list[tuple[str, list[Any]]]
) -> list[str]:
    meeting = data.get("meeting")
    duration = meeting.get("duration_minutes") if isinstance(meeting, Mapping) else None
    problems: list[str] = []
    limit = None
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        duration_seconds = float(duration) * 60
        if math.isfinite(duration_seconds):
            limit = int(duration_seconds)
        else:
            problems.append(
                f"meeting.duration_minutes: {duration!r} must be a finite number"
            )
    for field, value in _timestamps(data, sections):
        try:
            offset = parse_timestamp(value, field=field)
        except GroundTruthError as exc:
            problems.append(str(exc))
            continue
        if limit is not None and offset > limit:
            problems.append(
                f"{field}: {value!r} is past the end of the meeting"
                f" (duration_minutes {duration})"
            )
    return problems


def validate_manifest(data: Any) -> list[str]:
    """Every problem with one manifest: schema errors first, then loader rules.

    Returns messages rather than raising, so a caller can report all of them.
    The loader rules are written to tolerate schema-invalid input — an author
    with a missing field still gets told about their duplicate anchor.
    """
    problems = _schema_messages(data)
    if not isinstance(data, Mapping):
        return problems
    sections = _capture_sections(data)
    problems += _anchor_problems(sections)
    problems += _id_problems(data, sections)
    problems += _reference_problems(data)
    problems += _segment_problems(data)
    problems += _timestamp_problems(data, sections)
    return problems


def _report(name: str, problems: list[str]) -> str:
    return f"{name} is not a valid ground-truth manifest:\n  - " + "\n  - ".join(problems)


def load_manifest(path: Path) -> Manifest:
    """Parse and validate one manifest file, or raise :class:`GroundTruthError`.

    Every failure mode arrives as one error type: an unreadable file, a broken
    symlink, non-UTF-8 bytes and malformed YAML are all ways ground truth can
    be missing, and a caller walking a directory should not need a different
    ``except`` clause for each.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise GroundTruthError(f"{path.name}: cannot be read: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise GroundTruthError(f"{path.name}: not valid YAML: {exc}") from exc
    problems = validate_manifest(data)
    if problems:
        raise GroundTruthError(_report(path.name, problems))
    return Manifest(data=data, path=path)


def manifest_paths(directory: Path | None = None) -> list[Path]:
    """Every manifest file in the ground-truth directory, in a stable order.

    Flat by design: manifests are a single set, not a tree, and a nested
    directory would be a filing decision nobody has made. A missing or
    unreadable directory is reported as a :class:`GroundTruthError` like every
    other way ground truth can fail to arrive.
    """
    directory = Path(directory) if directory is not None else GROUND_TRUTH_DIR
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        raise GroundTruthError(
            f"cannot read the ground-truth directory {directory}: {exc}"
        ) from exc
    return sorted(
        path
        for path in entries
        if path.suffix.lower() in MANIFEST_SUFFIXES
        and (path.is_file() or path.is_symlink())
    )


def load_all(directory: Path | None = None) -> list[Manifest]:
    """Load every manifest in a directory and apply the corpus-level rules.

    Two manifests claiming one ``source_id`` would both match the same
    ingested meeting, and two claiming one ``meeting.id`` would be
    indistinguishable in a report. Neither is expressible in a per-file
    schema, so both live here. All problems across all files are collected
    into one error.
    """
    problems: list[str] = []
    manifests: list[Manifest] = []
    for path in manifest_paths(directory):
        try:
            manifests.append(load_manifest(path))
        except GroundTruthError as exc:
            problems.append(str(exc))

    for key, getter in (("source_id", lambda m: m.source_id), ("meeting.id", lambda m: m.id)):
        claims: dict[str, list[str]] = {}
        for manifest in manifests:
            name = manifest.path.name if manifest.path else manifest.id
            claims.setdefault(getter(manifest), []).append(name)
        problems += [
            f"duplicate {key} {value!r} declared by {', '.join(sorted(names))}"
            for value, names in claims.items()
            if len(names) > 1
        ]

    if problems:
        raise GroundTruthError(
            "the ground-truth corpus is invalid:\n" + "\n".join(problems)
        )
    return manifests
