import json
import subprocess
from pathlib import Path
from datetime import datetime

# ── Paths ────────────────────────────────────────────────────────────────────

VITA_DIR      = Path(".vita")
CONFIG_FILE   = VITA_DIR / "config.json"
REGISTRY_FILE = VITA_DIR / "companies.json"
LOG_FILE      = VITA_DIR / "logs" / "vita.log"

# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
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

ROLE_ALIASES = {
    "software engineer":        "swe",
    "software engineering":     "swe",
    "data engineer":            "de",
    "data engineering":         "de",
    "machine learning":         "ml",
    "machine learning engineer":"ml",
    "data scientist":           "ds",
    "data science":             "ds",
    "artificial intelligence":  "ai",
    "backend":                  "be",
    "backend engineer":         "be",
    "frontend":                 "fe",
    "frontend engineer":        "fe",
    "full stack":               "fs",
    "full stack engineer":      "fs",
    "devops":                   "devops",
    "product manager":          "pm",
    "infrastructure engineer":  "infra",
    "pre-training engineer":    "pt",
    "inference engineer":       "ie",
}

# ── Config & Registry I/O ────────────────────────────────────────────────────

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        print("⚠️  No .vita/config.json found. Run `vita init` first.")
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(data: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_registry() -> dict:
    if not REGISTRY_FILE.exists():
        print("⚠️  No .vita/companies.json found. Run `vita init` first.")
        return {}
    with open(REGISTRY_FILE) as f:
        return json.load(f)


def save_registry(data: dict) -> None:
    with open(REGISTRY_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ── Git Helpers ───────────────────────────────────────────────────────────────

def get_current_branch() -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True, text=True
    )
    return result.stdout.strip() or "(detached HEAD)"


def get_all_branches() -> list[str]:
    result = subprocess.run(
        ["git", "branch", "--list"],
        capture_output=True, text=True
    )
    return [b.strip().lstrip("* ") for b in result.stdout.splitlines() if b.strip()]

def has_commits() -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True
    )
    return result.returncode == 0

def is_git_clean() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True
    )
    return not bool(result.stdout.strip())

def run_shell(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)

# ── Utilities ─────────────────────────────────────────────────────────────────

def normalize_role(role: str) -> str:
    """Map verbose role names to short codes, or slugify anything else."""
    role_lower = role.lower().strip()
    if role_lower in ROLE_ALIASES:
        return ROLE_ALIASES[role_lower]
    return role_lower.replace(" ", "-")


def log(msg: str) -> None:
    """Append a timestamped entry to the VITA log file."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")
