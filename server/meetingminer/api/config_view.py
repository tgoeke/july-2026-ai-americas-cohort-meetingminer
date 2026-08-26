"""GET /config — the read-only, allowlist-sanitized configuration view (CAP-3).

The whole non-secret configuration, projected field by explicit field. This is
an **allowlist, never a model dump**: every response model below declares its
own fields and is populated by naming each source field, so a future
``Settings`` field — which could carry anything, including something
secret-shaped — does not serialize until someone adds it here deliberately.
``tests/test_api_config_view.py`` pins the exact field set of every section
and that no key/password value, prefix, or length appears, the same
secret-discipline pin ``/status`` carries (SPEC-system-status precedent).

Division of labor with ``GET /status``: `/status` owns *health* — whether a
binding's key works, whether a store answers — and already shows the bindings
it probes. This endpoint owns the *full* non-secret configuration: prompts,
pipeline thresholds, retrieval knobs, index attributes — the numbers `/status`
has no reason to carry. Store passwords and API keys live in ``.env`` and are
not configuration in the config.yaml sense; nothing here reads
``config.secrets`` at all.

Read-only: no route here (or anywhere in this chain) mutates ``config.yaml``.
The change path is the file contract — edit ``config.yaml``, restart the
affected process (AD-8/AD-10) — which the UI states per section (story ui-4).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from meetingminer.api.status import provider_of
from meetingminer.config import (
    AppConfig,
    ExtractionRoleBinding,
    LlmRoleBinding,
    SearchIndexConfig,
    Settings,
)

router = APIRouter()


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LlmRoleView(_CamelModel):
    """One ``llm.roles.<role>`` binding, endpoint resolved, prompts included.

    ``endpoint`` is where the primary model's calls actually go: the role's
    own ``base_url`` override when set, else the provider's ``providers.*``
    entry — resolved here so the page shows the effective endpoint rather
    than making the reader re-derive the override rule. ``fallback_endpoint``
    is only ever the role's explicit ``fallback_base_url``: an absent value
    means the fallback resolves through ``providers`` on its own (the
    config.py rule that a fallback never inherits the primary's host).
    """

    role: str
    model: str
    fallback: str | None = None
    provider: str | None = None
    endpoint: str | None = None
    fallback_endpoint: str | None = None
    timeout_seconds: float | None = None
    num_ctx: int | None = None
    # The two complete extraction prompt templates (parent CAP-5's prompt
    # visibility mandate); None on every role but extraction.
    arch_summary_prompt: str | None = None
    action_items_prompt: str | None = None


class OcrView(_CamelModel):
    engine: str
    fallback: str | None = None


class SttView(_CamelModel):
    engine: str
    model: str


class DiarizerView(_CamelModel):
    engine: str


class EmbedderView(_CamelModel):
    model: str
    dimension: int


class FramesView(_CamelModel):
    interval_seconds: float
    jpeg_quality: int


class ScreensView(_CamelModel):
    """Every threshold the screens stage compares against (AD-10)."""

    analysis_width: int
    pixel_diff_threshold: int
    white_pixel_level: int
    change_threshold: float
    settle_threshold: float
    settle_text_growth_ratio: float
    settle_timeout_seconds: float
    crop_survey_frames: int
    crop_column_white_max: float
    crop_min_region_width: float
    crop_row_static_range_max: float
    crop_max_bottom_strip: float
    camera_max_white_fraction: float
    camera_min_saturation: float
    lineage_threshold: float
    min_signature_tokens: int
    gallery_max_blocks: int
    gallery_max_text_density: float
    slide_min_block_height: float
    slide_max_blocks: int


class AlignView(_CamelModel):
    anchor_window_seconds: float
    min_match_score: float
    max_segment_ms: int


class MomentsView(_CamelModel):
    gap_seconds: float
    max_duration_ms: int


class PipelineView(_CamelModel):
    frames: FramesView
    screens: ScreensView
    align: AlignView
    moments: MomentsView


class ChunkingView(_CamelModel):
    chunk_max_chars: int
    chunk_overlap_turns: int


class SearchIndexView(_CamelModel):
    searchable_attributes: list[str]
    filterable_attributes: list[str]
    sortable_attributes: list[str]
    ranking_rules: list[str]


class ProjectionsView(_CamelModel):
    chunking: ChunkingView
    embed_batch_size: int
    moments_index: SearchIndexView
    chunks_index: SearchIndexView
    synonyms: dict[str, list[str]]


class SearchKnobsView(_CamelModel):
    default_limit: int
    max_limit: int
    semantic_ratio: float
    crop_length: int
    semantic_score_floor: float


class ChatKnobsView(_CamelModel):
    retrieval_limit: int
    traversal_row_limit: int


class ApiKnobsView(_CamelModel):
    job_events_poll_seconds: float
    job_events_heartbeat_seconds: float
    search: SearchKnobsView
    chat: ChatKnobsView


class PostgresView(_CamelModel):
    """Coordinates only — the password lives in .env and never serializes."""

    host: str
    port: int
    database: str
    user: str


class Neo4jView(_CamelModel):
    uri: str
    user: str


class MeilisearchView(_CamelModel):
    url: str


class StoresView(_CamelModel):
    postgres: PostgresView
    # Explicit alias: `to_camel` reads the digit as a word break and would
    # serialize the key as "neo4J".
    neo4j: Neo4jView = Field(alias="neo4j")
    meilisearch: MeilisearchView


class ConfigResponse(_CamelModel):
    """The live stack, as config.yaml binds it. No secret, ever."""

    service: str
    config_version: int
    llm_roles: list[LlmRoleView]
    # provider name -> base_url, the shared endpoint map roles resolve through.
    providers: dict[str, str]
    embedder: EmbedderView
    stt: SttView
    ocr: OcrView
    diarizer: DiarizerView
    pipeline: PipelineView
    projections: ProjectionsView
    api: ApiKnobsView
    stores: StoresView


def _role_view(role: str, binding: LlmRoleBinding, settings: Settings) -> LlmRoleView:
    provider = provider_of(binding.model)
    provider_conf = settings.providers.get(provider) if provider else None
    endpoint = binding.base_url or (
        provider_conf.base_url if provider_conf is not None else None
    )
    view = LlmRoleView(
        role=role,
        model=binding.model,
        fallback=binding.fallback,
        provider=provider,
        endpoint=endpoint,
        fallback_endpoint=binding.fallback_base_url,
        timeout_seconds=binding.timeout_seconds,
        num_ctx=binding.num_ctx,
    )
    if isinstance(binding, ExtractionRoleBinding):
        view.arch_summary_prompt = binding.arch_summary_prompt
        view.action_items_prompt = binding.action_items_prompt
    return view


def _index_view(index: SearchIndexConfig) -> SearchIndexView:
    return SearchIndexView(
        searchable_attributes=list(index.searchable_attributes),
        filterable_attributes=list(index.filterable_attributes),
        sortable_attributes=list(index.sortable_attributes),
        ranking_rules=list(index.ranking_rules),
    )


@router.get(
    "/config",
    operation_id="getConfiguration",
    response_model=ConfigResponse,
)
def get_configuration(request: Request) -> ConfigResponse:
    """The allowlist projection of Settings. Reads no secret; mutates nothing."""
    config: AppConfig = request.app.state.config
    settings = config.settings
    roles = settings.llm.roles
    pipeline = settings.pipeline
    projections = settings.projections
    api_conf = settings.api
    stores = settings.stores

    return ConfigResponse(
        service=settings.service,
        config_version=settings.config_version,
        llm_roles=[
            _role_view("extraction", roles.extraction, settings),
            _role_view("chat", roles.chat, settings),
            _role_view("judge", roles.judge, settings),
        ],
        providers={
            name: endpoint.base_url for name, endpoint in settings.providers.items()
        },
        embedder=EmbedderView(
            model=settings.embedder.model, dimension=settings.embedder.dimension
        ),
        stt=SttView(engine=settings.stt.engine, model=settings.stt.model),
        ocr=OcrView(engine=settings.ocr.engine, fallback=settings.ocr.fallback),
        diarizer=DiarizerView(engine=settings.diarizer.engine),
        pipeline=PipelineView(
            frames=FramesView(
                interval_seconds=pipeline.frames.interval_seconds,
                jpeg_quality=pipeline.frames.jpeg_quality,
            ),
            screens=ScreensView(
                analysis_width=pipeline.screens.analysis_width,
                pixel_diff_threshold=pipeline.screens.pixel_diff_threshold,
                white_pixel_level=pipeline.screens.white_pixel_level,
                change_threshold=pipeline.screens.change_threshold,
                settle_threshold=pipeline.screens.settle_threshold,
                settle_text_growth_ratio=pipeline.screens.settle_text_growth_ratio,
                settle_timeout_seconds=pipeline.screens.settle_timeout_seconds,
                crop_survey_frames=pipeline.screens.crop_survey_frames,
                crop_column_white_max=pipeline.screens.crop_column_white_max,
                crop_min_region_width=pipeline.screens.crop_min_region_width,
                crop_row_static_range_max=pipeline.screens.crop_row_static_range_max,
                crop_max_bottom_strip=pipeline.screens.crop_max_bottom_strip,
                camera_max_white_fraction=pipeline.screens.camera_max_white_fraction,
                camera_min_saturation=pipeline.screens.camera_min_saturation,
                lineage_threshold=pipeline.screens.lineage_threshold,
                min_signature_tokens=pipeline.screens.min_signature_tokens,
                gallery_max_blocks=pipeline.screens.gallery_max_blocks,
                gallery_max_text_density=pipeline.screens.gallery_max_text_density,
                slide_min_block_height=pipeline.screens.slide_min_block_height,
                slide_max_blocks=pipeline.screens.slide_max_blocks,
            ),
            align=AlignView(
                anchor_window_seconds=pipeline.align.anchor_window_seconds,
                min_match_score=pipeline.align.min_match_score,
                max_segment_ms=pipeline.align.max_segment_ms,
            ),
            moments=MomentsView(
                gap_seconds=pipeline.moments.gap_seconds,
                max_duration_ms=pipeline.moments.max_duration_ms,
            ),
        ),
        projections=ProjectionsView(
            chunking=ChunkingView(
                chunk_max_chars=projections.chunking.chunk_max_chars,
                chunk_overlap_turns=projections.chunking.chunk_overlap_turns,
            ),
            embed_batch_size=projections.embed_batch_size,
            moments_index=_index_view(projections.search.moments),
            chunks_index=_index_view(projections.search.chunks),
            synonyms={
                term: list(alternatives)
                for term, alternatives in projections.search.synonyms.items()
            },
        ),
        api=ApiKnobsView(
            job_events_poll_seconds=api_conf.job_events_poll_seconds,
            job_events_heartbeat_seconds=api_conf.job_events_heartbeat_seconds,
            search=SearchKnobsView(
                default_limit=api_conf.search.default_limit,
                max_limit=api_conf.search.max_limit,
                semantic_ratio=api_conf.search.semantic_ratio,
                crop_length=api_conf.search.crop_length,
                semantic_score_floor=api_conf.search.semantic_score_floor,
            ),
            chat=ChatKnobsView(
                retrieval_limit=api_conf.chat.retrieval_limit,
                traversal_row_limit=api_conf.chat.traversal_row_limit,
            ),
        ),
        stores=StoresView(
            postgres=PostgresView(
                host=stores.postgres.host,
                port=stores.postgres.port,
                database=stores.postgres.database,
                user=stores.postgres.user,
            ),
            neo4j=Neo4jView(uri=stores.neo4j.uri, user=stores.neo4j.user),
            meilisearch=MeilisearchView(url=stores.meilisearch.url),
        ),
    )
