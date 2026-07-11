from pathlib import Path


def test_build_workflow_contract() -> None:
    workflow = Path('.github/workflows/build.yml').read_text(encoding='utf-8')

    assert workflow.count('run: uv run build') == 2
    assert 'uv run pyinstaller' not in workflow
    assert "PYTHONHASHSEED: '0'" in workflow
    assert "SOURCE_DATE_EPOCH: '0'" in workflow
    assert 'LC_ALL: C.UTF-8' in workflow
    assert 'TZ: UTC' in workflow
    assert (
        'artifact_name: Fleasion-v${{ needs.prepare.outputs.app_version }}-Windows.exe'
        in workflow
    )
    assert (
        'artifact_name: Fleasion-v${{ needs.prepare.outputs.app_version }}-Linux'
        in workflow
    )
    assert (
        'artifact_name: Fleasion-v${{ needs.prepare.outputs.app_version }}-MacOS-Universal.zip'
        in workflow
    )
    assert 'name: ${{ matrix.artifact_name }}' in workflow
    assert 'path: ${{ matrix.artifact_path }}' in workflow
    assert 'archive: false' in workflow
    assert 'Verify Linux audio runtime' in workflow
    assert 'Linux package must use host audio backend libraries' in workflow


def test_draft_release_workflow_contract() -> None:
    workflow = Path('.github/workflows/draft-release.yml').read_text(encoding='utf-8')

    assert 'uses: ./.github/workflows/build.yml' in workflow
    assert 'uses: actions/download-artifact@' in workflow
    assert 'pattern: Fleasion-v${{ needs.build-packages.outputs.app_version }}-*' in workflow
    assert 'merge-multiple: true' in workflow
    assert 'skip-decompress: true' in workflow
    assert 'uses: softprops/action-gh-release@' in workflow
    assert 'tag_name: v${{ needs.build-packages.outputs.app_version }}' in workflow
    assert 'target_commitish: ${{ github.sha }}' in workflow
    assert 'draft: true' in workflow
    assert 'files: release-files/*' in workflow
