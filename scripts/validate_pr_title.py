"""Validate that a pull request title follows Conventional Commits."""

import sys

from vita.helpers.release import validate_pr_title

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_pr_title.py 'type(scope): description'")
    try:
        validate_pr_title(sys.argv[1])
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(f"Validated Conventional Commit pull request title: {sys.argv[1]}")
