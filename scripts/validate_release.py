"""Fail a release when its tag and package version do not match."""

import sys

from vita import __version__
from vita.helpers.release import validate_release_tag

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_release.py vX.Y.Z")
    try:
        validate_release_tag(sys.argv[1])
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(f"Validated release {sys.argv[1]} for vita-cv {__version__}")
