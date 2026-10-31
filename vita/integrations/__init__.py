"""Import adapters normalize external exports without executing their contents."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Application:
    source: str
    id: str
    company: str
    position: str
    description: str
    metadata: dict


@dataclass(frozen=True)
class Export:
    source: str
    exported_at: str | None
    applications: tuple[Application, ...]
    skipped: int = 0


def read_export(source, path, *, statuses=None, include_demo=False):
    # Explicit dispatch keeps the normalized contract independent of Jobenu.
    from vita.integrations.jobenu import read

    if source != "jobenu":
        raise ValueError(f"Unsupported import source: {source}")
    return read(path, statuses=statuses, include_demo=include_demo)
