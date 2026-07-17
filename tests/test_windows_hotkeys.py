import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from fleasion.gui.windows_hotkeys import (
    MOD_CTRL,
    MOD_SHIFT,
    binding_text,
    modifier_mask_for_virtual_key,
    normalize_binding,
)


def test_scan_code_bindings_allow_bare_keys_modifier_keys_and_combinations():
    assert normalize_binding({'scan_code': 0x1E, 'extended': False, 'modifiers': 0}) == {
        'scan_code': 0x1E,
        'extended': False,
        'modifiers': 0,
    }
    assert normalize_binding({'scan_code': 0x1D, 'extended': False, 'modifiers': 0}) is not None
    assert normalize_binding({'scan_code': 0x3B, 'extended': False, 'modifiers': MOD_CTRL | MOD_SHIFT}) is not None
    assert normalize_binding({'scan_code': 0, 'extended': False, 'modifiers': 0}) is None
    assert normalize_binding({'scan_code': 0x1E, 'extended': False, 'modifiers': 0x10}) is None


def test_scan_code_binding_labels_and_modifier_categories_are_human_readable():
    assert binding_text({'scan_code': 0x1E, 'extended': False, 'modifiers': 0}) == 'A'
    assert binding_text({'scan_code': 0x1D, 'extended': False, 'modifiers': 0}) == 'Left Ctrl'
    assert binding_text({'scan_code': 0x3B, 'extended': False, 'modifiers': MOD_CTRL}) == 'Ctrl+F1'
    assert modifier_mask_for_virtual_key(0xA2) == MOD_CTRL
