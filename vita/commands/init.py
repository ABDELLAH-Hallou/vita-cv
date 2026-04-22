"""vita init — scaffold the .vita/ configuration directory."""

import json
import shutil
from vita.helpers.config import VITA_DIR, CONFIG_FILE, DEFAULT_CONFIG
from vita.helpers.registry import REGISTRY_FILE
from vita.helpers.extensions import EXTENSIONS_FILE
from vita.helpers import git


def run(force: bool = False) -> None:
    if VITA_DIR.exists():
        if force:
            print(f"Force flag detected. Deleting existing '{VITA_DIR}'...")
            shutil.rmtree(VITA_DIR)
        else:
            print("VITA is already initialized in this directory.")
            print(f"   Run `vita init -f` or delete '{VITA_DIR}/' manually if you want to re-initialize.")
            return

    # Create directory structure
    (VITA_DIR / "logs").mkdir(parents=True)

    # Write default config
    with open(CONFIG_FILE, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)

    # Write empty company registry
    with open(REGISTRY_FILE, "w") as f:
        json.dump({}, f, indent=2)

    # Scaffold extensions.json — empty maps ready or the user to fill
    extensions_template = {
        "_doc": "See EXTENSIONS.md for full documentation. Keys starting with '_' are ignored.",
        "role_aliases": {},
        "language_map": {}
    }
    with open(EXTENSIONS_FILE, "w") as f:
        json.dump(extensions_template, f, indent=2)

    # Keep logs/ tracked by git
    (VITA_DIR / "logs" / ".gitkeep").touch()

    # Initialize git repo
    git.init()

    print("VITA initialized.")
    print(f"   {CONFIG_FILE}         — edit to set author, tex_entry, etc.")
    print(f"   {REGISTRY_FILE}   — company registry (empty)")
    print(f"   {EXTENSIONS_FILE}   — add your custom role aliases and languages")
    print(f"   {VITA_DIR}/logs/             — CLI activity logs")
    print()
    print("Next: edit .vita/extensions.json to customize role aliases and languages.")
    print("   See EXTENSIONS.md for the full format reference.")
    print()
    print("Then run: vita new etp <company> <role>")
