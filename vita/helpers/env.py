"""vita/helpers/env.py — zero-dependency .env file management.

Responsible for reading and writing secrets to .vita/.env.
"""

import os
import re

from vita.helpers.config import VITA_DIR

ENV_FILE = VITA_DIR / ".env"
ENV_EXAMPLE_FILE = VITA_DIR / ".env.example"


def read_env_file() -> dict[str, str]:
    """Read project settings without leaking them into subsequent project runs."""
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
                value = value.strip()
                if value.startswith(("\"", "'")):
                    quote = value[0]
                    end = value.find(quote, 1)
                    if end == -1 or (value[end + 1:].strip() and not value[end + 1:].strip().startswith("#")):
                        raise ValueError(f"Invalid quoted value for {key} in .vita/.env")
                    value = value[1:end]
                else:
                    value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
                env_vars[key] = value
                
    return env_vars


def load_env() -> dict[str, str]:
    """Return project settings with process environment taking precedence."""
    return {**read_env_file(), **os.environ}


def env_example_text() -> str:
    return """# Extraction is opt-in; existing provider settings remain the fallback.
ENABLE_JD_EXTRACTION=false
# EXTRACTION_PROVIDER=gemini
# EXTRACTION_MODEL=gemini-2.5-flash
# Optional shared approved-requirements store (otherwise Git common dir or .vita).
# VITA_REQUIREMENTS_DIR=/absolute/path/to/shared-requirements
# ANALYSIS_PROVIDER=openai
# ANALYSIS_MODEL=gpt-4o
# Review inherits ANALYSIS_* unless explicitly configured.
# REVIEW_PROVIDER=openai
# REVIEW_MODEL=gpt-4o
# ADAPT_PROVIDER=gemini
# ADAPT_MODEL=gemini-2.5-flash
# COVER_PROVIDER=gemini
# COVER_MODEL=gemini-2.5-flash
# One shared attempt budget per operation, including format recovery (1..5).
VITA_PROVIDER_MAX_ATTEMPTS=3
# Capped exponential backoff; Retry-After longer than the cap stops the run.
VITA_PROVIDER_RETRY_BASE_SECONDS=1
VITA_PROVIDER_RETRY_MAX_SECONDS=30
# Diagnostics default to technical metadata; sanitized mode captures structure only.
VITA_DIAGNOSTIC_CONTENT=off
# Absolute application project root (set explicitly for staging subprocesses).
# VITA_PROJECT_ROOT=/absolute/application/project
# Optional absolute persistent traces store (outside temporary staging).
# VITA_DIAGNOSTICS_DIR=/absolute/private/traces
# W3C v00 context from the parent; never put credentials in these IDs.
# VITA_TRACEPARENT=00-<32-lowercase-hex-trace-id>-<16-hex-parent-span>-01
OPENAI_API_KEY=your_openai_key
OPENROUTER_API_KEY=your_openrouter_key
GEMINI_API_KEY=your_gemini_key
ANTHROPIC_API_KEY=your_anthropic_key
"""


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

