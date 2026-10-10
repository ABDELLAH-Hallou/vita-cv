"""Release validation shared by automation and regression tests."""

import re

from vita import __version__

RELEASE_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def validate_release_tag(tag: str, package_version: str = __version__) -> None:
    if not RELEASE_TAG.fullmatch(tag):
        raise ValueError(f"Release tag must use stable SemVer format vX.Y.Z; received {tag!r}")
    tagged_version = tag.removeprefix("v")
    if tagged_version != package_version:
        raise ValueError(
            f"Tag {tag!r} does not match vita.__version__ {package_version!r}"
        )
