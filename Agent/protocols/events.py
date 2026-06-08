"""Hook system — permission, logging, and lifecycle events.

Permission warnings (BLOCKED / WARN) are always visible to the user.
Hook events are logged to logs/agent.log and logs/trace.jsonl, not printed.
Set DEBUG_AGENT=1 to also print hook output to terminal.
"""

import re, os
from pathlib import Path

from ..infra.config import (
    WORKDIR, DEBUG, SAFE_COMMANDS, CONFIRM_COMMANDS, BLOCKED_PATTERNS,
)
from ..infra.storage import safe_path
from ..infra.logging import log_info, log_trace, log_error

HOOKS = {
    "UserPromptSubmit": [],
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": [],
}


def register_hook(event: str, callback):
    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None


# ── Path scanning ──

_PATH_RE = re.compile(r'(?:^|\s)([A-Za-z]:[/\\]\S+|/[^\s:;|&<>]+)')
_SYSTEM_PREFIXES = (
    "/etc/", "/usr/", "/boot/", "/sys/", "/proc/", "/dev/",
    "c:/windows", "c:/windows.old", "c:/program files", "c:/programdata",
)


def _extract_paths(text: str) -> list[str]:
    return [m.group(1).replace("\\", "/") for m in _PATH_RE.finditer(text)]


def _path_escapes_workspace(path: str) -> bool:
    path_lower = path.lower().replace("\\", "/")
    if path_lower.startswith(_SYSTEM_PREFIXES):
        return True
    try:
        if path[1:2] == ":":
            p = Path(path).resolve()
        else:
            p = (WORKDIR / path.lstrip("/")).resolve()
        p.relative_to(WORKDIR.resolve())
        return False
    except (ValueError, OSError):
        return True


# ── Permission hook (always active, warnings always visible) ──

def permission_hook(block) -> str | None:
    # ── bash ──
    if block.name == "bash":
        command = block.input.get("command", "")
        cmd_lower = command.lower()

        # 1. Blocked — always reject
        for pattern in BLOCKED_PATTERNS:
            if pattern.lower() in cmd_lower:
                print(f"  \033[31mBLOCKED: {pattern}\033[0m")
                return f"Permission denied: '{pattern}' is blocked"

        # 2. Paths outside workspace — warn + confirm
        for path in _extract_paths(command):
            if _path_escapes_workspace(path):
                print(f"  \033[33mWARN: path outside workspace: {path}\033[0m")
                try:
                    choice = input("  Allow? [y/N] ").strip().lower()
                except (EOFError, OSError):
                    choice = "n"
                if choice not in ("y", "yes"):
                    return f"Permission denied: path '{path}' outside workspace"

        # 3. Destructive commands — warn + confirm
        for cmd in CONFIRM_COMMANDS:
            if cmd_lower.startswith(cmd.lower()) or f" {cmd.lower()}" in cmd_lower:
                print(f"  \033[33mWARN: destructive command: {command[:100]}\033[0m")
                try:
                    choice = input("  Allow? [y/N] ").strip().lower()
                except (EOFError, OSError):
                    choice = "n"
                if choice not in ("y", "yes"):
                    return "Permission denied by user"
                break

        return None

    # ── read_file ──
    if block.name == "read_file":
        path = block.input.get("path", "")
        if _path_escapes_workspace(path):
            print(f"  \033[33mWARN: read outside workspace: {path}\033[0m")
            try:
                choice = input("  Allow? [y/N] ").strip().lower()
            except (EOFError, OSError):
                choice = "n"
            if choice not in ("y", "yes"):
                return f"Permission denied: path '{path}' outside workspace"
        return None

    # ── write_file / edit_file ──
    if block.name in ("write_file", "edit_file"):
        path = block.input.get("path", "")
        try:
            safe_path(path)
        except Exception:
            return f"Permission denied: path escapes workspace: {path}"
        if _path_escapes_workspace(path):
            return f"Permission denied: system path: {path}"
        return None

    # ── MCP deploy ──
    if block.name.startswith("mcp__") and "deploy" in block.name:
        print(f"  \033[33mWARN: MCP destructive tool: {block.name}\033[0m")
        try:
            choice = input("  Allow? [y/N] ").strip().lower()
        except (EOFError, OSError):
            choice = "n"
        if choice not in ("y", "yes"):
            return "Permission denied by user"

    return None


# ── Hooks: debug-only by default ──

def user_prompt_hook(query: str) -> None:
    log_info(f"UserPromptSubmit")
    log_trace("user_prompt", query=query[:200])


def log_hook(block) -> None:
    if block.name == "bash":
        log_info(f"PreToolUse bash: {block.input.get('command', '')[:80]}")
    elif block.name in ("read_file", "write_file", "edit_file"):
        log_info(f"PreToolUse {block.name}: {block.input.get('path', '')}")
    else:
        log_info(f"PreToolUse {block.name}")


def post_tool_log_hook(block, output) -> None:
    summary = str(output)[:80].replace("\n", " ")
    log_info(f"PostToolUse {block.name}: {summary}")


def large_output_hook(block, output) -> None:
    if len(str(output)) > 100000:
        log_info(f"LargeOutput {block.name}: {len(str(output))} chars")


def stop_hook(messages: list) -> None:
    tool_count = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            tool_count += sum(1 for item in content
                              if isinstance(item, dict)
                              and item.get("type") == "tool_result")
    log_info(f"Stop: {tool_count} tool(s)")


# Register built-in hooks at module load.
register_hook("UserPromptSubmit", user_prompt_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", post_tool_log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", stop_hook)
