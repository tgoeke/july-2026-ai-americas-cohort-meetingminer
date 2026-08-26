"""The row -> Capture mapping, store-free.

`corpus.py` is the one module that needs a live Postgres, and its SQL cannot
be asserted without one. Its *mapping* can: `capture_from_row` is a pure
function over a row tuple, and it is where a silent corruption would live —
swapping the two nullable columns would make every capture look textless and
every textless capture look defective, and no check would notice, because both
still type-check as "something falsy".

These tests are why `CAPTURE_COLUMNS` exists as a named contract rather than as
four positional indexes inside a comprehension.
"""

from __future__ import annotations

import pytest

from evals.harness.corpus import CAPTURE_COLUMNS, CorpusQueryError, capture_from_row

FRAME_ID = "01a0170c-bb04-78c2-832a-4fc2bc555551"


def row(
    ordinal: int = 1,
    view_type: str = "ui-screen",
    representative_frame_id: str | None = FRAME_ID,
    ocr_text: str | None = "Order Search Results",
) -> tuple[object, ...]:
    """One `screenshot` row in the column order `_CAPTURES` selects."""
    return (ordinal, view_type, representative_frame_id, ocr_text)


def test_the_columns_map_to_the_fields_that_carry_their_meaning() -> None:
    capture = capture_from_row(row(ordinal=7, view_type="slide"))
    assert capture.ordinal == 7
    assert capture.view_type == "slide"
    assert capture.ocr_text == "Order Search Results"
    assert capture.has_representative_frame is True


def test_a_swapped_pair_of_columns_does_not_map_cleanly() -> None:
    """The regression this file exists for: the frame id and the text are both
    nullable strings, so swapping them is invisible to every other test."""
    swapped = capture_from_row((1, "ui-screen", "Order Search Results", FRAME_ID))
    assert swapped.ocr_text == FRAME_ID, "the mapping is positional by contract"
    assert capture_from_row(row()).ocr_text != FRAME_ID


def test_a_cleared_representative_frame_yields_no_text_and_no_frame() -> None:
    """A `frames` rerun sets `representative_frame_id` NULL; the LEFT JOIN then
    contributes no `frame_ocr.text`."""
    capture = capture_from_row(row(representative_frame_id=None, ocr_text=None))
    assert capture.has_representative_frame is False
    assert capture.ocr_text is None
    assert capture.has_ocr_text is False


def test_a_frame_with_no_ocr_row_keeps_the_frame_but_has_no_text() -> None:
    """The other defect, and it must read differently: the `screens` stage
    chose a frame the `ocr` stage never covered."""
    capture = capture_from_row(row(ocr_text=None))
    assert capture.has_representative_frame is True
    assert capture.has_ocr_text is False


def test_an_empty_recognized_text_is_text_not_a_missing_row() -> None:
    """A camera gallery legitimately recognizes nothing. `""` is a measurement;
    `None` is a defect, and collapsing the two would hide a broken `ocr` run."""
    capture = capture_from_row(row(ocr_text=""))
    assert capture.ocr_text == ""
    assert capture.has_ocr_text is True
    assert capture.normalized_text == ""


def test_the_text_is_carried_unfolded_for_the_checks_to_fold() -> None:
    """`corpus.py` maps rows; it runs no algorithm. Folding here would put half
    of check 2.1's comparison in the module that opens the connection."""
    capture = capture_from_row(row(ocr_text="ORDER  Search-Results!"))
    assert capture.ocr_text == "ORDER  Search-Results!"
    assert capture.normalized_text == "order search results"


@pytest.mark.parametrize("width", [3, 5])
def test_a_row_of_the_wrong_width_is_a_named_error(width: int) -> None:
    """Not an IndexError or a silent short unpack: the query and the mapping
    having drifted apart is a thing to say out loud."""
    with pytest.raises(CorpusQueryError) as caught:
        capture_from_row(tuple(range(width)))
    assert ", ".join(CAPTURE_COLUMNS) in str(caught.value)
