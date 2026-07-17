"""Small Windows global-hotkey bridge for custom FastFlag toggles."""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Mapping
from ctypes import wintypes

from PyQt6.QtCore import QObject, pyqtSignal

from ..utils import log_buffer


class WindowsHotkeyService(QObject):
    """Register Qt key/modifier pairs as process-independent Windows hotkeys."""

    activated = pyqtSignal(str)

    _WM_HOTKEY = 0x0312
    _WM_QUIT = 0x0012
    _MOD_ALT = 0x0001
    _MOD_CONTROL = 0x0002
    _MOD_SHIFT = 0x0004
    _MOD_WIN = 0x0008
    _MOD_NOREPEAT = 0x4000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    @staticmethod
    def _windows_modifiers(qt_modifiers: int) -> int:
        result = 0
        if qt_modifiers & 0x04000000:  # Ctrl
            result |= WindowsHotkeyService._MOD_CONTROL
        if qt_modifiers & 0x08000000:  # Alt
            result |= WindowsHotkeyService._MOD_ALT
        if qt_modifiers & 0x02000000:  # Shift
            result |= WindowsHotkeyService._MOD_SHIFT
        if qt_modifiers & 0x10000000:  # Meta / Windows
            result |= WindowsHotkeyService._MOD_WIN
        return result

    @staticmethod
    def _virtual_key(qt_key: int) -> int | None:
        # Qt shares ASCII key values with Windows for letters, digits, and space.
        if 0x30 <= qt_key <= 0x5A or qt_key == 0x20:
            return qt_key
        special = {
            0x01000000: 0x1B,  # Escape
            0x01000001: 0x09,  # Tab
            0x01000003: 0x08,  # Backspace
            0x01000004: 0x0D,  # Return
            0x01000005: 0x0D,  # Enter
            0x01000006: 0x2D,  # Insert
            0x01000007: 0x7F,  # Delete
            0x01000010: 0x24,  # Home
            0x01000011: 0x23,  # End
            0x01000016: 0x21,  # PageUp
            0x01000017: 0x22,  # PageDown
            0x01000012: 0x25,  # Left
            0x01000013: 0x26,  # Up
            0x01000014: 0x27,  # Right
            0x01000015: 0x28,  # Down
        }
        if 0x01000030 <= qt_key <= 0x01000047:  # F1-F24
            return 0x70 + qt_key - 0x01000030
        return special.get(qt_key)

    def set_bindings(self, bindings: Mapping[str, Mapping[str, int]]) -> None:
        """Replace every registered hotkey. Invalid/conflicting bindings are skipped."""
        self.stop()
        if sys.platform != 'win32' or not bindings:
            return
        clean = {
            str(name): {'key': int(spec['key']), 'modifiers': int(spec['modifiers'])}
            for name, spec in bindings.items()
            if self._virtual_key(int(spec.get('key', 0))) is not None
            and self._windows_modifiers(int(spec.get('modifiers', 0)))
        }
        if not clean:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(clean,), daemon=True, name='fleasion-fflag-hotkeys'
        )
        self._thread.start()

    def _run(self, bindings: Mapping[str, Mapping[str, int]]) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        # Force creation of the thread message queue before callers can post WM_QUIT.
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
        registered: dict[int, str] = {}
        try:
            with self._lock:
                self._thread_id = kernel32.GetCurrentThreadId()
            if self._stop.is_set():
                return
            for hotkey_id, (name, spec) in enumerate(bindings.items(), start=1):
                if user32.RegisterHotKey(
                    None,
                    hotkey_id,
                    self._windows_modifiers(spec['modifiers']) | self._MOD_NOREPEAT,
                    self._virtual_key(spec['key']),
                ):
                    registered[hotkey_id] = name
                else:
                    log_buffer.log(
                        'CustomFFlags', f'Could not register Windows hotkey for {name}; it is in use.'
                    )
            while not self._stop.is_set() and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == self._WM_HOTKEY and message.wParam in registered:
                    self.activated.emit(registered[message.wParam])
        finally:
            for hotkey_id in registered:
                user32.UnregisterHotKey(None, hotkey_id)
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

    def close(self) -> None:
        self.stop()
