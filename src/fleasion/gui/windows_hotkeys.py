"""Windows scan-code hotkeys for custom FastFlag toggles.

This follows the same physical-key model used by Spencer Macro Utilities: a
binding stores its scan code, whether it is extended, and the modifier state
required alongside it.  A low-level keyboard hook is necessary because
RegisterHotKey cannot reliably represent bare keys or modifier-only binds.
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


class _KeyboardData(ctypes.Structure):
    _fields_ = [
        ('vkCode', wintypes.DWORD),
        ('scanCode', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_size_t),
    ]


class WindowsHotkeyService(QObject):
    """Dispatch global Windows key-down edges matched by physical scan code."""

    activated = pyqtSignal(str)

    _WH_KEYBOARD_LL = 13
    _HC_ACTION = 0
    _WM_KEYDOWN = 0x0100
    _WM_KEYUP = 0x0101
    _WM_SYSKEYDOWN = 0x0104
    _WM_SYSKEYUP = 0x0105
    _WM_QUIT = 0x0012
    _LLKHF_EXTENDED = 0x01

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

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

    @staticmethod
    def _active_modifier_mask(pressed: Mapping[tuple[int, bool], int]) -> int:
        result = 0
        for virtual_key in pressed.values():
            result |= modifier_mask_for_virtual_key(virtual_key)
        return result

    def _run(self, bindings: Mapping[str, Mapping[str, int | bool]]) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
        pressed: dict[tuple[int, bool], int] = {}
        used_modifier_keys: set[tuple[int, bool]] = set()
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = (
            ctypes.c_int, callback_type, ctypes.c_void_p, wintypes.DWORD
        )
        user32.UnhookWindowsHookEx.argtypes = (ctypes.c_void_p,)

        @callback_type
        def keyboard_hook(code, message_type, lparam):
            if code == self._HC_ACTION:
                data = ctypes.cast(lparam, ctypes.POINTER(_KeyboardData)).contents
                extended = bool(data.flags & self._LLKHF_EXTENDED)
                identity = (int(data.scanCode), extended)
                if message_type in (self._WM_KEYDOWN, self._WM_SYSKEYDOWN):
                    if identity not in pressed:  # Ignore operating-system autorepeat.
                        # Modifier-only binds activate on release.  Mark any
                        # already-held modifier as used when another key joins
                        # it, so Ctrl alone does not also fire for Ctrl+F1.
                        used_modifier_keys.update(
                            pressed_identity
                            for pressed_identity, virtual_key in pressed.items()
                            if modifier_mask_for_virtual_key(virtual_key)
                        )
                        pressed[identity] = int(data.vkCode)
                        active_modifiers = self._active_modifier_mask(pressed)
                        main_modifier = modifier_mask_for_virtual_key(int(data.vkCode))
                        if not main_modifier:
                            for name, binding in bindings.items():
                                if (
                                    identity
                                    == (int(binding['scan_code']), bool(binding['extended']))
                                    and active_modifiers == int(binding['modifiers'])
                                ):
                                    self.activated.emit(name)
                                    break
                elif message_type in (self._WM_KEYUP, self._WM_SYSKEYUP):
                    virtual_key = pressed.get(identity, int(data.vkCode))
                    main_modifier = modifier_mask_for_virtual_key(virtual_key)
                    if main_modifier and identity not in used_modifier_keys:
                        active_modifiers = self._active_modifier_mask(pressed) & ~main_modifier
                        for name, binding in bindings.items():
                            if (
                                identity
                                == (int(binding['scan_code']), bool(binding['extended']))
                                and active_modifiers == int(binding['modifiers'])
                            ):
                                self.activated.emit(name)
                                break
                    pressed.pop(identity, None)
                    used_modifier_keys.discard(identity)
            return user32.CallNextHookEx(None, code, message_type, lparam)

        hook = None
        try:
            hook = user32.SetWindowsHookExW(
                self._WH_KEYBOARD_LL, keyboard_hook, kernel32.GetModuleHandleW(None), 0
            )
            if not hook:
                log_buffer.log('CustomFFlags', 'Could not install the Windows FastFlag keyboard hook.')
                return
            with self._lock:
                self._thread_id = kernel32.GetCurrentThreadId()
            if self._stop.is_set():
                return
            while not self._stop.is_set() and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if hook:
                user32.UnhookWindowsHookEx(hook)
            with self._lock:
                self._thread_id = None

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            thread_id = self._thread_id
        if thread_id and sys.platform == 'win32':
            ctypes.windll.user32.PostThreadMessageW(thread_id, self._WM_QUIT, 0, 0)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None
