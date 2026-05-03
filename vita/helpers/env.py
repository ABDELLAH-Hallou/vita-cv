"""vita/helpers/env.py — zero-dependency .env file management.

Responsible for reading and writing secrets to .vita/.env.
"""

import os
from pathlib import Path
from vita.helpers.config import VITA_DIR

ENV_FILE = VITA_DIR / ".env"
ENV_EXAMPLE_FILE = VITA_DIR / ".env.example"


def load_env() -> dict[str, str]:
    """Load the .env file into a dictionary and into os.environ."""
    env_vars = {}
    if not ENV_FILE.exists():
        return env_vars

    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            # Split on the first '='
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"\'') # remove optional quotes
                env_vars[key] = value
                os.environ[key] = value
                
    return env_vars


def set_env_key(key: str, value: str) -> None:
    """Safely append or update a key in the .env file."""
    lines = []
    updated = False
    
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    # Process lines to find and update existing key
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
            
        if stripped.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            updated = True
            break
            
    if not updated:
        # Add a newline if the last line doesn't have one
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{key}={value}\n")
        
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)
    
    # Update current process environment
    os.environ[key] = value

