"""Tests for Codex provider configuration and executable discovery."""

import json
import os
from unittest.mock import MagicMock, mock_open

import pytest

from vita.helpers import extensions, llm


def test_auto_adds_missing_codex_without_prompting(monkeypatch: pytest.MonkeyPatch) -> None:
    add_provider = MagicMock()
    call_codex = MagicMock(return_value="response")
    monkeypatch.setattr(llm, "load_env", lambda: {})
    monkeypatch.setattr(
        llm,
        "get_llm_providers",
        lambda: {"gemini": {"model": "gemini-2.0-flash"}},
    )
    monkeypatch.setattr(llm, "load_config", lambda: {"auto_add_codex_provider": True})
    monkeypatch.setattr(llm, "add_llm_provider", add_provider)
    monkeypatch.setattr(llm, "_call_codex_cli", call_codex)
    monkeypatch.setattr(
        "builtins.input",
        lambda _: pytest.fail("input must not be called when auto-add is enabled"),
    )

    assert llm.generate("system", "user", provider="codex") == "response"
    add_provider.assert_called_once_with("codex", {"model": ""})
    call_codex.assert_called_once_with("system", "user", "")


def test_manual_confirmation_adds_missing_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    add_provider = MagicMock()
    monkeypatch.setattr(llm, "load_env", lambda: {})
    monkeypatch.setattr(llm, "get_llm_providers", lambda: {"gemini": {}})
    monkeypatch.setattr(llm, "load_config", lambda: {"auto_add_codex_provider": False})
    monkeypatch.setattr(llm, "add_llm_provider", add_provider)
    monkeypatch.setattr(llm, "_call_codex_cli", lambda *_: "response")
    monkeypatch.setattr("builtins.input", lambda _: "y")

    assert llm.generate("system", "user", provider="codex") == "response"
    add_provider.assert_called_once_with("codex", {"model": ""})


def test_declining_manual_confirmation_stops_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "load_env", lambda: {})
    monkeypatch.setattr(llm, "get_llm_providers", lambda: {"gemini": {}})
    monkeypatch.setattr(llm, "load_config", lambda: {"auto_add_codex_provider": False})
    monkeypatch.setattr("builtins.input", lambda _: "n")

    with pytest.raises(ValueError, match="Codex is not configured"):
        llm.generate("system", "user", provider="codex")


def test_add_provider_preserves_existing_extension_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    original = {
        "_doc": "test configuration",
        "llm_providers": {"gemini": {"model": "gemini-2.0-flash"}},
        "role_aliases": {"dev": "developer"},
    }
    extensions_file = MagicMock()
    extensions_file.exists.return_value = True
    dump = MagicMock()
    monkeypatch.setattr(extensions, "EXTENSIONS_FILE", extensions_file)
    monkeypatch.setattr("builtins.open", mock_open(read_data=json.dumps(original)))
    monkeypatch.setattr(extensions.json, "dump", dump)

    extensions.add_llm_provider("codex", {"model": ""})

    saved = dump.call_args.args[0]
    assert saved["llm_providers"]["gemini"] == original["llm_providers"]["gemini"]
    assert saved["llm_providers"]["codex"] == {"model": ""}
    assert saved["role_aliases"] == original["role_aliases"]


def test_explicit_codex_path_has_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    executable = "/custom/codex"
    path = MagicMock()
    path.is_file.return_value = True
    which = MagicMock()
    monkeypatch.setenv("VITA_CODEX", executable)
    monkeypatch.setattr(llm, "Path", MagicMock(return_value=path))
    monkeypatch.setattr(llm.shutil, "which", which)

    assert llm._find_codex_cli() == executable
    which.assert_not_called()


def test_discovers_newest_codex_in_vscode_extension_and_updates_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = MagicMock()
    root.is_dir.return_value = True
    old_extension = MagicMock()
    latest_extension = MagicMock()
    root.glob.return_value = (old_extension, latest_extension)
    old_extension.is_dir.return_value = True
    latest_extension.is_dir.return_value = True

    old = MagicMock()
    old.is_file.return_value = True
    old.stat.return_value.st_mtime = 1
    old.parent = "/extensions/old/bin"
    old.__str__.return_value = "/extensions/old/bin/codex"

    latest = MagicMock()
    latest.is_file.return_value = True
    latest.stat.return_value.st_mtime = 2
    latest.parent = "/extensions/latest/bin"
    latest.__str__.return_value = "/extensions/latest/bin/codex"
    old_extension.rglob.return_value = (old,)
    latest_extension.rglob.return_value = (latest,)

    monkeypatch.setenv("VITA_CODEX", "")
    monkeypatch.setenv("CODEX_EXE", "")
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(llm.shutil, "which", lambda _: None)
    monkeypatch.setattr(llm, "_codex_extension_roots", lambda _: (root,))
    monkeypatch.setattr(llm.os, "access", lambda *_: True)

    assert llm._find_codex_cli() == "/extensions/latest/bin/codex"
    assert "/extensions/latest/bin" in os.environ["PATH"].split(os.pathsep)
