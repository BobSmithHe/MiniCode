"""Configuration, environment, and constants for the agent harness."""

import os, sys, threading
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

_api_key = os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")

WORKDIR = Path.cwd()

# Anthropic client — created once at module load.
from anthropic import Anthropic
client = Anthropic(
    base_url=os.getenv("ANTHROPIC_BASE_URL") or None,
    api_key=_api_key or None,
)

MODEL = os.environ["MODEL_ID"]
PRIMARY_MODEL = MODEL
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID")

# Directory paths.
SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"
TASKS_DIR = WORKDIR / ".tasks"
WORKTREES_DIR = WORKDIR / ".worktrees"
MAILBOX_DIR = WORKDIR / ".mailboxes"
MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
DURABLE_PATH = WORKDIR / ".scheduled_tasks.json"

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

# CLI.
CONTINUATION_PROMPT = "Continue from the previous response. Do not repeat completed work."
PROMPT = "\033[36m> \033[0m"
CLI_ACTIVE = False

# Permission deny / destructive lists (cross-platform).
# DENY_LIST: auto-reject, no user override. Destructive to system.
DENY_LIST = [
    # Linux / Unix
    "rm -rf /", "rm -rf / ", "mkfs", "dd if=", "dd if =",
    "> /dev/sd", "> /dev/hd", "> /dev/nvme", "> /dev/xvd",
    # Windows
    "format ", "diskpart", "reg delete",
    "del /f /s C:\\", "del /f /s D:\\",
    "rd /s /q C:\\", "rd /s /q D:\\",
    "\\\\.\\PhysicalDrive", "\\\\.\\C:",
    "Remove-Item -Recurse -Force C:\\",
    "Remove-Item -Recurse -Force D:\\",
    "Remove-Item -Path C:\\",
    # Cross-platform
    "sudo", "shutdown", "reboot",
]

# DESTRUCTIVE: warn + interactive confirm. Danger to workspace or local state.
DESTRUCTIVE = [
    # Linux / Unix
    "rm ", "> /etc/", "chmod 777", "chmod -R 777",
    # Windows
    "del ", "rd ", "rmdir ",
    "icacls ", "takeown",
    "> C:\\Windows", "> C:\\WINDOWS",
    "Remove-Item ",
    "Set-ExecutionPolicy",
    "runas ",
    # Cross-platform
    "shutdown /s", "shutdown /r",
]

# Round tracker for todo reminders.
rounds_since_todo = 0
agent_lock = threading.Lock()

# Teammate registry.
active_teammates: dict[str, bool] = {}
