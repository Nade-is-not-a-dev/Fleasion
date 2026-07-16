from __future__ import annotations

import subprocess
from pathlib import Path

from pytest import MonkeyPatch

from fleasion.scripts import _macos_build, build


def _set_reproducible_environment(monkeypatch: MonkeyPatch) -> None:
    for name, value in build.REPRODUCIBLE_ENV.items():
        monkeypatch.setenv(name, value)


def test_build_dispatches_to_macos_release_builder(monkeypatch: MonkeyPatch) -> None:
    _set_reproducible_environment(monkeypatch)
    monkeypatch.setattr(build.sys, 'platform', 'darwin')
    monkeypatch.delenv(build.MACOS_SLICE_BUILD_ENV, raising=False)
    calls: list[None] = []

    def build_macos_release() -> None:
        calls.append(None)

    monkeypatch.setattr(_macos_build, 'build_macos_release', build_macos_release)

    assert build.main([]) == 0
    assert calls == [None]


def test_macos_slice_build_runs_pyinstaller_without_redispatch(monkeypatch: MonkeyPatch) -> None:
    _set_reproducible_environment(monkeypatch)
    monkeypatch.setattr(build.sys, 'platform', 'darwin')
    monkeypatch.setenv(build.MACOS_SLICE_BUILD_ENV, '1')
    calls: list[tuple[list[str] | None, bool]] = []

    def run_pyinstaller(arguments: list[str] | None, *, skip_setup_logging: bool) -> None:
        calls.append((arguments, skip_setup_logging))

    monkeypatch.setattr(build, 'run_pyinstaller', run_pyinstaller)

    assert build.main(['--clean']) == 0
    assert calls == [(['--clean', '--noconfirm', 'Fleasion.spec'], True)]


def test_macos_versions_are_normalized_for_comparison() -> None:
    assert _macos_build.MacOSBuilder._version_tuple('11.0') == (11, 0, 0)
    assert _macos_build.MacOSBuilder._version_tuple('11.0.0') == (11, 0, 0)


def test_universal_verification_ignores_helper_symlink_targets(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    builder = object.__new__(_macos_build.MacOSBuilder)
    builder.executable_name = 'Fleasion-v1.0.0'
    resources = tmp_path / 'Contents/Resources'
    frameworks = tmp_path / 'Contents/Frameworks'
    resources.mkdir(parents=True)
    frameworks.mkdir(parents=True)

    helper_paths: dict[str, Path] = {}
    framework_helpers: list[Path] = []
    for architecture in ('arm64', 'x86_64'):
        helper_name = f'fleasion-proxy-helper-{architecture}'
        framework_helper = frameworks / helper_name
        framework_helper.touch()
        resource_helper = resources / helper_name
        resource_helper.symlink_to(framework_helper)
        helper_paths[helper_name] = resource_helper
        framework_helpers.append(framework_helper)

    def require_architectures(_file_path: Path, *_required: str) -> None:
        return None

    def require_payload(
        _app_path: Path,
        relative_path: str,
        _build_label: str,
        *,
        executable: bool = False,
    ) -> Path:
        assert executable
        return helper_paths[relative_path]

    def require_only_architectures(_file_path: Path, *_required: str) -> None:
        return None

    monkeypatch.setattr(builder, '_require_architectures', require_architectures)
    monkeypatch.setattr(builder, '_require_payload', require_payload)
    monkeypatch.setattr(builder, '_require_only_architectures', require_only_architectures)
    monkeypatch.setattr(builder, '_regular_files', lambda _app_path: framework_helpers)

    builder._verify_app_architectures(tmp_path)


def test_x86_build_uses_the_project_python_pin(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    builder = object.__new__(_macos_build.MacOSBuilder)
    builder.x86_environment_path = tmp_path / 'venv-x86'
    builder.x86_uv_path = tmp_path / 'uv-x86_64'
    builder.base_environment = {}
    uv_calls: list[tuple[str, ...]] = []
    commands: list[list[str]] = []
    verified_slices: list[tuple[str, str]] = []

    def x86_uv(*arguments: str, capture_output: bool = False) -> str:
        assert not capture_output
        uv_calls.append(arguments)
        return ''

    def subprocess_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, '', '')

    def ensure_x86_uv() -> None:
        return None

    def verify_slice(architecture: str, label: str) -> None:
        verified_slices.append((architecture, label))

    monkeypatch.setattr(builder, '_ensure_x86_uv', ensure_x86_uv)
    monkeypatch.setattr(builder, '_x86_uv', x86_uv)
    monkeypatch.setattr(builder, '_verify_slice', verify_slice)
    monkeypatch.setattr(_macos_build, 'subprocess_run', subprocess_run)

    builder._build_x86_64()

    assert uv_calls == [('sync', '--locked', '--group', 'dev')]
    assert commands == [
        ['arch', '-x86_64', str(builder.x86_uv_path), 'run', '--no-sync', 'build', '--clean']
    ]
    assert verified_slices == [('x86_64', 'Intel build')]
