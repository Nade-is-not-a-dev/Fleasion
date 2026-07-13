import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PyQt6.QtWidgets import QApplication

from fleasion.gui.modifications_tab import CustomFFlagEditor, FFlagBrowserDialog, FastFlagValueDelegate


def _qapp():
    return QApplication.instance() or QApplication([])


def test_fflag_browser_reports_retrieved_and_filtered_totals(monkeypatch):
    app = _qapp()
    monkeypatch.setattr(FFlagBrowserDialog, '_refresh', lambda _self: None)
    dialog = FFlagBrowserDialog()
    dialog._apply_flags(
        {
            'DFFlagAlpha': 'True',
            'DFFlagBeta': 'False',
            'DFIntTargetFps': '60',
            'FFlagGamma': 'True',
            'FIntLevel': '2',
            'UnclassifiedFlag': 'enabled',
        }
    )

    assert dialog._count.text() == 'Showing 6 FastFlags • 6 retrieved from Roblox'
    assert dialog._table.columnCount() == 2
    assert dialog._family_filter.minimumWidth() == 165

    dialog._family_filter.setCurrentIndex(dialog._family_filter.findData('DFFlag'))
    assert dialog._count.text() == 'Showing 2 FastFlags • 6 retrieved from Roblox'

    dialog._search.setText('beta')
    assert dialog._count.text() == 'Showing 1 FastFlags • 6 retrieved from Roblox'
    assert app is not None


def test_fflag_browser_extracts_current_values_and_selection(monkeypatch):
    app = _qapp()
    monkeypatch.setattr(FFlagBrowserDialog, '_refresh', lambda _self: None)
    assert FFlagBrowserDialog._extract_flags(
        {'applicationSettings': {'FFlagExample': True, 'DFIntLimit': 120, 'skip': []}}
    ) == {'FFlagExample': 'True', 'DFIntLimit': '120'}
    with pytest.raises(ValueError, match='application FastFlags'):
        FFlagBrowserDialog._extract_flags({})

    dialog = FFlagBrowserDialog()
    dialog._apply_flags({'FFlagExample': 'True'})
    dialog._table.selectRow(0)
    app.processEvents()
    dialog._add_selected()

    assert dialog.selected_flags == {'FFlagExample': 'True'}


def test_custom_fflag_editor_uses_an_edit_on_demand_boolean_selector():
    app = _qapp()
    config = SimpleNamespace(
        custom_fflags={'FFlagExample': 'True', 'DFIntExample': '60'},
        custom_fflags_enabled=False,
    )
    proxy = SimpleNamespace(refresh_custom_fflag_interception=lambda: None)

    editor = CustomFFlagEditor(config, proxy)

    assert editor._table.rowCount() == 2
    assert editor._table.cellWidget(0, 1) is None
    assert isinstance(editor._table.itemDelegateForColumn(1), FastFlagValueDelegate)
    assert app is not None
