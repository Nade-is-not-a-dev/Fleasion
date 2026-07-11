"""Build the standalone Fleasion application."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from ._logger import setup_script_logging

log = logging.getLogger(__name__)


_REPRODUCIBLE_ENV = {
    'PYTHONHASHSEED': '0',
    'SOURCE_DATE_EPOCH': '0',
    'LC_ALL': 'C.UTF-8',
    'TZ': 'UTC',
}


def _project_root() -> Path:
    for directory in (Path.cwd(), *Path.cwd().parents):
        if (directory / 'pyproject.toml').is_file() and (directory / 'Fleasion.spec').is_file():
            return directory

    msg = 'Could not find the Fleasion project root containing Fleasion.spec.'
    raise FileNotFoundError(msg)


def main() -> int:
    """Build Fleasion with its PyInstaller specification."""
    setup_script_logging()
    project_root = _project_root()
    command = [
        sys.executable,
        '-m',
        'PyInstaller',
        '--clean',
        '--noconfirm',
        'Fleasion.spec',
    ]
    environment = os.environ.copy()
    environment.update(_REPRODUCIBLE_ENV)

    log.info('Building Fleasion from %s', project_root)
    result = subprocess.run(
        command,
        cwd=project_root,
        env=environment,
        check=False,
    )
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
