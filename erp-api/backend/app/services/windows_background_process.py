"""Hide managed console children without touching externally owned browsers."""

import ctypes
import os
import subprocess


def has_hidden_console() -> bool:
    if os.name != "nt":
        return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel.GetConsoleWindow.restype = ctypes.c_void_p
    user.IsWindowVisible.argtypes = [ctypes.c_void_p]
    window = kernel.GetConsoleWindow()
    return bool(window) and not bool(user.IsWindowVisible(window))


def hidden_startup_info():
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return info


def background_process_options() -> dict:
    if os.name != "nt":
        return {}
    # Keep the hidden console attached: grandchildren can then inherit it too.
    # CREATE_NO_WINDOW alone leaves console-less SSH/Node parents whose own
    # descendants may allocate a new visible console.
    return {
        "startupinfo": hidden_startup_info(),
        "creationflags": 0 if has_hidden_console() else subprocess.CREATE_NO_WINDOW,
    }
