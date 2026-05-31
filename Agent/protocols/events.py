"""Hook system — extension points for permission, logging, and lifecycle events.

Hooks are intentionally outside tool handlers. The loop can add permission,
logging, and stop behavior without changing each individual tool.
"""

from ..infra.config import WORKDIR, DENY_LIST, DESTRUCTIVE
from ..infra.storage import safe_path

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


# ── Built-in hooks ──


def permission_hook(block) -> str | None:
    if block.name == "bash":
        command = block.input.get("command", "")
        command_lower = command.lower()
        for pattern in DENY_LIST:
            if pattern.lower() in command_lower:
                return f"Permission denied: '{pattern}' is on the deny list"
        for token in DESTRUCTIVE:
            if token.lower() in command_lower:
                print(f"\n\033[33m[permission] destructive command\033[0m")
                print(f"  {command}")
                choice = input("  Allow? [y/N] ").strip().lower()
                if choice not in ("y", "yes"):
                    return "Permission denied by user"
                break  # Only confirm once per command
    if block.name in ("write_file", "edit_file"):
        path = block.input.get("path", "")
        path_lower = path.lower().replace("\\", "/")
        # Check path escape via safe_path
        try:
            safe_path(path)
        except Exception:
            return f"Permission denied: path escapes workspace: {path}"
        # Extra guard: writing directly to system roots / Windows drives
        if path_lower.startswith(("/etc/", "/usr/", "/boot/", "/sys/", "/proc/")):
            return f"Permission denied: system path: {path}"
        if path_lower.startswith(("c:/windows", "c:/windows.old")):
            return f"Permission denied: system path: {path}"
    if block.name.startswith("mcp__") and "deploy" in block.name:
        print(f"\n\033[33m[permission] MCP destructive-looking tool: {block.name}\033[0m")
        choice = input("  Allow? [y/N] ").strip().lower()
        if choice not in ("y", "yes"):
            return "Permission denied by user"
    return None


def log_hook(block) -> None:
    print(f"\033[90m[HOOK] {block.name}\033[0m")


def post_tool_log_hook(block, output) -> None:
    summary = str(output)[:80].replace("\n", " ")
    print(f"\033[90m[HOOK] PostToolUse: {block.name} -> {summary}\033[0m")


def large_output_hook(block, output) -> None:
    if len(str(output)) > 100000:
        print(f"\033[33m[HOOK] large output from {block.name}: "
              f"{len(str(output))} chars\033[0m")


def user_prompt_hook(query: str) -> None:
    print(f"\033[90m[HOOK] UserPromptSubmit: {WORKDIR}\033[0m")


def stop_hook(messages: list) -> None:
    tool_count = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            tool_count += sum(1 for item in content
                              if isinstance(item, dict)
                              and item.get("type") == "tool_result")
    print(f"\033[90m[HOOK] Stop: {tool_count} tool result(s)\033[0m")


# Register built-in hooks at module load.
register_hook("UserPromptSubmit", user_prompt_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", post_tool_log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", stop_hook)
