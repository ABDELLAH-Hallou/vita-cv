"""vita/helpers/git.py — centralized git operations layer.

All git subprocess calls in the VITA CLI go through this module.
Commands receive typed parameters and return GitResult objects,
keeping business logic in commands/ free of raw subprocess calls.
"""

import subprocess
from dataclasses import dataclass


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class GitResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int


def _run(*args: str, **kwargs) -> GitResult:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        **kwargs,
    )
    return GitResult(
        ok=result.returncode == 0,
        stdout=result.stdout.strip(),
        stderr=result.stderr.strip(),
        returncode=result.returncode,
    )


# ── Repository state ──────────────────────────────────────────────────────────

def init() -> GitResult:
    return _run("init")


def current_branch() -> str:
    r = _run("branch", "--show-current")
    return r.stdout or "(detached HEAD)"


def all_branches() -> list[str]:
    r = _run("branch", "--list")
    return [b.strip().lstrip("* ") for b in r.stdout.splitlines() if b.strip()]


def has_commits() -> bool:
    return _run("rev-parse", "HEAD").ok


def is_clean() -> bool:
    return not bool(_run("status", "--porcelain").stdout)

# git add -A; git commit -m "update cv"; git push --all origin
# ── Staging & committing ──────────────────────────────────────────────────────

def add_all(branch :str=None) -> GitResult:
    if not branch:
        return _run("add","-A")
    return _run("add", ".")


def commit(message: str) -> GitResult:
    return _run("commit", "-m", message)


def add_and_commit(message: str="", branch:str=None) -> GitResult:
    add_all(branch)
    return commit(message)


def stash() -> GitResult:
    return _run("stash")

# ── Pushing ──────────────────────────────────────────────────────────────────

def push(remote: str = "origin", branch: str = None, force: bool = False) -> GitResult:
    cmd = ["push"]
    if force:
        cmd.append("--force")
    if branch:
        cmd.append(branch)
    else:
        cmd.append("--all")
    if remote != "origin":
        cmd.append(remote)
    return _run(*cmd)

def add_commit_push(remote: str = "origin", branch: str = None, message:str="", force: bool = False) -> GitResult:
    add_and_commit(message,branch)
    return push(remote, branch, force)

# ── Branching ─────────────────────────────────────────────────────────────────

def checkout(branch: str) -> GitResult:
    return _run("checkout", branch)


def create_branch(branch: str) -> GitResult:
    return _run("checkout", "-b", branch)


def branch_exists(branch: str) -> bool:
    return branch in all_branches()


# ── Inspection ────────────────────────────────────────────────────────────────

def diff(base: str, target: str, paths: list[str] | None = None) -> GitResult:
    """
    Show diff between base and target branches.

    Args:
        base:   The reference base branch (e.g. 'gen-swe').
        target: The branch to compare against base.
        paths:  Optional list of path filters (e.g. ['*.tex', 'sections/']).
    """
    cmd = ["diff", f"{base}...{target}"]
    if paths:
        cmd += ["--"] + paths
    return _run(*cmd)
