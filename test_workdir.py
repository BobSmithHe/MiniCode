#!/usr/bin/env python3
"""Test AGENT_HOME / WORKDIR directory separation logic."""

import os, sys, tempfile, shutil, subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
sandbox = tempfile.mkdtemp(prefix="agent_test_")

# Backup .env, write one without AGENT_WORKDIR
env_path = _PROJECT_ROOT / ".env"
env_backup = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
env_test = "\n".join(
    line for line in env_backup.splitlines()
    if not line.strip().startswith("AGENT_WORKDIR")
)
env_path.write_text(env_test, encoding="utf-8")

code = f'''
import os, sys
sys.path.insert(0, {str(_PROJECT_ROOT)!r})
os.environ["AGENT_WORKDIR"] = {sandbox!r}

for m in list(sys.modules):
    if m.startswith("Agent"):
        del sys.modules[m]

from Agent.infra.config import AGENT_HOME, WORKDIR, MEMORY_DIR, SKILLS_DIR, WORKTREES_DIR, TRANSCRIPT_DIR

def ok(msg):
    print("  " + msg)

home = os.path.abspath(str(AGENT_HOME)).lower()
work = os.path.abspath(str(WORKDIR)).lower()
expected = os.path.abspath({sandbox!r}).lower()

if home == {str(_PROJECT_ROOT.resolve()).lower()!r}:
    ok("PASS: AGENT_HOME == project root")
else:
    ok("FAIL: AGENT_HOME mismatch: " + str(AGENT_HOME))

if work == expected:
    ok("PASS: WORKDIR == sandbox")
else:
    ok("FAIL: WORKDIR mismatch: " + str(WORKDIR) + " != " + {sandbox!r})

if home != work:
    ok("PASS: AGENT_HOME != WORKDIR (separated)")
else:
    ok("FAIL: AGENT_HOME == WORKDIR (not separated)")

for name, path in [("MEMORY", MEMORY_DIR), ("SKILLS", SKILLS_DIR), ("TRANSCRIPTS", TRANSCRIPT_DIR)]:
    try:
        path.relative_to(AGENT_HOME)
        ok("PASS: " + name + " under AGENT_HOME")
    except ValueError:
        ok("FAIL: " + name + " NOT under AGENT_HOME")

try:
    WORKTREES_DIR.relative_to(WORKDIR)
    ok("PASS: worktrees under WORKDIR")
except ValueError:
    ok("FAIL: worktrees NOT under WORKDIR")

sys.exit(0)
'''

result = subprocess.run(
    [sys.executable, "-c", code],
    capture_output=True, text=True, timeout=30,
    encoding="utf-8", errors="replace",
)

print(result.stdout)
if result.stderr:
    print(result.stderr, file=sys.stderr)

# Restore .env
env_path.write_text(env_backup, encoding="utf-8")
shutil.rmtree(sandbox, ignore_errors=True)
sys.exit(result.returncode)
