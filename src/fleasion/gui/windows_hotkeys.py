"""Windows scan-code hotkeys for custom FastFlag toggles.

Bindings are captured as physical scan codes and converted to virtual keys for
``GetAsyncKeyState`` polling.  Polling is deliberately used instead of a
keyboard hook: it observes input but cannot consume or block the user's keys.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Mapping
from ctypes import wintypes

from PyQt6.QtCore import QObject, pyqtSignal

from ..utils import log_buffer


MOD_SHIFT = 0x01
MOD_CTRL = 0x02
MOD_ALT = 0x04
MOD_WIN = 0x08
MODIFIER_MASK = MOD_SHIFT | MOD_CTRL | MOD_ALT | MOD_WIN

_VK_SHIFT = 0x10
_VK_CONTROL = 0x11
_VK_MENU = 0x12
_VK_LWIN = 0x5B
_VK_RWIN = 0x5C
_VK_LSHIFT = 0xA0
_VK_RSHIFT = 0xA1
_VK_LCONTROL = 0xA2
_VK_RCONTROL = 0xA3
_VK_LMENU = 0xA4
_VK_RMENU = 0xA5


def modifier_mask_for_virtual_key(virtual_key: int) -> int:
    if virtual_key in (_VK_SHIFT, _VK_LSHIFT, _VK_RSHIFT):
        return MOD_SHIFT
    if virtual_key in (_VK_CONTROL, _VK_LCONTROL, _VK_RCONTROL):
        return MOD_CTRL
    if virtual_key in (_VK_MENU, _VK_LMENU, _VK_RMENU):
        return MOD_ALT
    if virtual_key in (_VK_LWIN, _VK_RWIN):
        return MOD_WIN
    return 0


def normalize_binding(binding) -> dict[str, int | bool] | None:
    """Validate a persisted physical-key binding."""
    if not isinstance(binding, Mapping):
        return None
    scan_code = binding.get('scan_code')
    modifiers = binding.get('modifiers', 0)
    extended = binding.get('extended', False)
    if (
        not isinstance(scan_code, int)
        or isinstance(scan_code, bool)
        or not 0 < scan_code <= 0xFF
        or not isinstance(modifiers, int)
        or isinstance(modifiers, bool)
        or modifiers & ~MODIFIER_MASK
        or not isinstance(extended, bool)
    ):
        return None
    return {'scan_code': scan_code, 'extended': extended, 'modifiers': modifiers}


def _fallback_key_name(scan_code: int, extended: bool) -> str:
    names = {
        0x01: 'Esc', 0x0E: 'Backspace', 0x0F: 'Tab', 0x1C: 'Enter',
        0x1D: 'Right Ctrl' if extended else 'Left Ctrl',
        0x2A: 'Left Shift', 0x36: 'Right Shift',
        0x38: 'Right Alt' if extended else 'Left Alt', 0x39: 'Space',
        0x3A: 'Caps Lock', 0x45: 'Num Lock', 0x46: 'Scroll Lock',
        0x47: 'Home', 0x48: 'Up', 0x49: 'Page Up', 0x4B: 'Left',
        0x4D: 'Right', 0x4F: 'End', 0x50: 'Down', 0x51: 'Page Down',
        0x52: 'Insert', 0x53: 'Delete', 0x5B: 'Win',
    }
    if 0x02 <= scan_code <= 0x0B:
        return str((scan_code - 1) % 10)
    if 0x3B <= scan_code <= 0x58:
        return f'F{scan_code - 0x3B + 1}'
    letters = {
        0x10: 'Q', 0x11: 'W', 0x12: 'E', 0x13: 'R', 0x14: 'T', 0x15: 'Y',
        0x16: 'U', 0x17: 'I', 0x18: 'O', 0x19: 'P', 0x1E: 'A', 0x1F: 'S',
        0x20: 'D', 0x21: 'F', 0x22: 'G', 0x23: 'H', 0x24: 'J', 0x25: 'K',
        0x26: 'L', 0x2C: 'Z', 0x2D: 'X', 0x2E: 'C', 0x2F: 'V', 0x30: 'B',
        0x31: 'N', 0x32: 'M',
    }
    return names.get(scan_code, letters.get(scan_code, f'Scan 0x{scan_code:02X}'))


def binding_text(binding) -> str:
    """Return the user-facing label for a persisted binding."""
    normalized = normalize_binding(binding)
    if normalized is None:
        return 'Not assigned'
    modifiers = int(normalized['modifiers'])
    labels = [
        label for flag, label in ((MOD_WIN, 'Win'), (MOD_CTRL, 'Ctrl'), (MOD_ALT, 'Alt'), (MOD_SHIFT, 'Shift'))
        if modifiers & flag
    ]
    key_text = _fallback_key_name(int(normalized['scan_code']), bool(normalized['extended']))
    if sys.platform == 'win32':
        try:
            key_name = ctypes.create_unicode_buffer(64)
            lparam = int(normalized['scan_code']) << 16
            if normalized['extended']:
                lparam |= 1 << 24
            if ctypes.windll.user32.GetKeyNameTextW(lparam, key_name, len(key_name)):
                key_text = key_name.value
        except (AttributeError, OSError):
            pass
    return '+'.join([*labels, key_text])


class WindowsHotkeyService(QObject):
    """Poll global key state and dispatch a binding exactly once per key press."""

    activated = pyqtSignal(str)

    _MAPVK_VSC_TO_VK_EX = 3
    _POLL_SECONDS = 0.01

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def set_bindings(self, bindings: Mapping[str, Mapping[str, int]]) -> None:
        """Replace active bindings. Bare and modifier-only keys are supported."""
        self.stop()
        if sys.platform != 'win32':
            return
        clean = {
            str(name): normalized
            for name, spec in bindings.items()
            if (normalized := normalize_binding(spec)) is not None
        }
        if not clean:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(clean,), daemon=True, name='fleasion-fflag-hotkeys'
        )
        self._thread.start()

    def _run(self, bindings: Mapping[str, Mapping[str, int | bool]]) -> None:
        user32 = ctypes.windll.user32
        user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
        user32.MapVirtualKeyW.restype = wintypes.UINT
        translated: dict[str, tuple[int, int]] = {}
        try:
            for name, binding in bindings.items():
                scan_code = int(binding['scan_code'])
                if binding['extended']:
                    scan_code |= 0xE000
                virtual_key = int(user32.MapVirtualKeyW(scan_code, self._MAPVK_VSC_TO_VK_EX))
                if virtual_key:
                    translated[name] = (virtual_key, int(binding['modifiers']))
                else:
                    log_buffer.log('CustomFFlags', f'Could not map the keybind for {name}.')
        except Exception as exc:
            log_buffer.log('CustomFFlags', f'Could not start Windows FastFlag key polling: {exc}')
            return

        def is_pressed(virtual_key: int) -> bool:
            return bool(user32.GetAsyncKeyState(virtual_key) & 0x8000)

        def active_modifiers() -> int:
            result = 0
            if is_pressed(_VK_LSHIFT) or is_pressed(_VK_RSHIFT):
                result |= MOD_SHIFT
            if is_pressed(_VK_LCONTROL) or is_pressed(_VK_RCONTROL):
                result |= MOD_CTRL
            if is_pressed(_VK_LMENU) or is_pressed(_VK_RMENU):
                result |= MOD_ALT
            if is_pressed(_VK_LWIN) or is_pressed(_VK_RWIN):
                result |= MOD_WIN
            return result

        was_active = {name: False for name in translated}
        while not self._stop.wait(self._POLL_SECONDS):
            modifiers = active_modifiers()
            for name, (virtual_key, required_modifiers) in translated.items():
                main_modifier = modifier_mask_for_virtual_key(virtual_key)
                active = is_pressed(virtual_key) and (
                    modifiers & ~main_modifier
                ) == required_modifiers
                if active and not was_active[name]:
                    self.activated.emit(name)
                was_active[name] = active

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None
