"""The query side of the search projection: the highlight parser and the request body.

Store-free on purpose. Everything here is a decision made *before* the store
is called or *after* it has answered, and those are the two places a
user-visible search bug hides where no integration test would find it: a
snippet that drops a character, a hybrid block sent without a vector, an index
that should never have been queried.

The store-backed half — that these parameters actually rank the right moments
against Meilisearch 1.53 — lives in `test_api_search.py`.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from meetingminer.config import AppConfig
from meetingminer.projections.publish_gate import ARTIFACTS_INDEX
from meetingminer.projections.query import (
    ARTIFACT_SEARCHABLE_INDEXES,
    ARTIFACT_SNIPPET_ATTRIBUTES,
    HIGHLIGHT_POST,
    HIGHLIGHT_PRE,
    SEARCHABLE_INDEXES,
    SNIPPET_ATTRIBUTES,
    ArtifactHit,
    MomentHit,
    MomentSearchResult,
    SnippetRun,
    _snippet_of,
    apply_semantic_floor,
    build_filter,
    build_search_parameters,
    build_artifact_search_parameters,
    merge_search_lanes,
    parse_highlight_runs,
    search_artifacts,
    search_moments,
)
from meetingminer.projections.stores import (
    CHUNKS_INDEX,
    MOMENTS_INDEX,
    ProjectionError,
)

PRE, POST = HIGHLIGHT_PRE, HIGHLIGHT_POST


def mark(text: str) -> str:
    """One highlighted term, as Meilisearch would return it."""
    return f"{PRE}{text}{POST}"


# --- the allow-list -------------------------------------------------------


def test_only_the_moments_index_is_searchable() -> None:
    assert SEARCHABLE_INDEXES == (MOMENTS_INDEX,)


def test_the_artifacts_index_has_its_own_keyword_only_lane() -> None:
    """NFR7 on the query side, rewritten by story 4.4: published artifacts
    *do* surface now, but only through the keyword-only artifact lane, whose
    allow-list holds the artifacts index alone — the hybrid lane's allow-list
    still never names it, so no artifact can ride the vector lane, and every
    artifact query pins `state = 'published'` in its own filter (asserted
    below in the parameter tests)."""
    assert ARTIFACTS_INDEX not in SEARCHABLE_INDEXES
    assert ARTIFACT_SEARCHABLE_INDEXES == (ARTIFACTS_INDEX,)


def test_the_chunks_index_is_not_searchable_from_here() -> None:
    """Chunk-granularity retrieval is story 3.3's synthesis leg, not `/search`."""
    assert CHUNKS_INDEX not in SEARCHABLE_INDEXES


# --- the highlight parser -------------------------------------------------


def test_an_absent_formatted_value_yields_no_runs() -> None:
    assert parse_highlight_runs(None) == ()
    assert parse_highlight_runs("") == ()


def test_plain_text_is_one_unhighlighted_run() -> None:
    assert parse_highlight_runs("nothing matched here") == (
        SnippetRun("nothing matched here", False),
    )


def test_a_match_splits_the_text_into_runs() -> None:
    runs = parse_highlight_runs(f"and the {mark('purchase')} order")
    assert runs == (
        SnippetRun("and the ", False),
        SnippetRun("purchase", True),
        SnippetRun(" order", False),
    )
    # The plain snippet is the concatenation, unchanged.
    assert "".join(run.text for run in runs) == "and the purchase order"


def test_adjacent_matches_stay_separate_runs() -> None:
    """Two consecutive matched terms are two runs, not one merged one.

    Meilisearch marks each matched term individually, and a renderer that
    wraps every highlighted run reproduces exactly what the store meant. The
    assertion pins that the parser does not helpfully coalesce them, because
    coalescing across a separator is how "purchase order" would become one run
    that also swallowed the space between them.
    """
    runs = parse_highlight_runs(f"{mark('purchase')}{mark('order')}")
    assert runs == (SnippetRun("purchase", True), SnippetRun("order", True))


def test_a_match_at_each_end_needs_no_surrounding_plain_run() -> None:
    assert parse_highlight_runs(mark("sftp")) == (SnippetRun("sftp", True),)


def test_an_empty_match_produces_no_run() -> None:
    assert parse_highlight_runs(f"a{PRE}{POST}b") == (
        SnippetRun("a", False),
        SnippetRun("b", False),
    )


def test_an_unclosed_sentinel_is_literal_text() -> None:
    """The Design Notes assumption, attacked.

    U+E000 is a private-use code point no producer in this system emits — but
    "no known producer emits it" is not "it cannot occur". An opener the store
    never closed can only have come from the document, so it is the character
    it is. Raising here would turn one stray code point in one OCR run into a
    500 on every query that matched it.
    """
    runs = parse_highlight_runs(f"a literal {PRE} sits here")
    assert runs == (SnippetRun(f"a literal {PRE} sits here", False),)


def test_a_closer_with_no_opener_is_literal_text() -> None:
    runs = parse_highlight_runs(f"stray {POST} closer")
    assert runs == (SnippetRun(f"stray {POST} closer", False),)


def test_a_source_sentinel_beside_a_real_match_keeps_both() -> None:
    """The mixed case: literal sentinel *and* a genuine highlight in one value."""
    runs = parse_highlight_runs(f"{PRE} then {mark('purchase')} order")
    assert runs == (
        SnippetRun(f"{PRE} then ", False),
        SnippetRun("purchase", True),
        SnippetRun(" order", False),
    )


def test_no_run_text_ever_contains_a_delimiter_it_consumed() -> None:
    runs = parse_highlight_runs(f"the {mark('sftp')} feed")
    for run in runs:
        if run.highlighted:
            assert PRE not in run.text and POST not in run.text


# --- snippet attribute selection -----------------------------------------


def test_the_snippet_comes_from_the_attribute_that_actually_matched() -> None:
    """A moment matched only through its screen's OCR text shows *that* text.

    Meilisearch crops every attribute it is asked to crop, matched or not, so
    without this preference a hit found via `screenText` would be shown the
    opening words of its transcript — a snippet that does not contain the term
    the user typed.
    """
    runs = _snippet_of(
        {
            "text": "Everybody, good morning.",
            "screenText": f"Vendor Portal {mark('PO-40199')} dashboard",
        }
    )
    assert any(run.highlighted for run in runs)
    assert "".join(run.text for run in runs) == "Vendor Portal PO-40199 dashboard"


def test_the_transcript_wins_when_both_attributes_matched() -> None:
    runs = _snippet_of(
        {
            "text": f"the {mark('purchase')} order",
            "screenText": f"a {mark('purchase')} screen",
        }
    )
    assert "".join(run.text for run in runs) == "the purchase order"


def test_an_unmatched_hit_falls_back_to_the_first_non_empty_attribute() -> None:
    """A pure semantic hit marks no term; it still deserves a snippet."""
    runs = _snippet_of({"text": "", "screenText": "Vendor Portal dashboard"})
    assert runs == (SnippetRun("Vendor Portal dashboard", False),)


def test_a_speaker_match_produces_a_highlighted_run_from_the_array() -> None:
    """AC1's "a mention": `speakers` is an array, so `_formatted` is one too.

    A query that only matches a name would otherwise show the opening of the
    transcript with nothing marked — a hit the user cannot see the reason for.
    """
    runs = _snippet_of(
        {
            "text": "Everybody, good morning.",
            "speakers": ["Goeke, Timothy", f"{mark('Whitmore')}, Ellis"],
        }
    )
    assert any(run.highlighted for run in runs)
    assert "".join(run.text for run in runs) == "Whitmore, Ellis"


def test_a_meeting_name_match_produces_a_highlighted_run_from_the_title() -> None:
    """AC1's "a meeting name"."""
    runs = _snippet_of(
        {"text": "Everybody, good morning.", "title": f"{mark('Data')} Hub Demo"}
    )
    assert any(run.highlighted for run in runs)
    assert "".join(run.text for run in runs) == "Data Hub Demo"


def test_the_transcript_still_wins_over_the_metadata_attributes() -> None:
    """Preference order is the point of the tuple, not an accident of it.

    When the words matched both the passage and the header, the passage is
    what tells the user why this moment answers them.
    """
    runs = _snippet_of(
        {
            "text": f"the {mark('purchase')} order",
            "speakers": [f"{mark('purchase')}, Ellis"],
            "title": f"{mark('purchase')} review",
        }
    )
    assert "".join(run.text for run in runs) == "the purchase order"


def test_a_hit_with_no_formatted_block_has_no_snippet() -> None:
    assert _snippet_of(None) == ()
    assert _snippet_of({}) == ()


# --- the request body -----------------------------------------------------


def test_a_vector_produces_a_hybrid_block_naming_the_configured_embedder(
    app_config: AppConfig,
) -> None:
    parameters = build_search_parameters(
        app_config, limit=10, offset=0, query_vector=(0.1, 0.2, 0.3)
    )
    assert parameters["hybrid"] == {
        "semanticRatio": app_config.settings.api.search.semantic_ratio,
        "embedder": "default",
    }
    assert parameters["vector"] == [0.1, 0.2, 0.3]


def test_no_vector_means_no_hybrid_block_at_all(app_config: AppConfig) -> None:
    """The store cannot embed for us — AD-4 keeps its embedder `userProvided`.

    So a hybrid block with no vector would be asking Meilisearch to do the one
    thing this architecture forbids it. Keyword-only is the degraded path, and
    it is expressed by the absence of the block, not by a zero ratio.
    """
    parameters = build_search_parameters(app_config, limit=10, offset=0)
    assert "hybrid" not in parameters
    assert "vector" not in parameters


def test_the_request_retrieves_ids_only(app_config: AppConfig) -> None:
    """AD-6: every other field on the wire is re-read from Postgres."""
    parameters = build_search_parameters(app_config, limit=10, offset=0)
    assert parameters["attributesToRetrieve"] == ["id"]


def test_the_highlight_tags_are_the_private_use_sentinels(
    app_config: AppConfig,
) -> None:
    parameters = build_search_parameters(app_config, limit=10, offset=0)
    # Pinned as code points, not as the module's own constants: a test that
    # compares a constant to itself would pass through a silent change from
    # a private-use sentinel back to HTML tags.
    assert parameters["highlightPreTag"] == "\ue000"
    assert parameters["highlightPostTag"] == "\ue001"
    assert (HIGHLIGHT_PRE, HIGHLIGHT_POST) == ("\ue000", "\ue001")
    # No markup reaches the wire, which is the whole point of the sentinels.
    assert "<" not in parameters["highlightPreTag"]


def test_the_snippet_attributes_are_both_highlighted_and_cropped(
    app_config: AppConfig,
) -> None:
    parameters = build_search_parameters(app_config, limit=10, offset=0)
    assert parameters["attributesToHighlight"] == list(SNIPPET_ATTRIBUTES)
    assert parameters["attributesToCrop"] == list(SNIPPET_ATTRIBUTES)
    assert parameters["cropLength"] == app_config.settings.api.search.crop_length


def test_the_snippet_attributes_are_exactly_the_searchable_ones(
    app_config: AppConfig,
) -> None:
    """Every searchable attribute must also be a highlightable one.

    Both directions matter and both are bugs. Cropping an attribute the index
    does not search can never produce a highlight; searching an attribute the
    request does not ask to be highlighted produces a hit with *no* highlighted
    run — the user is shown a result and no reason for it. AC1's three input
    kinds match across all four: a topic and OCR text through `text` and
    `screenText`, a mention through `speakers`, a meeting name through `title`.
    """
    searchable = app_config.settings.projections.search.moments.searchable_attributes
    assert list(SNIPPET_ATTRIBUTES) == searchable


def test_limit_and_offset_are_passed_through(app_config: AppConfig) -> None:
    parameters = build_search_parameters(app_config, limit=7, offset=14)
    assert parameters["limit"] == 7
    assert parameters["offset"] == 14


def test_an_unscoped_query_carries_no_filter(app_config: AppConfig) -> None:
    assert "filter" not in build_search_parameters(app_config, limit=5, offset=0)


def test_a_meeting_scope_filters_on_the_meeting_id(app_config: AppConfig) -> None:
    meeting_id = uuid4()
    parameters = build_search_parameters(
        app_config, limit=5, offset=0, meeting_id=meeting_id
    )
    assert parameters["filter"] == f'meetingId = "{meeting_id}"'


def test_both_scopes_combine_with_and(app_config: AppConfig) -> None:
    meeting_id = uuid4()
    parameters = build_search_parameters(
        app_config, limit=5, offset=0, meeting_id=meeting_id, corpus="scripted"
    )
    assert parameters["filter"] == (
        f'meetingId = "{meeting_id}" AND corpus = "scripted"'
    )


def test_a_meeting_id_is_round_tripped_through_uuid_before_interpolation() -> None:
    """A filter expression is not a place to trust a string's shape."""
    with pytest.raises(ValueError):
        build_filter("not-a-uuid", None)  # type: ignore[arg-type]


def test_a_corpus_scope_that_is_not_a_bare_word_is_refused() -> None:
    with pytest.raises(ValueError, match="bare word"):
        build_filter(None, 'scripted" OR corpus = "real')


def test_a_valid_uuid_string_is_accepted_by_the_filter_builder() -> None:
    meeting_id = uuid4()
    assert build_filter(str(meeting_id), None) == f'meetingId = "{meeting_id}"'


# --- the result value object ---------------------------------------------


def test_an_empty_result_is_not_a_missing_index() -> None:
    """ "No matches" and "never projected" are different answers.

    Collapsing them is exactly the silent zero the SPEC Constraints forbid:
    an empty corpus reports nothing found for the same reason a nonsense query
    does, and nobody discovers the projection never ran.
    """
    empty = MomentSearchResult(hits=(), estimated_total=0, limit=10, offset=0)
    assert empty.index_missing is False
    missing = MomentSearchResult(
        hits=(), estimated_total=0, limit=10, offset=0, index_missing=True
    )
    assert missing.index_missing is True


def test_a_hit_carries_a_uuid_moment_id_and_nothing_citation_shaped() -> None:
    """The module returns ranking, not citations (AD-6)."""
    from meetingminer.projections.query import MomentHit

    hit = MomentHit(moment_id=UUID(int=1), snippet=(), score=0.5)
    fields = set(vars(hit))
    assert fields == {"moment_id", "snippet", "score"}


# --- the semantic floor ---------------------------------------------------


def hit(score: float | None) -> MomentHit:
    return MomentHit(moment_id=uuid4(), snippet=(), score=score)


def test_the_floor_applies_to_the_separate_semantic_lane() -> None:
    weak, strong = hit(0.66), hit(0.80)
    kept, dropped = apply_semantic_floor((weak, strong), floor=0.75)
    assert kept == (strong,)
    assert dropped == 1


def test_a_query_matching_nothing_can_come_back_empty() -> None:
    """Without this, the vector lane makes an empty result set unreachable."""
    kept, dropped = apply_semantic_floor((hit(0.65), hit(0.67), hit(0.70)), floor=0.75)
    assert kept == ()
    assert dropped == 3


def test_a_zero_floor_disables_the_filter_entirely() -> None:
    """0.0 is a legitimate configuration: keep every neighbour the store found."""
    hits = (hit(0.1), hit(0.2))
    kept, dropped = apply_semantic_floor(hits, floor=0.0)
    assert kept == hits
    assert dropped == 0


def test_an_unscored_hit_is_kept_rather_than_discarded() -> None:
    """A hit with no score means the client shape changed, not that it is weak."""
    unscored = hit(None)
    kept, dropped = apply_semantic_floor((unscored,), floor=0.75)
    assert kept == (unscored,)
    assert dropped == 0


def test_keyword_hits_survive_when_semantic_match_count_exceeds_a_page() -> None:
    """No exhaustive store count can make a keyword hit eligible for flooring."""
    keyword_low = hit(0.15)
    semantic_weak = hit(0.5)
    semantic_kept, _dropped = apply_semantic_floor((semantic_weak,), floor=0.75)
    assert merge_search_lanes((keyword_low,), semantic_kept, 0.3, 1) == (keyword_low,)


def test_the_floor_is_a_configured_value_not_a_constant(app_config: AppConfig) -> None:
    floor = app_config.settings.api.search.semantic_score_floor
    assert 0.0 <= floor <= 1.0


# --- what search_moments makes of the store's answer ----------------------


class _FakeIndex:
    """One index handle that answers keyword then semantic canned responses."""

    def __init__(
        self, keyword_response: dict, semantic_response: dict | None = None
    ) -> None:
        self.keyword_response = keyword_response
        self.semantic_response = semantic_response or keyword_response
        self.calls: list[tuple[str, dict]] = []

    def search(self, query: str, parameters: dict) -> dict:
        self.calls.append((query, parameters))
        return (
            self.semantic_response if "vector" in parameters else self.keyword_response
        )


class _FakeMeili:
    """Enough of a `meilisearch.Client` to answer one moments query.

    A canned response rather than the real store: what is under test here is
    what this module *makes of* an answer, and the shapes that matter (a
    document with an unusable id, a page the floor empties) are ones the real
    store will not produce on demand.
    """

    def __init__(
        self, keyword_response: dict, semantic_response: dict | None = None
    ) -> None:
        self.moments = _FakeIndex(keyword_response, semantic_response)

    def index(self, name: str) -> _FakeIndex:
        assert name == MOMENTS_INDEX, name
        return self.moments


def test_a_hit_whose_id_is_not_a_uuid_is_the_same_named_refusal(
    app_config: AppConfig,
) -> None:
    """A document that cannot become a citation is loud, whichever way it fails.

    A missing id already raised `ProjectionError`; an id that is present but
    unparseable used to escape as a bare `ValueError`, which the api had no
    branch for and which surfaced as an opaque 500 with a traceback. Same
    failure, same named refusal.
    """
    meili = _FakeMeili({"hits": [{"id": "not-a-uuid"}], "estimatedTotalHits": 1})
    with pytest.raises(ProjectionError, match="not a UUID"):
        search_moments(meili, app_config, query="purchase order", limit=10)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "response, message",
    [
        (
            {"hits": ["not-a-document"], "estimatedTotalHits": 1},
            "hit in an invalid shape",
        ),
        (
            {
                "hits": [{"id": str(uuid4()), "_rankingScore": "nope"}],
                "estimatedTotalHits": 1,
            },
            "invalid ranking score",
        ),
        ({"hits": [], "estimatedTotalHits": "nope"}, "invalid estimated hit count"),
    ],
)
def test_malformed_store_results_become_named_projection_errors(
    app_config: AppConfig, response: dict, message: str
) -> None:
    with pytest.raises(ProjectionError, match=message):
        search_moments(
            _FakeMeili(response), app_config, query="purchase order", limit=10
        )  # type: ignore[arg-type]


def test_missing_id_refusal_does_not_echo_the_index_document(
    app_config: AppConfig,
) -> None:
    secret = "internal OCR text"
    with pytest.raises(ProjectionError) as raised:
        search_moments(
            _FakeMeili({"hits": [{"text": secret}], "estimatedTotalHits": 1}),
            app_config,
            query="purchase order",
            limit=10,
        )  # type: ignore[arg-type]
    assert secret not in str(raised.value)


def test_a_first_page_floored_out_with_no_keyword_hits_estimates_zero(
    app_config: AppConfig,
) -> None:
    """Keyword hits rank first and are never floored.

    So a first page that came back entirely from the vector lane and lost all
    of it to the floor proves nothing above the floor exists anywhere — and
    "about 50 matches, you are seeing none of them" would be a false statement
    about the corpus rather than about the page.
    """
    floor = app_config.settings.api.search.semantic_score_floor
    meili = _FakeMeili(
        {"hits": [], "estimatedTotalHits": 0},
        {
            "hits": [
                {"id": str(uuid4()), "_rankingScore": floor - 0.2},
                {"id": str(uuid4()), "_rankingScore": floor - 0.1},
            ],
            "estimatedTotalHits": 50,
        },
    )
    result = search_moments(
        meili,
        app_config,
        query="zzzzzzzz",
        limit=10,
        query_vector=(0.1, 0.2),  # type: ignore[arg-type]
    )
    assert result.hits == ()
    assert result.below_floor == 2
    assert result.estimated_total == 0


def test_keyword_and_semantic_lanes_are_merged_without_dropping_keyword_hits(
    app_config: AppConfig,
) -> None:
    """The zero applies only when the *keyword* lane came back empty."""
    floor = app_config.settings.api.search.semantic_score_floor
    keyword_low = uuid4()
    semantic_strong = uuid4()
    meili = _FakeMeili(
        {
            "hits": [
                {"id": str(keyword_low), "_rankingScore": 0.15},
            ],
            "estimatedTotalHits": 1,
        },
        {
            "hits": [
                {"id": str(keyword_low), "_rankingScore": floor - 0.1},
                {"id": str(semantic_strong), "_rankingScore": floor + 0.1},
            ],
            "estimatedTotalHits": 2,
        },
    )
    result = search_moments(
        meili,
        app_config,
        query="purchase order",
        limit=10,
        query_vector=(0.1,),  # type: ignore[arg-type]
    )
    assert {entry.moment_id for entry in result.hits} == {keyword_low, semantic_strong}
    assert result.estimated_total == 2


# --- the artifacts lane (story 4.4) ---------------------------------------


class _FakeArtifactsMeili:
    """Enough of a client to answer count + artifact-page queries."""

    def __init__(self, response: dict | Exception | list[dict | Exception]) -> None:
        self._responses = response if isinstance(response, list) else [response]
        self.calls: list[tuple[str, dict]] = []

    def index(self, name: str) -> "_FakeArtifactsMeili":
        assert name == ARTIFACTS_INDEX, name
        return self

    def search(self, query: str, parameters: dict) -> dict:
        self.calls.append((query, parameters))
        response = self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


def test_artifact_parameters_are_keyword_only_and_pin_published(
    app_config: AppConfig,
) -> None:
    """No hybrid block can ever be built — the index has no embedder — and the
    `state = 'published'` filter is a property of every request, not a hope
    about the index's contents (belt and braces under the publish gate)."""
    parameters = build_artifact_search_parameters(app_config, limit=10)
    assert "hybrid" not in parameters
    assert "vector" not in parameters
    assert parameters["filter"] == 'state = "published"'
    assert parameters["attributesToRetrieve"] == ["id", "momentIds"]
    assert parameters["attributesToHighlight"] == list(ARTIFACT_SNIPPET_ATTRIBUTES)

    paged = build_artifact_search_parameters(app_config, limit=7, offset=11)
    assert paged["limit"] == 7
    assert paged["offset"] == 11


def test_artifact_parameters_match_question_shaped_queries(
    app_config: AppConfig,
) -> None:
    """`chat._artifact_leg` forwards a whole question into this lane, so the
    strategy has to survive the words a question carries and a title does not.

    Meilisearch's `last` default drops query words from the end until a match
    appears, which never strips a leading "what did we decide about" — against
    a published-artifact index holding none of those words the query returns
    nothing, and the crisp decision text never reaches the prompt while the
    hybrid moments lane still answers "the provided moments do not state any
    decision". `frequency` drops the most common words first and leaves the
    terms that carry the question."""
    parameters = build_artifact_search_parameters(app_config, limit=10)
    assert parameters["matchingStrategy"] == "frequency"


def test_artifact_scopes_combine_with_the_published_pin(app_config: AppConfig) -> None:
    meeting_id = uuid4()
    parameters = build_artifact_search_parameters(
        app_config, limit=10, meeting_id=meeting_id, corpus="scripted"
    )
    assert parameters["filter"] == (
        f'state = "published" AND meetingId = "{meeting_id}" AND corpus = "scripted"'
    )


def test_search_artifacts_returns_ids_moments_and_a_snippet(
    app_config: AppConfig,
) -> None:
    artifact_id, moment_id = uuid4(), uuid4()
    meili = _FakeArtifactsMeili(
        [
            {"hits": [], "totalHits": 4},
            {
                "hits": [
                    {
                        "id": str(artifact_id),
                        "momentIds": [str(moment_id)],
                        "_rankingScore": 0.9,
                        "_formatted": {
                            "title": f"Move the feed to {mark('SFTP')}",
                            "text": "Decided during the demo.",
                        },
                    }
                ],
                # Deliberately wrong: the combined boundary must use the
                # exhaustive count response, never this page estimate.
                "estimatedTotalHits": 1,
            },
        ]
    )
    result = search_artifacts(meili, app_config, query="sftp", limit=10, offset=2)  # type: ignore[arg-type]
    assert result.index_missing is False
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.artifact_id == artifact_id
    assert hit.moment_ids == (moment_id,)
    assert hit.score == 0.9
    assert any(run.highlighted and run.text == "SFTP" for run in hit.snippet)
    assert result.total == 4
    assert result.limit == 10
    assert result.offset == 2
    assert meili.calls[0][1]["hitsPerPage"] == 0
    assert "offset" not in meili.calls[0][1]
    assert meili.calls[1][1]["offset"] == 2


def test_artifact_exact_total_skips_a_page_beyond_the_finite_lane(
    app_config: AppConfig,
) -> None:
    meili = _FakeArtifactsMeili({"hits": [], "totalHits": 2})
    result = search_artifacts(
        meili, app_config, query="sftp", limit=3, offset=7  # type: ignore[arg-type]
    )
    assert result.total == 2
    assert result.hits == ()
    assert len(meili.calls) == 1


def test_a_missing_artifacts_index_is_reported_not_raised(
    app_config: AppConfig,
) -> None:
    """A store from before story 4.4 holds nothing published — that is an
    answer, not an outage."""
    import requests
    from meilisearch.errors import MeilisearchApiError

    fake_response = requests.models.Response()
    fake_response.status_code = 404
    fake_response._content = (
        b'{"message":"x","code":"index_not_found","type":"invalid_request","link":"x"}'
    )
    error = MeilisearchApiError("missing", fake_response)
    result = search_artifacts(
        _FakeArtifactsMeili(error),
        app_config,
        query="sftp",
        limit=10,  # type: ignore[arg-type]
    )
    assert result.hits == ()
    assert result.index_missing is True


def test_an_artifact_hit_without_a_uuid_id_is_a_named_refusal(
    app_config: AppConfig,
) -> None:
    meili = _FakeArtifactsMeili(
        [{"hits": [], "totalHits": 1}, {"hits": [{"id": "not-a-uuid"}]}]
    )
    with pytest.raises(ProjectionError, match="not a UUID"):
        search_artifacts(meili, app_config, query="sftp", limit=10)  # type: ignore[arg-type]
