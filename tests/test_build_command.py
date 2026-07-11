import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

from fleasion.scripts import build


def test_build_runs_pyinstaller_with_reproducible_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
        )
    )
    monkeypatch.setattr(build, '_project_root', lambda: tmp_path)
    monkeypatch.setattr(build, 'setup_script_logging', lambda: None)
    monkeypatch.setattr(build.subprocess, 'run', run)
    monkeypatch.setenv('FLEASION_BUILD_TEST', 'preserved')
    monkeypatch.setenv('PYTHONHASHSEED', 'random')

    assert build.main() == 0

    environment = run.call_args.kwargs['env']
    assert environment['FLEASION_BUILD_TEST'] == 'preserved'
    assert environment['PYTHONHASHSEED'] == '0'
    assert environment['SOURCE_DATE_EPOCH'] == '0'
    assert environment['LC_ALL'] == 'C.UTF-8'
    assert environment['TZ'] == 'UTC'
    run.assert_called_once_with(
        [
            sys.executable,
            '-m',
            'PyInstaller',
            '--clean',
            '--noconfirm',
            'Fleasion.spec',
        ],
        cwd=tmp_path,
        env=environment,
        check=False,
    )
