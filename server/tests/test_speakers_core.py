"""Speaker identity: normalization, scoping, and the never-guess rule.

Each case below is a label shape observed in transcript data: a `Last, First`
label alongside the same person's bare first name, two people sharing a first
name, and an unresolvable `Speaker N` placeholder.
"""

from __future__ import annotations

import pytest

from meetingminer.pipeline.speakers import (
    AMBIGUOUS,
    PLACEHOLDER,
    RESOLVED,
    UNRESOLVED,
    MAIL_NAMESPACE,
    NAME_NAMESPACE,
    identity_key_for,
    is_placeholder_label,
    normalize_display_name,
    resolve_label,
    roster_from_labels,
)

# One meeting's roster, as *match* keys — normalized display names. A
# transcript label never carries a mail, so this is the space it resolves in.
ROSTER = (
    "timothy goeke",
    "ellis whitmore",
    "kendall kingsley",
    "kendall inglewood",
    "oakleylangmere",
    "tobin dunmore",
)


# --- normalization ---------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Goeke, Timothy", "timothy goeke"),
        ("Timothy Goeke", "timothy goeke"),
        ("GOEKE,   TIMOTHY", "timothy goeke"),
        # Parenthetical qualifiers are stripped (AD-5).
        ("Dunmore, Tobin (CNTR)", "tobin dunmore"),
        ("Fenwick, Peyton (Fenwick, Peyton)", "peyton fenwick"),
        # The whole label is the qualifier — an observed transcript shape.
        ("(Fenwick, Peyton)", "peyton fenwick"),
        ("Calloway, Frankie Sage", "frankie sage calloway"),
        # A login-shaped token is a name here: there is no directory to ask.
        ("oakleylangmere", "oakleylangmere"),
    ],
)
def test_normalization_reorders_strips_and_folds(label: str, expected: str) -> None:
    assert normalize_display_name(label) == expected
    # With no mail to key on, identity falls back to the normalized name — in
    # its own namespace, so it can never collide with a mail-keyed identity.
    assert identity_key_for(label) == NAME_NAMESPACE + expected


def test_last_first_and_first_last_reach_one_identity_key() -> None:
    assert identity_key_for("Whitmore, Ellis") == identity_key_for("Ellis Whitmore")


# --- identity key: mail first, name as the documented fallback -------------


def test_mail_wins_over_the_name_when_the_graph_supplies_one() -> None:
    """Nearly every person-row carries a mail; it is the stable key."""
    key = identity_key_for("Goeke, Timothy", "Timothy.Goeke@contoso.com")
    assert key == MAIL_NAMESPACE + "timothy.goeke@contoso.com"
    # The same human written three ways reaches one identity.
    assert identity_key_for("Tim Goeke", "timothy.goeke@contoso.com") == key
    assert identity_key_for("Timothy Goeke", "TIMOTHY.GOEKE@CONTOSO.COM") == key


def test_two_people_sharing_a_name_stay_two_identities() -> None:
    """The whole point: a name-only key would silently merge these two humans,
    and a silent merge is the wrong attribution never-guess exists to prevent.
    """
    first = identity_key_for("Kingsley, Kendall", "kendall.kingsley@contoso.com")
    second = identity_key_for("Kingsley, Kendall", "kendall.kingsley2@contoso.com")
    assert first != second


def test_a_row_without_mail_falls_back_to_the_normalized_name() -> None:
    """External attendees carry `unresolved: true` and an empty mail."""
    for empty in (None, "", "   "):
        assert identity_key_for("Micah Maplewood", empty) == NAME_NAMESPACE + "micah maplewood"


def test_the_employee_number_login_is_not_treated_as_a_name() -> None:
    """It is a different field from `mail`, but it is still mail-shaped: if a
    source ever supplies it here it must not silently become a name key."""
    key = identity_key_for("Goeke, Timothy", "58231@contoso.com")
    assert key == MAIL_NAMESPACE + "58231@contoso.com"
    assert key != identity_key_for("Goeke, Timothy", "timothy.goeke@contoso.com")


def test_the_two_key_spaces_cannot_collide() -> None:
    mail_key = identity_key_for("anyone", "timothy.goeke@contoso.com")
    name_key = identity_key_for("timothy.goeke@contoso.com")
    assert mail_key != name_key
    assert mail_key.startswith(MAIL_NAMESPACE)
    assert name_key.startswith(NAME_NAMESPACE)


def test_a_label_normalizing_to_nothing_has_no_identity_key() -> None:
    assert identity_key_for("") == ""
    assert identity_key_for("   ") == ""


# --- placeholders ----------------------------------------------------------


@pytest.mark.parametrize("label", ["Speaker 2", "Speaker 8", "speaker8", "Unknown", "unidentified speaker"])
def test_placeholder_labels_are_recognized(label: str) -> None:
    assert is_placeholder_label(label)
    assert resolve_label(label, ROSTER).status == PLACEHOLDER


def test_a_real_name_is_not_a_placeholder() -> None:
    assert not is_placeholder_label("Goeke, Timothy")
    assert not is_placeholder_label("Kendall")


def test_placeholders_never_enter_a_transcript_derived_roster() -> None:
    roster = roster_from_labels(["Whitmore, Ellis", "Speaker 8", None, "  ", "Ellis"])
    assert roster == ("ellis whitmore", "ellis")


# --- resolution, scoped to one meeting's roster ----------------------------


def test_exact_and_reordered_labels_resolve() -> None:
    assert resolve_label("Goeke, Timothy", ROSTER).match_key == "timothy goeke"
    assert resolve_label("Timothy Goeke", ROSTER).match_key == "timothy goeke"


def test_bare_first_name_with_one_roster_match_resolves() -> None:
    resolution = resolve_label("Ellis", ROSTER)
    assert resolution.status == RESOLVED
    assert resolution.match_key == "ellis whitmore"


def test_bare_first_name_with_two_roster_matches_is_ambiguous() -> None:
    """Two Kendalls: the never-guess rule refuses rather than taking the first."""
    resolution = resolve_label("Kendall", ROSTER)
    assert resolution.status == AMBIGUOUS
    assert resolution.match_key is None
    assert set(resolution.candidates) == {"kendall kingsley", "kendall inglewood"}


def test_initials_resolve_only_inside_the_roster() -> None:
    assert resolve_label("T.G.", ROSTER).match_key == "timothy goeke"
    assert resolve_label("T G", ROSTER).match_key == "timothy goeke"
    # A single bare initial identifies nobody.
    assert resolve_label("T", ROSTER).status == UNRESOLVED


def test_a_label_matching_nobody_is_unresolved() -> None:
    resolution = resolve_label("Langmere, Oakley", ROSTER)
    assert resolution.status == UNRESOLVED
    assert resolution.match_key is None
    assert resolution.candidates == ()


def test_a_shortened_first_name_is_not_guessed_at() -> None:
    """`Tim Goeke` is not asserted to be `Goeke, Timothy` — that is a guess."""
    assert resolve_label("Tim Goeke", ROSTER).status == UNRESOLVED


def test_resolution_is_scoped_to_the_roster_it_is_given() -> None:
    """Corpus-wide `Ellis` is ambiguous; inside one roster it usually is not."""
    two_ellises = ("ellis whitmore", "ellis westbrook")
    assert resolve_label("Ellis", two_ellises).status == AMBIGUOUS
    assert resolve_label("Ellis", ("ellis whitmore",)).status == RESOLVED


def test_no_label_at_all_is_a_placeholder() -> None:
    assert resolve_label(None, ROSTER).status == PLACEHOLDER
    assert resolve_label("   ", ROSTER).status == PLACEHOLDER


@pytest.mark.parametrize("label", ["Kendall", "Langmere, Oakley", "Speaker 8", None])
def test_only_a_resolved_label_ever_names_a_participant(label: str | None) -> None:
    """unresolved / ambiguous / placeholder never yield an identity."""
    assert resolve_label(label, ROSTER).match_key is None
