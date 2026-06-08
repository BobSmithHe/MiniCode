"""Thread-safe terminal + file logging.

Three layers:
  - User-facing: terminal_print() — clean output the user sees
  - Debug log:    logs/agent.log    — human-readable event log
  - Trace log:    logs/trace.jsonl  — structured JSON events for analysis
"""

import json, threading, time
from pathlib import Path
from datetime import datetime

from ..config import PROMPT, CLI_ACTIVE, AGENT_HOME, DEBUG

try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

LOGS_DIR = AGENT_HOME / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

_agent_log = LOGS_DIR / "agent.log"
_trace_log = LOGS_DIR / "trace.jsonl"
_error_log = LOGS_DIR / "error.log"

_log_lock = threading.Lock()


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── User-facing ──

def _safe_print(text: str):
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"), flush=True)


def terminal_print(text: str):
    """Thread-safe print for user-visible output."""
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


# ── Debug log (agent.log) ──

def log_info(msg: str):
    """Append a line to agent.log."""
    line = f"{_timestamp()} {msg}\n"
    with _log_lock:
        with open(_agent_log, "a", encoding="utf-8") as f:
            f.write(line)
    if DEBUG:
        _safe_print(f"  \033[90m{msg}\033[0m")


def log_error(msg: str):
    """Log an error to both error.log and agent.log. Always shown to user."""
    line = f"{_timestamp()} ERROR {msg}\n"
    with _log_lock:
        with open(_error_log, "a", encoding="utf-8") as f:
            f.write(line)
        with open(_agent_log, "a", encoding="utf-8") as f:
            f.write(line)
    _safe_print(f"  \033[31m{msg}\033[0m")


# ── Trace log (trace.jsonl) ──

def log_trace(event: str, **data):
    """Append a structured JSON event to trace.jsonl."""
    record = {"ts": time.time(), "event": event, **data}
    with _log_lock:
        with open(_trace_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")


def tool_start(name: str, input_data: dict):
    log_info(f"Tool={name}")
    log_trace("tool_start", tool=name, input=input_data)


def tool_end(name: str, output: str, latency_ms: float):
    summary = output[:100].replace("\n", " ")
    log_trace("tool_end", tool=name, latency_ms=round(latency_ms, 1), output=summary)


def turn_start():
    log_trace("turn_start")


def turn_end(tool_count: int):
    log_info(f"Stop ({tool_count} tools)")
    log_trace("turn_end", tool_count=tool_count)
