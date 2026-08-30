"""Config-loader edge cases from the story 1.1 and 1.10 I/O matrices:
missing file, bad YAML, invalid shape, env secret pickup, the one .env
dialect, path anchoring, and the content-root warning."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from meetingminer.config import (
    FASTAPI_SSE_KEEPALIVE_SECONDS,
    ConfigError,
    docs_root,
    load_config,
    resolve_config_path,
)

from repo_paths import REPO_ROOT

VALID_CONFIG = """\
config_version: 1
service: meetingminer
ocr:
  engine: apple-vision
stt:
  engine: mlx-whisper
  model: mlx-community/whisper-large-v3-turbo
diarizer:
  engine: noop
llm:
  roles:
    extraction:
      model: claude-sonnet-5
      fallback: ollama/qwen3:32b
      arch_summary_prompt: "Summarize the architecture decisions."
      action_items_prompt: "Extract the action items."
      topics_prompt: "List the topics discussed."
    chat: {model: claude-sonnet-5, fallback: ollama/qwen3:32b}
    judge: {model: claude-sonnet-5, fallback: ollama/qwen3:32b}
embedder:
  model: qwen3-embedding
  dimension: 1024
providers:
  anthropic: {base_url: https://api.anthropic.com}
  ollama: {base_url: http://localhost:11434}
pipeline:
  frames: {interval_seconds: 2, jpeg_quality: 3}
  screens:
    analysis_width: 320
    pixel_diff_threshold: 16
    white_pixel_level: 200
    change_threshold: 0.10
    settled_change_threshold: 0.03
    settled_change_frames: 3
    settle_threshold: 0.02
    settle_text_growth_ratio: 1.5
    settle_timeout_seconds: 10
    crop_survey_frames: 24
    crop_column_white_max: 0.25
    crop_min_region_width: 0.6
    crop_row_static_range_max: 80
    crop_max_bottom_strip: 0.12
    camera_max_white_fraction: 0.118
    camera_min_saturation: 0.212
    lineage_threshold: 0.8
    min_signature_tokens: 3
    gallery_max_blocks: 6
    gallery_max_text_density: 0.02
    slide_min_block_height: 0.04
    slide_max_blocks: 25
  align:
    anchor_window_seconds: 2.0
    min_match_score: 0.35
    max_segment_ms: 60000
  moments:
    gap_seconds: 20
    max_duration_ms: 180000
api:
  job_events_poll_seconds: 1.0
  job_events_heartbeat_seconds: 10.0
  search:
    default_limit: 20
    max_limit: 100
    semantic_ratio: 0.3
    crop_length: 40
    semantic_score_floor: 0.75
  chat:
    retrieval_limit: 30
    traversal_row_limit: 20
projections:
  chunking: {chunk_max_chars: 1400, chunk_overlap_turns: 1}
  embed_batch_size: 16
  search:
    moments:
      searchable_attributes: [text, screenText, speakers, title]
      filterable_attributes: [meetingId, corpus]
      sortable_attributes: [startMs]
      ranking_rules: [words, typo, proximity, attribute, sort, exactness]
    chunks:
      searchable_attributes: [text, speakers, title]
      filterable_attributes: [meetingId, corpus]
      sortable_attributes: [startMs]
      ranking_rules: [words, typo, proximity, attribute, sort, exactness]
    artifacts:
      searchable_attributes: [title, text]
      filterable_attributes: [meetingId, corpus, state, kind]
      sortable_attributes: []
      ranking_rules: [words, typo, proximity, attribute, sort, exactness]
    synonyms: {sftp: [ftp], ftp: [sftp]}
stores:
  postgres: {host: localhost, port: 5432, database: meetingminer, user: meetingminer}
  neo4j: {uri: bolt://localhost:7687, user: neo4j}
  meilisearch: {url: http://localhost:7700}
acquisition:
  youtube:
    max_duration_minutes: 37
"""


@pytest.fixture()
def valid_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(VALID_CONFIG, encoding="utf-8")
    return path


@pytest.fixture()
def no_env(tmp_path: Path) -> Path:
    """An env-file path that does not exist."""
    return tmp_path / "absent.env"


def test_missing_config_file_is_fatal(tmp_path: Path, no_env: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(ConfigError, match=str(missing)):
        load_config(missing, no_env)


def test_unparseable_yaml_is_fatal(tmp_path: Path, no_env: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("ocr: [unclosed\n  engine: :::", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(path, no_env)


def test_non_mapping_yaml_is_fatal(tmp_path: Path, no_env: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML mapping"):
        load_config(path, no_env)


def test_unknown_engine_is_fatal(tmp_path: Path, no_env: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        VALID_CONFIG.replace("engine: apple-vision", "engine: crystal-ball"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="failed validation"):
        load_config(path, no_env)


def test_missing_llm_role_is_fatal(tmp_path: Path, no_env: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        VALID_CONFIG.replace(
            "    judge: {model: claude-sonnet-5, fallback: ollama/qwen3:32b}\n", ""
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="failed validation"):
        load_config(path, no_env)


@pytest.mark.parametrize(
    "replacement",
    [
        ("service: meetingminer", "service: '   '"),
        ("port: 5432", "port: 0"),
        ("port: 5432", "port: 65536"),
        ("database: meetingminer", "database: '  '"),
    ],
)
def test_blank_identifiers_and_invalid_store_ports_are_fatal(
    tmp_path: Path, no_env: Path, replacement: tuple[str, str]
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(VALID_CONFIG.replace(*replacement), encoding="utf-8")
    with pytest.raises(ConfigError, match="failed validation"):
        load_config(path, no_env)


def test_unsupported_config_version_is_fatal(tmp_path: Path, no_env: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        VALID_CONFIG.replace("config_version: 1", "config_version: 2"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="unsupported config_version 2"):
        load_config(path, no_env)


def test_valid_config_loads(valid_config: Path, no_env: Path) -> None:
    config = load_config(valid_config, no_env)
    assert config.settings.service == "meetingminer"
    assert config.settings.ocr.engine == "apple-vision"
    assert config.settings.llm.roles.chat.model == "claude-sonnet-5"
    assert config.settings.embedder.dimension == 1024
    assert config.settings.llm.roles.extraction.arch_summary_prompt == (
        "Summarize the architecture decisions."
    )
    assert config.settings.llm.roles.extraction.action_items_prompt == (
        "Extract the action items."
    )


def test_missing_extraction_prompt_key_is_fatal(tmp_path: Path, no_env: Path) -> None:
    """Story 4.2's I/O matrix: an omitted prompt key fails config loading
    with a named error — there is no code-level default to fall back to."""
    path = tmp_path / "config.yaml"
    path.write_text(
        VALID_CONFIG.replace(
            '      arch_summary_prompt: "Summarize the architecture decisions."\n',
            "",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="arch_summary_prompt"):
        load_config(path, no_env)


def test_env_file_secret_pickup(
    valid_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MM_CONTENT_ROOT", raising=False)
    envfile = tmp_path / ".env"
    envfile.write_text(
        "# comment\nANTHROPIC_API_KEY=sk-from-file\nMM_CONTENT_ROOT=/tmp/content\n",
        encoding="utf-8",
    )
    config = load_config(valid_config, envfile)
    assert config.secrets.anthropic_api_key == "sk-from-file"
    # resolve()d (story 1.10): one absolute path regardless of caller cwd.
    assert config.secrets.mm_content_root == Path("/tmp/content").resolve()


def test_process_env_wins_over_env_file(
    valid_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envfile = tmp_path / ".env"
    envfile.write_text("POSTGRES_PASSWORD=from-file\n", encoding="utf-8")
    monkeypatch.setenv("POSTGRES_PASSWORD", "from-process")
    config = load_config(valid_config, envfile)
    assert config.secrets.postgres_password == "from-process"


def test_blank_secret_is_none(
    valid_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    envfile = tmp_path / ".env"
    envfile.write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    config = load_config(valid_config, envfile)
    assert config.secrets.openai_api_key is None


def test_committed_config_yaml_is_valid(no_env: Path) -> None:
    """The repo's real config.yaml must always satisfy the loader."""
    config = load_config(REPO_ROOT / "config.yaml", no_env)
    assert config.settings.config_version == 1


# --- path anchoring (story 1.10, finding 17) -------------------------------


def test_config_resolves_cwd_relative_by_default(
    valid_config: Path, no_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(valid_config.parent)
    assert resolve_config_path() == valid_config.parent / "config.yaml"
    config = load_config(None, no_env)
    assert config.settings.service == "meetingminer"


def test_mm_config_path_overrides_cwd(
    valid_config: Path, no_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # no config.yaml here
    monkeypatch.setenv("MM_CONFIG_PATH", str(valid_config))
    config = load_config(None, no_env)
    assert config.settings.service == "meetingminer"


def test_missing_default_config_error_names_both_locations(
    tmp_path: Path, no_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    with pytest.raises(ConfigError) as excinfo:
        load_config(None, no_env)
    message = str(excinfo.value)
    assert "MM_CONFIG_PATH" in message
    assert str(empty / "config.yaml") in message


def test_docs_root_anchors_on_config_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MM_CONFIG_PATH", "/somewhere/else/config.yaml")
    assert docs_root() == Path("/somewhere/else/docs")
    monkeypatch.delenv("MM_CONFIG_PATH")
    assert docs_root() == Path.cwd() / "docs"  # conftest chdir'd to repo root
    assert (docs_root() / "source-drop.schema.json").is_file()


# --- the one .env dialect (story 1.10, findings 14-16) ---------------------


def _secrets(valid_config: Path, tmp_path: Path, env_text: str):
    envfile = tmp_path / "dialect.env"
    envfile.write_text(env_text, encoding="utf-8")
    return load_config(valid_config, envfile).secrets


def test_quoted_value_with_inline_comment(
    valid_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I/O matrix: `KEY="v" # note` resolves `v` — quotes gone, comment gone."""
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    secrets = _secrets(valid_config, tmp_path, 'POSTGRES_PASSWORD="v" # note\n')
    assert secrets.postgres_password == "v"


def test_hash_inside_quoted_value_is_kept(
    valid_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comments are never stripped from quoted values (finding 14): a secret
    containing ` #` survives intact."""
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    secrets = _secrets(valid_config, tmp_path, 'POSTGRES_PASSWORD="pa ss #word"\n')
    assert secrets.postgres_password == "pa ss #word"


def test_unquoted_value_inline_comment_stripped(
    valid_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    secrets = _secrets(valid_config, tmp_path, "NEO4J_PASSWORD=v  # note\n")
    assert secrets.neo4j_password == "v"


def test_export_prefix_accepted(
    valid_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MEILI_MASTER_KEY", raising=False)
    secrets = _secrets(valid_config, tmp_path, "export MEILI_MASTER_KEY=exported\n")
    assert secrets.meili_master_key == "exported"


def test_blank_process_env_does_not_mask_env_file(
    valid_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I/O matrix: `export VAR=` (blank) in the shell — the .env value wins."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "")
    secrets = _secrets(valid_config, tmp_path, "POSTGRES_PASSWORD=from-file\n")
    assert secrets.postgres_password == "from-file"


def test_content_root_tilde_expands(
    valid_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I/O matrix: MM_CONTENT_ROOT=~/mm expands to $HOME/mm (finding 16)."""
    monkeypatch.delenv("MM_CONTENT_ROOT", raising=False)
    secrets = _secrets(valid_config, tmp_path, "MM_CONTENT_ROOT=~/mm\n")
    assert secrets.mm_content_root == (Path.home() / "mm").resolve()


# --- the loader and docker compose agree on the same file (finding 14) -----


@pytest.mark.parametrize(
    "line,expected",
    [
        ("POSTGRES_PASSWORD=plain", "plain"),
        ('POSTGRES_PASSWORD="quoted value"', "quoted value"),
        ('POSTGRES_PASSWORD="v" # note', "v"),
        ('POSTGRES_PASSWORD="pa ss #word"', "pa ss #word"),
        ("POSTGRES_PASSWORD=trailing  # note", "trailing"),
        ("export POSTGRES_PASSWORD=exported", "exported"),
        ("POSTGRES_PASSWORD='raw $literal'", "raw $literal"),
        ('OTHER=inner\nPOSTGRES_PASSWORD="${OTHER}-suffix"', "inner-suffix"),
    ],
)
def test_env_dialect_matches_docker_compose(
    line: str,
    expected: str,
    valid_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented dialect is only real if both readers agree on it.

    Resolves the same .env through the Python loader and through
    `docker compose --env-file … config`, and requires an identical value.
    """
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not installed — run via 'make test'")
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("Docker daemon not running — start it or run 'make test'")

    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("OTHER", raising=False)
    envfile = tmp_path / "parity.env"
    envfile.write_text(line + "\n", encoding="utf-8")

    compose_file = tmp_path / "compose.yml"
    compose_file.write_text(
        "services:\n"
        "  probe:\n"
        "    image: alpine\n"
        "    environment:\n"
        "      VALUE: ${POSTGRES_PASSWORD}\n",
        encoding="utf-8",
    )
    rendered = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(envfile),
            "-f",
            str(compose_file),
            "config",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert rendered.returncode == 0, rendered.stderr
    compose_value = yaml.safe_load(rendered.stdout)["services"]["probe"]["environment"][
        "VALUE"
    ]
    # `docker compose config` emits a compose file, so a literal `$` comes back
    # escaped as `$$`. Verified against ground truth: for `KEY='raw $literal'`
    # the rendered output shows `raw $$literal` while a container started from
    # the same file receives `raw $literal`. Decode the escape so this compares
    # effective values, not output encoding.
    compose_value = compose_value.replace("$$", "$")

    loader_value = load_config(valid_config, envfile).secrets.postgres_password
    assert loader_value == expected
    assert compose_value == expected, (
        f"compose resolved {compose_value!r}, loader resolved {loader_value!r}"
    )


# --- content-root startup warning (story 1.10, finding 18) -----------------


def test_unset_content_root_warns(
    valid_config: Path,
    no_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MM_CONTENT_ROOT", raising=False)
    config = load_config(valid_config, no_env)
    assert config.secrets.mm_content_root is None
    assert "MM_CONTENT_ROOT is unset" in capsys.readouterr().err


def test_content_root_not_a_directory_warns(
    valid_config: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MM_CONTENT_ROOT", raising=False)
    missing = tmp_path / "not-there"
    _secrets(valid_config, tmp_path, f"MM_CONTENT_ROOT={missing}\n")
    assert "MM_CONTENT_ROOT is not a directory" in capsys.readouterr().err


def test_content_root_directory_does_not_warn(
    valid_config: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MM_CONTENT_ROOT", raising=False)
    _secrets(valid_config, tmp_path, f"MM_CONTENT_ROOT={tmp_path}\n")
    assert "MM_CONTENT_ROOT" not in capsys.readouterr().err


def test_relative_content_root_is_a_named_config_error(
    valid_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker's media-root contract deliberately rejects relative paths."""
    monkeypatch.delenv("MM_CONTENT_ROOT", raising=False)
    envfile = tmp_path / "rel.env"
    envfile.write_text("MM_CONTENT_ROOT=./content\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="MM_CONTENT_ROOT must be an absolute path"):
        load_config(valid_config, envfile)


def test_frame_interval_accepts_one_millisecond_and_rejects_smaller(
    valid_config: Path, no_env: Path
) -> None:
    valid_config.write_text(
        VALID_CONFIG.replace("interval_seconds: 2", "interval_seconds: 0.001"),
        encoding="utf-8",
    )
    assert (
        load_config(valid_config, no_env).settings.pipeline.frames.interval_seconds
        == 0.001
    )
    valid_config.write_text(
        VALID_CONFIG.replace("interval_seconds: 2", "interval_seconds: 0.0009"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="greater than or equal to 0.001"):
        load_config(valid_config, no_env)


def test_search_index_requires_the_attributes_the_module_names(
    tmp_path: Path, no_env: Path
) -> None:
    """Story 1.7: `projections.search` filters on `meetingId` and `corpus` and
    writes the passage body to `text`. Omitting one is not a tuning choice —
    it turns every re-projection into a Meilisearch error hours into an
    ingest, so it has to be a config-load refusal instead."""
    for kept, missing in (("corpus", "meetingId"), ("meetingId", "corpus")):
        path = tmp_path / f"config-{missing}.yaml"
        path.write_text(
            VALID_CONFIG.replace(
                "      filterable_attributes: [meetingId, corpus]",
                f"      filterable_attributes: [{kept}]",
                1,  # the moments index; one broken index is enough to refuse
            ),
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match=missing):
            load_config(path, no_env)

    path = tmp_path / "config-no-text.yaml"
    path.write_text(
        VALID_CONFIG.replace(
            "      searchable_attributes: [text, speakers, title]",
            "      searchable_attributes: [speakers, title]",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="'text'"):
        load_config(path, no_env)


def test_searchable_attribute_order_stays_free_to_retune(
    tmp_path: Path, no_env: Path
) -> None:
    """The order *is* the field boost in Meilisearch 1.53, so reordering must
    stay a config edit — the validator pins membership, never sequence."""
    path = tmp_path / "config.yaml"
    path.write_text(
        VALID_CONFIG.replace(
            "      searchable_attributes: [text, screenText, speakers, title]",
            "      searchable_attributes: [title, text, screenText, speakers]",
            1,
        ),
        encoding="utf-8",
    )
    moments = load_config(path, no_env).settings.projections.search.moments
    assert moments.searchable_attributes == ["title", "text", "screenText", "speakers"]


@pytest.mark.parametrize(
    ("configured", "broken", "message"),
    [
        (
            "      searchable_attributes: [title, text]",
            "      searchable_attributes: [text]",
            "artifacts.searchable_attributes.*'title'",
        ),
        (
            "      filterable_attributes: [meetingId, corpus, state, kind]",
            "      filterable_attributes: [meetingId, corpus, kind]",
            "artifacts.filterable_attributes.*'state'",
        ),
    ],
)
def test_artifacts_index_requires_its_query_surface(
    tmp_path: Path,
    no_env: Path,
    configured: str,
    broken: str,
    message: str,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(VALID_CONFIG.replace(configured, broken), encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(path, no_env)


def test_search_default_limit_may_not_exceed_the_configured_maximum(
    tmp_path: Path, no_env: Path
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        VALID_CONFIG.replace("    default_limit: 20", "    default_limit: 101"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="default_limit"):
        load_config(path, no_env)


def test_moments_search_requires_every_highlighted_query_attribute(
    tmp_path: Path, no_env: Path
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        VALID_CONFIG.replace(
            "text, screenText, speakers, title", "text, speakers, title", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="screenText"):
        load_config(path, no_env)


def test_min_signature_tokens_rejects_zero(valid_config: Path, no_env: Path) -> None:
    """Zero would invert the guard the field exists to enforce.

    At 0 an empty signature clears the floor and hashes to a corpus-wide key,
    collapsing every textless screen in the corpus onto one row.
    """
    valid_config.write_text(
        VALID_CONFIG.replace("min_signature_tokens: 3", "min_signature_tokens: 1"),
        encoding="utf-8",
    )
    screens = load_config(valid_config, no_env).settings.pipeline.screens
    assert screens.min_signature_tokens == 1
    valid_config.write_text(
        VALID_CONFIG.replace("min_signature_tokens: 3", "min_signature_tokens: 0"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="greater than or equal to 1"):
        load_config(valid_config, no_env)


def test_unresolvable_tilde_user_is_a_named_config_error(
    valid_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`~nosuchuser/...` makes expanduser raise RuntimeError; the loader's
    contract is a named ConfigError, never an escaping exception."""
    monkeypatch.delenv("MM_CONTENT_ROOT", raising=False)
    envfile = tmp_path / "baduser.env"
    envfile.write_text("MM_CONTENT_ROOT=~nosuchuser54321/mm\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="MM_CONTENT_ROOT could not be expanded"):
        load_config(valid_config, envfile)


# --- the schema anchors on the config actually loaded (finding 17) ---------


def test_config_path_is_recorded_on_the_loaded_config(
    valid_config: Path, no_env: Path
) -> None:
    config = load_config(valid_config, no_env)
    assert config.config_path == valid_config.resolve()


def test_drop_schema_follows_an_explicitly_passed_config_path(
    tmp_path: Path, no_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit config path is invisible to MM_CONFIG_PATH/cwd lookup, so
    re-resolving would anchor the schema on a different tree than the config
    (conftest passes explicit paths, and pytest's cwd moves)."""
    tree = tmp_path / "tree"
    (tree / "docs").mkdir(parents=True)
    config_path = tree / "config.yaml"
    config_path.write_text(VALID_CONFIG, encoding="utf-8")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("MM_CONFIG_PATH", str(elsewhere / "config.yaml"))

    config = load_config(config_path, no_env)

    from meetingminer.api.ingests import drop_schema_path

    assert drop_schema_path(config) == tree / "docs" / "source-drop.schema.json"
    # …and not the tree MM_CONFIG_PATH/cwd would have produced.
    assert docs_root() != tree / "docs"


# --- story 1.9: the api's job-event stream intervals ------------------------


def test_api_stream_intervals_load_from_config(
    valid_config: Path, no_env: Path
) -> None:
    api = load_config(valid_config, no_env).settings.api
    assert api.job_events_poll_seconds == 1.0
    assert api.job_events_heartbeat_seconds == 10.0


def test_chat_retrieval_knobs_load_from_config(
    valid_config: Path, no_env: Path
) -> None:
    """Story 3.3, AD-10: retrieval breadth is a config edit, not a code edit."""
    chat = load_config(valid_config, no_env).settings.api.chat
    assert chat.retrieval_limit == 30
    assert chat.traversal_row_limit == 20


def test_chat_retrieval_knobs_refuse_a_value_that_would_retrieve_nothing(
    valid_config: Path, no_env: Path
) -> None:
    """A zero or negative breadth would make every question `no-evidence`, and
    an unbounded one would put the whole corpus in a prompt."""
    for line, bad in (
        ("retrieval_limit: 30", "0"),
        ("retrieval_limit: 30", "-1"),
        ("retrieval_limit: 30", "201"),
        ("traversal_row_limit: 20", "0"),
        ("traversal_row_limit: 20", "201"),
    ):
        key = line.split(":")[0]
        valid_config.write_text(
            VALID_CONFIG.replace(line, f"{key}: {bad}"), encoding="utf-8"
        )
        with pytest.raises(ConfigError, match=f"api.chat.{key}"):
            load_config(valid_config, no_env)


def test_poll_interval_must_be_positive_and_stay_under_a_minute(
    valid_config: Path, no_env: Path
) -> None:
    """A non-positive poll would spin; past a minute it is no longer live progress."""
    for bad in ("0", "-1", "60.1"):
        valid_config.write_text(
            VALID_CONFIG.replace(
                "job_events_poll_seconds: 1.0", f"job_events_poll_seconds: {bad}"
            ),
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="failed validation"):
            load_config(valid_config, no_env)


def test_heartbeat_is_capped_at_fastapis_own_keepalive(
    valid_config: Path, no_env: Path
) -> None:
    """The bound is the invariant the field's comment states.

    Above FastAPI's own 15s SSE keepalive the configured value would be
    silently shadowed by the framework's ping — a comment asserting an
    invariant nothing enforces is worse than no comment, so the loader
    enforces it.
    """
    assert FASTAPI_SSE_KEEPALIVE_SECONDS == 15.0

    valid_config.write_text(
        VALID_CONFIG.replace(
            "job_events_heartbeat_seconds: 10.0", "job_events_heartbeat_seconds: 15.0"
        ),
        encoding="utf-8",
    )
    loaded = load_config(valid_config, no_env)
    assert loaded.settings.api.job_events_heartbeat_seconds == 15.0

    valid_config.write_text(
        VALID_CONFIG.replace(
            "job_events_heartbeat_seconds: 10.0", "job_events_heartbeat_seconds: 15.1"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="less than or equal to 15"):
        load_config(valid_config, no_env)


def test_repo_config_stays_within_the_heartbeat_bound() -> None:
    """The shipped config.yaml, not just the test fixture, honours the cap."""
    shipped = load_config(REPO_ROOT / "config.yaml", REPO_ROOT / ".env").settings.api
    assert 0 < shipped.job_events_heartbeat_seconds <= FASTAPI_SSE_KEEPALIVE_SECONDS


# --- a worktree's private stack: .env.worktree and the port overrides (11.2) --


def _stack_files(tmp_path: Path, env_text: str, worktree_text: str | None) -> Path:
    """A `.env` (returned) with, when given, a `.env.worktree` beside it."""
    envfile = tmp_path / ".env"
    envfile.write_text(env_text, encoding="utf-8")
    if worktree_text is not None:
        (tmp_path / ".env.worktree").write_text(worktree_text, encoding="utf-8")
    return envfile


PORT_OVERRIDES = ("MM_POSTGRES_PORT", "MM_NEO4J_BOLT_PORT", "MM_MEILI_PORT")


@pytest.fixture()
def no_port_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*PORT_OVERRIDES, "MM_TEST_MEILI_URL", "MM_TEST_NEO4J_URI", "MM_STACK_NAME"):
        monkeypatch.delenv(name, raising=False)


def test_worktree_env_file_overrides_env_file(
    valid_config: Path, tmp_path: Path, no_port_overrides: None
) -> None:
    """A twin URL may sit in both files; the worktree's wins."""
    from meetingminer.config import merged_env

    envfile = _stack_files(
        tmp_path,
        "MM_TEST_MEILI_URL=http://localhost:1\n",
        good_stack_text("probe"),
    )
    assert merged_env(envfile)["MM_TEST_MEILI_URL"] == "http://localhost:20007"


def test_process_env_overrides_worktree_env_file(
    valid_config: Path, tmp_path: Path, no_port_overrides: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MM_MEILI_PORT", "20014")
    envfile = _stack_files(tmp_path, "", good_stack_text("probe"))
    assert load_config(valid_config, envfile).settings.stores.meilisearch.url == "http://localhost:20014"


def test_blank_process_env_does_not_mask_worktree_env_file(
    valid_config: Path, tmp_path: Path, no_port_overrides: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MM_MEILI_PORT", "")
    envfile = _stack_files(tmp_path, "", good_stack_text("probe"))
    assert load_config(valid_config, envfile).settings.stores.meilisearch.url == "http://localhost:20004"


def test_merged_env_precedence_is_env_then_worktree_then_process(
    tmp_path: Path, no_port_overrides: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from meetingminer.config import merged_env

    monkeypatch.setenv("MM_MEILI_PORT", "30004")
    monkeypatch.setenv("MM_POSTGRES_PORT", "")
    envfile = _stack_files(
        tmp_path,
        "POSTGRES_PASSWORD=from-env\nMM_TEST_MEILI_URL=http://localhost:1\n",
        good_stack_text("probe"),
    )
    env = merged_env(envfile)
    assert env["POSTGRES_PASSWORD"] == "from-env"  # .env alone
    assert env["MM_TEST_MEILI_URL"] == "http://localhost:20007"  # worktree over .env
    assert env["MM_MEILI_PORT"] == "30004"  # process over worktree
    assert env["MM_POSTGRES_PORT"] == "20001"  # blank process value does not mask


def test_worktree_env_file_refuses_a_key_that_is_not_a_stack_key(
    valid_config: Path, tmp_path: Path, no_port_overrides: None
) -> None:
    """A secret can never be overridden from the worktree file."""
    envfile = _stack_files(tmp_path, "", good_stack_text("probe") + "POSTGRES_PASSWORD=sneaky\n")
    with pytest.raises(ConfigError, match=r"\.env\.worktree: POSTGRES_PASSWORD is not a stack key"):
        load_config(valid_config, envfile)


@pytest.mark.parametrize("key", ["MM_STACK_NAME", "MM_POSTGRES_PORT", "MM_MEILI_TEST_PORT"])
def test_env_file_refuses_stack_name_and_port_keys(
    valid_config: Path, tmp_path: Path, no_port_overrides: None, key: str
) -> None:
    """The Makefile never reads them from .env, so the loader must not either."""
    envfile = _stack_files(tmp_path, f"{key}=x\n", None)
    with pytest.raises(ConfigError, match=rf"{key} — stack keys belong in \.env\.worktree"):
        load_config(valid_config, envfile)


def test_worktree_env_file_is_found_beside_the_env_path_not_its_target(
    valid_config: Path, tmp_path: Path, no_port_overrides: None
) -> None:
    """In a worktree `.env` is a symlink to the main checkout's file; the
    worktree file that counts is the one beside the LINK."""
    main = tmp_path / "main"
    main.mkdir()
    (main / ".env").write_text("POSTGRES_PASSWORD=from-main\n", encoding="utf-8")
    (main / ".env.worktree").write_text("MM_MEILI_PORT=20014\n", encoding="utf-8")  # must NOT be read
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".env").symlink_to(main / ".env")
    (worktree / ".env.worktree").write_text(good_stack_text("wt"), encoding="utf-8")
    config = load_config(valid_config, worktree / ".env")
    assert config.settings.stores.meilisearch.url == "http://localhost:20004"
    assert config.secrets.postgres_password == "from-main"
    (worktree / ".env.worktree").unlink()
    assert load_config(valid_config, worktree / ".env").settings.stores.meilisearch.url == "http://localhost:7700"


def test_port_overrides_repoint_the_three_stores(
    valid_config: Path, tmp_path: Path, no_port_overrides: None
) -> None:
    envfile = _stack_files(tmp_path, "", good_stack_text("probe"))
    stores = load_config(valid_config, envfile).settings.stores
    assert (stores.postgres.host, stores.postgres.port) == ("localhost", 20001)
    assert stores.neo4j.uri == "bolt://localhost:20003"
    assert stores.neo4j.user == "neo4j"
    assert stores.meilisearch.url == "http://localhost:20004"


def test_port_overrides_are_inactive_when_unset(
    valid_config: Path, no_env: Path, no_port_overrides: None
) -> None:
    stores = load_config(valid_config, no_env).settings.stores
    assert (stores.postgres.port, stores.neo4j.uri, stores.meilisearch.url) == (
        5432,
        "bolt://localhost:7687",
        "http://localhost:7700",
    )


@pytest.mark.parametrize("name", PORT_OVERRIDES)
@pytest.mark.parametrize("value", ["abc", "70000", "0", "-1", "1.5", "65536", "+5", "1_000", "\u0663"])
def test_invalid_port_override_is_a_named_config_error(
    valid_config: Path,
    tmp_path: Path,
    no_port_overrides: None,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)
    envfile = _stack_files(tmp_path, "", None)
    with pytest.raises(ConfigError, match=rf"{name} must be an integer port in 1\.\.65535"):
        load_config(valid_config, envfile)


def _config_with(tmp_path: Path, old: str, new: str) -> Path:
    assert old in VALID_CONFIG
    config_path = tmp_path / "config.yaml"
    config_path.write_text(VALID_CONFIG.replace(old, new), encoding="utf-8")
    return config_path


def test_port_override_adds_a_port_to_a_uri_without_one(
    tmp_path: Path, no_port_overrides: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _config_with(tmp_path, "uri: bolt://localhost:7687", "uri: bolt://host")
    monkeypatch.setenv("MM_NEO4J_BOLT_PORT", "1")
    envfile = _stack_files(tmp_path, "", None)
    assert load_config(config_path, envfile).settings.stores.neo4j.uri == "bolt://host:1"


def test_port_override_keeps_userinfo_and_path(
    tmp_path: Path, no_port_overrides: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _config_with(
        tmp_path, "url: http://localhost:7700", "url: http://u:p@127.0.0.1:7700/base"
    )
    monkeypatch.setenv("MM_MEILI_PORT", "20004")
    envfile = _stack_files(tmp_path, "", None)
    assert load_config(config_path, envfile).settings.stores.meilisearch.url == "http://u:p@127.0.0.1:20004/base"


def test_port_override_keeps_the_host_text_verbatim(
    tmp_path: Path, no_port_overrides: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mixed case is kept (not lowercased through .hostname); IPv6 keeps its brackets."""
    config_path = _config_with(tmp_path, "uri: bolt://localhost:7687", "uri: bolt://Neo4jHost:7687")
    monkeypatch.setenv("MM_NEO4J_BOLT_PORT", "20003")
    envfile = _stack_files(tmp_path, "", None)
    assert load_config(config_path, envfile).settings.stores.neo4j.uri == "bolt://Neo4jHost:20003"
    config_path = _config_with(tmp_path, "uri: bolt://localhost:7687", 'uri: "bolt://[::1]:7687"')
    assert load_config(config_path, envfile).settings.stores.neo4j.uri == "bolt://[::1]:20003"


# --- remediation 2026-08-30: the loader validates the whole worktree file ----
# The schema is spelled twice on purpose — infra/worktree_stack.py must run
# with the system python3 before a venv exists, and the server package cannot
# import from infra/ — so this table pins the two implementations equal: for
# every bad file both refuse, naming the same key.

from test_worktree_stack import (  # noqa: E402
    BAD_STACK_FILES,
    BAD_STACK_IDS,
    good_stack_text,
    ws as worktree_stack,
)


def test_a_rendered_stack_file_passes_both_validators(
    tmp_path: Path, no_port_overrides: None
) -> None:
    from meetingminer.config import merged_env

    envfile = _stack_files(tmp_path, "POSTGRES_PASSWORD=x\n", good_stack_text("probe"))
    values = worktree_stack.validate_env_file(tmp_path / ".env.worktree", "probe")
    env = merged_env(envfile)
    for key, value in values.items():
        assert env[key] == value


def test_loader_refuses_another_worktrees_record_at_a_linked_checkout_root(
    tmp_path: Path,
    no_port_overrides: None,
) -> None:
    """Structural validity is not directory ownership for server entrypoints."""
    from meetingminer.config import merged_env

    checkout = tmp_path / "probe"
    checkout.mkdir()
    (checkout / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    envfile = _stack_files(checkout, "POSTGRES_PASSWORD=x\n", good_stack_text("other"))

    with pytest.raises(ConfigError, match=r"meetingminer-other.*meetingminer-probe"):
        merged_env(envfile)


@pytest.mark.parametrize(
    ("case", "lines", "key", "loader_rejects"), BAD_STACK_FILES, ids=BAD_STACK_IDS
)
def test_loader_and_script_refuse_the_same_files_naming_the_same_key(
    tmp_path: Path,
    no_port_overrides: None,
    case: str,
    lines: list[str],
    key: str,
    loader_rejects: bool,
) -> None:
    from meetingminer.config import merged_env

    text = "\n".join(lines) + "\n"
    envfile = _stack_files(tmp_path, "POSTGRES_PASSWORD=x\n", text)
    with pytest.raises(worktree_stack.StackError) as script_error:
        worktree_stack.validate_env_file(tmp_path / ".env.worktree", "probe")
    assert key in str(script_error.value)
    if loader_rejects:
        with pytest.raises(ConfigError) as loader_error:
            merged_env(envfile)
        assert key in str(loader_error.value)
        assert str(tmp_path / ".env.worktree") in str(loader_error.value)
    else:
        # The loader does not know the checkout directory; a coherent file
        # naming another slug is the directory-keyed validators' catch.
        assert merged_env(envfile)["MM_STACK_NAME"] == "meetingminer-other"
