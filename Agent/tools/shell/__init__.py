"""Shell command execution (bash tool) with cross-platform support."""

import os, re, subprocess
from pathlib import Path

from ...infra.config import WORKDIR, BASH_ENV

# ── Windows command translation ──
# Map Unix commands to their Windows equivalents when running on nt.

_WIN_TRANSLATIONS: dict[str, str] = {
    "ls": "dir",
    "rm": "del",
    "rmdir": "rd",
    "cat": "type",
    "cp": "copy",
    "mv": "move",
    "pwd": "cd",
    "clear": "cls",
    "touch": "type nul >",
    "grep": "findstr",
    "which": "where",
    "uname": "ver",
    "whoami": "whoami",
    "hostname": "hostname",
}

_WIN_CHCP_PREFIX = "chcp 65001 > nul && "


def _translate_command(command: str) -> str:
    """Translate Unix commands to Windows equivalents on nt platforms."""
    if os.name != "nt":
        return command

    # Detect multi-command (pipes, &&, ||, ;) — don't translate complex pipelines
    if any(sep in command for sep in ("|", "&&", "||", ";")):
        return command

    # Translate the first word only (the command itself)
    parts = command.strip().split(maxsplit=1)
    if not parts:
        return command

    cmd = parts[0].lower()
    if cmd in _WIN_TRANSLATIONS:
        rest = parts[1] if len(parts) > 1 else ""
        translated = f"{_WIN_TRANSLATIONS[cmd]} {rest}".strip()
        # Record translation in env for logging
        if "AGENT_TRANSLATED_COMMAND" not in os.environ:
            pass  # Set per-call via environment isn't thread-safe; use return tuple
        return f"{_WIN_CHCP_PREFIX}{translated}"

    # Unknown command — still set UTF-8 codepage
    return f"{_WIN_CHCP_PREFIX}{command}"


def run_bash(command: str, cwd: Path | None = None,
             run_in_background: bool = False) -> str:
    """Execute a shell command. On Windows, translates Unix commands and
    sets console codepage to UTF-8 before execution.
    *run_in_background* is consumed by the dispatcher; direct execution ignores it."""
    actual_command = _translate_command(command)
    try:
        r = subprocess.run(
            actual_command, shell=True, cwd=cwd or WORKDIR,
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace", env=BASH_ENV,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
