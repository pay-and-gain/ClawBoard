"""Read the focused window thread's input locale without changing its IME state."""
from clawboard.windows_api import u32


def keyboard_layout(hwnd):
    """Return the target thread's HKL (low 32 bits), or zero when unknown.

    A hook/worker owns a different input context from the target application.
    Cross-thread ImmGetContext/ImmGetOpenStatus cannot establish that composing
    text is safe to erase, so callers only admit an explicitly supported HKL.
    """
    try:
        if not hwnd:
            return 0
        tid = u32.GetWindowThreadProcessId(int(hwnd), None)
        if not tid:
            return 0
        return int(u32.GetKeyboardLayout(tid) or 0) & 0xFFFFFFFF
    except Exception:
        return 0
