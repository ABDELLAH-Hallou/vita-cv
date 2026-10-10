"""Release validation shared by automation and regression tests."""

import re

from vita import __version__

RELEASE_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CONVENTIONAL_PR_TITLE = re.compile(
    r"^(build|chore|ci|deps|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(?:\([a-z0-9][a-z0-9._/-]*\))?!?: \S.*$"
)


def validate_release_tag(tag: str, package_version: str = __version__) -> None:
    if not RELEASE_TAG.fullmatch(tag):
        raise ValueError(f"Release tag must use stable SemVer format vX.Y.Z; received {tag!r}")
    tagged_version = tag.removeprefix("v")
    if tagged_version != package_version:
        raise ValueError(
            f"Tag {tag!r} does not match vita.__version__ {package_version!r}"
        )


def validate_pr_title(title: str) -> None:
    if not CONVENTIONAL_PR_TITLE.fullmatch(title):
        raise ValueError(
            "Pull request title must follow Conventional Commits, for example "
            "'fix(cli): handle missing config' or 'feat!: redesign configuration'"
        )
