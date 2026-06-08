"""Configuration, environment, and constants for the agent harness."""

import os, sys, threading
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

_api_key = os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")

# AGENT_HOME: MiniCode's own state directory (memory, skills, tasks, etc.)
# Defaults to the directory where run.py lives (Path.cwd() at import time).
AGENT_HOME = Path.cwd().resolve()

# WORKDIR: the agent's workspace sandbox. Set via .env to operate on another directory.
WORKDIR = Path(os.getenv("AGENT_WORKDIR", AGENT_HOME)).resolve()

# Anthropic client — created once at module load.
from anthropic import Anthropic
client = Anthropic(
    base_url=os.getenv("ANTHROPIC_BASE_URL") or None,
    api_key=_api_key or None,
)

MODEL = os.environ["MODEL_ID"]
PRIMARY_MODEL = MODEL
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID")

# Directory paths — all MiniCode data lives under AGENT_HOME.
SKILLS_DIR = AGENT_HOME / "skills"
TRANSCRIPT_DIR = AGENT_HOME / ".transcripts"
TOOL_RESULTS_DIR = AGENT_HOME / ".task_outputs" / "tool-results"
WORKTREES_DIR = WORKDIR / ".worktrees"   # worktrees belong to the workspace repo
MEMORY_DIR = AGENT_HOME / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
DB_PATH = AGENT_HOME / "agent.db"        # SQLite database for tasks/cron/messages

# Subprocess environment (UTF-8 + Python on PATH for Windows).
_PYTHON_DIR = str(Path(sys.executable).parent)
BASH_ENV: dict = {
    **os.environ,
    "PATH": _PYTHON_DIR + os.pathsep + os.environ.get("PATH", ""),
    "PYTHONIOENCODING": "utf-8",
}

# Token / retry / context budget.
DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 16000
MAX_RETRIES = 3
MAX_CONSECUTIVE_529 = 2
MAX_RECOVERY_RETRIES = 2
BASE_DELAY_MS = 500
CONTEXT_LIMIT = 50000
KEEP_RECENT_TOOL_RESULTS = 3
PERSIST_THRESHOLD = 30000

# CLI / debug.
DEBUG = os.getenv("DEBUG_AGENT") == "1"
CONTINUATION_PROMPT = "Continue from the previous response. Do not repeat completed work."
PROMPT = "\033[36m> \033[0m"
CLI_ACTIVE = False

# Permission model — tiered command safety (replaces simple deny lists).
#
# SAFE:       auto-allow, no confirmation (read-only / dev tools)
# CONFIRM:    warn + interactive confirm (destructive but workspace-scoped)
# BLOCKED:    always reject (system-level destruction)
#
# Unknown commands fall through to path-scanning: any absolute path
# outside WORKDIR triggers confirmation.

SAFE_COMMANDS = [
    "echo", "cat", "type", "head", "tail", "more",
    "ls", "dir", "tree", "find", "grep", "rg", "wc",
    "pwd", "cd", "which", "where", "whoami", "hostname",
    "git", "python", "python3", "pip", "node", "npm", "npx",
    "cargo", "go", "rustc", "javac", "java",
    "mkdir", "cp", "copy", "mv", "move", "ren", "rename",
]

CONFIRM_COMMANDS = [
    "rm", "del", "rd", "rmdir", "Remove-Item",
    "chmod", "icacls", "takeown", "cacls",
    "chown", "kill", "taskkill",
    "shutdown",
]

BLOCKED_PATTERNS = [
    # raw disk / device access
    "/dev/sd", "/dev/hd", "/dev/nvme", "/dev/xvd",
    "\\\\.\\PhysicalDrive", "\\\\.\\C:",
    # filesystem formatting
    "mkfs", "format", "diskpart",
    # registry / system config destruction
    "reg delete", "reg add",
    "dd if=", "dd if =",
    # privilege escalation
    "sudo", "runas", "Set-ExecutionPolicy",
    # redirect to system paths
    "> /etc/", "> /usr/", "> /boot/",
    "> C:\\Windows", "> C:\\WINDOWS",
]

# Round tracker for todo reminders.
rounds_since_todo = 0
agent_lock = threading.Lock()

# Teammate registry.
active_teammates: dict[str, bool] = {}
