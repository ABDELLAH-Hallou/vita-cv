"""vita init — scaffold the .vita/ configuration directory."""

import json
import shutil
from vita.utils import VITA_DIR, CONFIG_FILE, REGISTRY_FILE, DEFAULT_CONFIG, run_shell


def run(force: bool = False) -> None:
    if VITA_DIR.exists():
        if force:
            print(f"⚠️  Force flag detected. Deleting existing '{VITA_DIR}'...")
            shutil.rmtree(VITA_DIR)
        else:
            print("⚠️  VITA is already initialized in this directory.")
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

    # Keep logs/ tracked by git
    (VITA_DIR / "logs" / ".gitkeep").touch()

    # Initialize git repo
    run_shell(["git", "init"])

    print("✅ VITA initialized.")
    print(f"   {CONFIG_FILE}      — edit to set author, tex_entry, etc.")
    print(f"   {REGISTRY_FILE}  — company registry (empty)")
    print(f"   {VITA_DIR}/logs/          — CLI activity logs")
    print()
    print("💡 Next step: vita new etp <company> <role>")
