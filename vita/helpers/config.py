"""vita/helpers/config.py — configuration paths, defaults, and I/O.

Responsible for:
- Defining the canonical file paths for the .vita/ directory
- Storing and providing access to default configuration values
- Loading and saving .vita/config.json
"""

import json
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

VITA_DIR    = Path(".vita")
CONFIG_FILE = VITA_DIR / "config.json"

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_CONFIG: dict = {
    "author": "",
    "output_dir": "out",
    "output_filename": "cv-{author}.pdf",
    "tex_entry": "main.tex",
    "build_mode": "auto",
    "default_base_branch": "master",
    "strict_mode": False,
    "allow_multiple_per_company": True,
    "warn_on_duplicate": True,
}

# ── I/O ───────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load config.json, falling back to DEFAULT_CONFIG if not found."""
    if not CONFIG_FILE.exists():
        print("⚠️  No .vita/config.json found. Run `vita init` first.")
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(data: dict) -> None:
    """Write data to .vita/config.json."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)
