"""Regression coverage for core workflows and release invariants."""

import os
from pathlib import Path

import pytest

import vita
from vita.commands import run as pipeline
from vita.commands import sync
from vita.helpers import config, env, registry
from vita.helpers.release import validate_release_tag

pytestmark = pytest.mark.regression


def test_release_version_is_stable_semver() -> None:
    validate_release_tag(f"v{vita.__version__}")


@pytest.mark.parametrize("tag", ["2.3.0", "v2.3", "v2.3.0rc1", "v02.3.0"])
def test_release_rejects_invalid_tags(tag: str) -> None:
    with pytest.raises(ValueError, match="stable SemVer"):
        validate_release_tag(tag, "2.3.0")


def test_release_rejects_version_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        validate_release_tag("v9.9.9", "2.3.0")


def test_pipeline_runs_all_steps_and_only_localizes_adapt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        pipeline,
        "ai_step_run",
        lambda step, **kwargs: calls.append((step, kwargs)),
    )

    pipeline.run(auto=True, language="fr", provider="codex")

    assert calls == [
        ("analyze", {"language": None, "auto": True, "provider": "codex"}),
        ("adapt", {"language": "fr", "auto": True, "provider": "codex"}),
        ("review", {"language": None, "auto": True, "provider": "codex"}),
    ]


def test_environment_file_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".vita" / ".env"
    monkeypatch.setattr(env, "ENV_FILE", env_file)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    env.set_env_key("OPENAI_API_KEY", "first")
    env.set_env_key("OPENAI_API_KEY", "second=value")

    assert env.load_env() == {"OPENAI_API_KEY": "second=value"}
    assert os.environ["OPENAI_API_KEY"] == "second=value"
    assert env_file.read_text(encoding="utf-8") == "OPENAI_API_KEY=second=value\n"


def test_config_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)
    expected = {**config.DEFAULT_CONFIG, "author": "Test User"}

    config.save_config(expected)

    assert config.load_config() == expected


def test_role_normalization_uses_aliases_and_slugifies_unknown_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vita.helpers.extensions.merged_role_aliases",
        lambda builtins: builtins,
    )

    assert registry.normalize_role(" Software Engineer ") == "swe"
    assert registry.normalize_role("Platform Reliability Engineer") == (
        "platform-reliability-engineer"
    )


def test_sync_merges_nested_defaults_without_overwriting_values() -> None:
    defaults = {"provider": {"model": "default", "timeout": 10}, "enabled": True}
    current = {"provider": {"model": "custom"}}

    merged, added = sync._merge_missing(defaults, current)

    assert merged == {
        "provider": {"model": "custom", "timeout": 10},
        "enabled": True,
    }
    assert added == 2


@pytest.mark.parametrize(
    ("branch", "expected"),
    [
        ("etp-openai-ml", ("openai", "ml")),
        ("etp-acme-senior-data-engineer", ("acme", "senior-data-engineer")),
        ("master", None),
        ("etp-incomplete", None),
    ],
)
def test_sync_parses_employer_branches(branch: str, expected: tuple[str, str] | None) -> None:
    assert sync._parse_etp_branch(branch) == expected
