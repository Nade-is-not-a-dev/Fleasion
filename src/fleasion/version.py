"""Project version helpers."""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_DISTRIBUTION_NAME = 'Fleasion'
_UNKNOWN_VERSION = '0.0.0'


def _read_pyproject_version() -> str | None:
    for parent in Path(__file__).resolve().parents:
        pyproject_path = parent / 'pyproject.toml'
        if not pyproject_path.is_file():
            continue

        pyproject = tomllib.loads(pyproject_path.read_text(encoding='utf-8'))
        project = pyproject.get('project')
        if not isinstance(project, dict):
            return None

        project_version = project.get('version')
        if isinstance(project_version, str) and project_version:
            return project_version

        return None

    return None


def _read_installed_version() -> str | None:
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return None


def read_version() -> str:
    return _read_pyproject_version() or _read_installed_version() or _UNKNOWN_VERSION
