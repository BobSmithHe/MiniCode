"""Thread-safe terminal logging."""

import threading

from ..config import PROMPT, CLI_ACTIVE

try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False


def _safe_print(text: str):
    """Print, falling back to ASCII on Windows console encoding errors."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"), flush=True)


def terminal_print(text: str):
    """Thread-safe print.  Restores the REPL prompt after background output."""
    if threading.current_thread() is threading.main_thread() or not CLI_ACTIVE:
        _safe_print(text)
        return
    line = ""
    if READLINE_AVAILABLE:
        try:
            line = readline.get_line_buffer()
        except Exception:
            line = ""
    _safe_print(f"\r\033[K{text}")
    try:
        print(PROMPT + line, end="", flush=True)
    except UnicodeEncodeError:
        pass
