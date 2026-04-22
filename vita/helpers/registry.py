"""vita/helpers/registry.py — company registry I/O and role normalization.

Responsible for:
- Defining the registry file path
- Loading and saving .vita/companies.json
- Normalizing role names via a canonical alias table
"""

import json
from pathlib import Path
from vita.helpers.config import VITA_DIR

# ── Path ──────────────────────────────────────────────────────────────────────

REGISTRY_FILE = VITA_DIR / "companies.json"

# ── Role aliases ──────────────────────────────────────────────────────────────

ROLE_ALIASES: dict[str, str] = {
    "software engineer":         "swe",
    "software engineering":      "swe",
    "data engineer":             "de",
    "data engineering":          "de",
    "machine learning":          "ml",
    "machine learning engineer": "ml",
    "data scientist":            "ds",
    "data science":              "ds",
    "artificial intelligence":   "ai",
    "backend":                   "be",
    "backend engineer":          "be",
    "frontend":                  "fe",
    "frontend engineer":         "fe",
    "full stack":                "fs",
    "full stack engineer":       "fs",
    "devops":                    "devops",
    "product manager":           "pm",
    "infrastructure engineer":   "infra",
    "pre-training engineer":     "pt",
    "inference engineer":        "ie",
}


def normalize_role(role: str) -> str:
    """Map a verbose role name to its short code, or slugify anything else.

    Built-in aliases are merged with any user-defined aliases from
    .vita/extensions.json ("role_aliases" key). User values win on conflict.
    """
    from vita.helpers.extensions import merged_role_aliases
    aliases = merged_role_aliases(ROLE_ALIASES)
    role_lower = role.lower().strip()
    return aliases.get(role_lower, role_lower.replace(" ", "-"))


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_registry() -> dict:
    """Load companies.json, returning an empty dict if not found."""
    if not REGISTRY_FILE.exists():
        print("⚠️  No .vita/companies.json found. Run `vita init` first.")
        return {}
    with open(REGISTRY_FILE) as f:
        return json.load(f)


def save_registry(data: dict) -> None:
    """Write data to .vita/companies.json."""
    with open(REGISTRY_FILE, "w") as f:
        json.dump(data, f, indent=2)
