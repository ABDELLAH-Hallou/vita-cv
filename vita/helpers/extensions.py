"""vita/helpers/extensions.py — user-defined overrides for built-in maps.

Loads `.vita/extensions.json` from the user's CV project and merges custom
role aliases and language codes on top of the built-in defaults.

User values always WIN on conflict — allowing full customization without
editing the package source.
"""

import json
from pathlib import Path
from vita.helpers.config import VITA_DIR

EXTENSIONS_FILE = VITA_DIR / "extensions.json"


def _load_raw() -> dict:
    """Load extensions.json as a raw dict. Returns empty dict if absent."""
    if not EXTENSIONS_FILE.exists():
        return {}
    try:
        with open(EXTENSIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"⚠️  Malformed .vita/extensions.json — ignoring user extensions. ({e})")
        return {}


def merged_role_aliases(builtin: dict[str, str]) -> dict[str, str]:
    """
    Return role aliases with user overrides merged on top of built-ins.

    User entries win on key conflict. Keys starting with '_' are skipped
    (they act as documentation/comment fields in the JSON).
    """
    raw = _load_raw()
    user_aliases = {
        k.lower(): v
        for k, v in raw.get("role_aliases", {}).items()
        if not k.startswith("_")
    }
    return {**builtin, **user_aliases}


def merged_language_map(builtin: dict[str, str]) -> dict[str, str]:
    """
    Return language codes with user overrides merged on top of built-ins.

    User entries win on key conflict. Keys starting with '_' are skipped
    (they act as documentation/comment fields in the JSON).
    """
    raw = _load_raw()
    user_langs = {
        k.lower(): v
        for k, v in raw.get("language_map", {}).items()
        if not k.startswith("_")
    }
    return {**builtin, **user_langs}


def get_llm_providers() -> dict[str, dict]:
    """
    Return the configured LLM providers and their models from extensions.json.
    
    Returns a dictionary mapping provider names to their config (e.g., {'openai': {'model': 'gpt-4o'}}).
    Keys starting with '_' are skipped.
    """
    raw = _load_raw()
    providers = {
        k.lower(): v
        for k, v in raw.get("llm_providers", {}).items()
        if not k.startswith("_")
    }
    return providers
