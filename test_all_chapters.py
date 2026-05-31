#!/usr/bin/env python3
"""Comprehensive test for all 20 chapters (s01-s20) of the agent framework.

Run: python test_all_chapters.py
"""

import json, sys, os, time, threading
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT))

# Create support dirs
for d in [".memory", ".tasks", ".transcripts", ".task_outputs/tool-results",
          ".worktrees", ".mailboxes", ".scheduled_tasks.json"]:
    p = _PROJECT_ROOT / d
    if p.suffix: p.parent.mkdir(parents=True, exist_ok=True)
    else: p.mkdir(parents=True, exist_ok=True)

PASS = FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  \033[32m[PASS]\033[0m {name}")
    else: FAIL += 1; print(f"  \033[31m[FAIL]\033[0m {name}  {detail}")

def section(title):
    print(f"\n{'='*60}\n{title}\n{'='*60}")

def cleanup(pattern):
    for d in [".memory", ".tasks", ".transcripts",
              ".task_outputs/tool-results", ".worktrees", ".mailboxes"]:
        for f in (_PROJECT_ROOT / d).glob(pattern):
            if f.name == "MEMORY.md": continue
            try: f.unlink()
            except: pass


# ══════════════════════════════════════════════════════════════════
section("s01 — Agent Loop: messages[] / while True / stop_reason")

from Agent.infra.config import MODEL, WORKDIR
check("MODEL loaded from env", MODEL and len(MODEL) > 0)
check("WORKDIR is a Path", isinstance(WORKDIR, Path))

# Verify agent_loop function exists and has correct signature
from Agent.planner.workflow import agent_loop
import inspect
sig = inspect.signature(agent_loop)
check("agent_loop accepts messages + context", "messages" in sig.parameters and "context" in sig.parameters)

# ══════════════════════════════════════════════════════════════════
section("s02 — Tool Use: TOOL_HANDLERS / dispatch / call_tool_handler")

from Agent.tools.registry import assemble_tool_pool, call_tool_handler, BUILTIN_TOOLS

tools, handlers = assemble_tool_pool()
check("Tool pool assembled with > 20 tools", len(tools) > 20, f"{len(tools)} tools")

required = ["bash", "read_file", "write_file", "edit_file", "glob", "task",
            "todo_write", "load_skill", "create_task"]
for name in required:
    check(f"  Tool '{name}' registered", name in handlers, f"handler={'OK' if name in handlers else 'MISSING'}")

# 'compact' is a schema-only tool handled inline in workflow.py
compact_def = [t for t in tools if t["name"] == "compact"]
check("  Tool 'compact' has schema (handled inline in workflow)", len(compact_def) == 1)

# Test handler dispatch
r = call_tool_handler(handlers["glob"], {"pattern": "*.py"}, "glob")
check("glob handler works", "(no matches)" in r or ".py" in r or "Error" not in r)

check("call_tool_handler returns unknown for missing handler",
      "Unknown:" in call_tool_handler(None, {}, "nonexistent"))

check("call_tool_handler handles TypeError for wrong args",
      "Error:" in call_tool_handler(handlers["bash"], {}, "bash"))

# ══════════════════════════════════════════════════════════════════
section("s03 — Permission: DENY_LIST / DESTRUCTIVE / permission_hook")

from Agent.infra.config import DENY_LIST, DESTRUCTIVE
check("DENY_LIST has 'rm -rf /'", any("rm" in d for d in DENY_LIST))
check("DENY_LIST has 'sudo'", any("sudo" in d for d in DENY_LIST))
check("DENY_LIST has 'shutdown'", any("shutdown" in d for d in DENY_LIST))
check("DESTRUCTIVE list not empty", len(DESTRUCTIVE) > 0)

from Agent.protocols.events import permission_hook
from types import SimpleNamespace

block = SimpleNamespace(name="bash", input={"command": "rm -rf /"})
result = permission_hook(block)
check("permission_hook blocks rm -rf /", result is not None and "Permission denied" in result)

block_ok = SimpleNamespace(name="bash", input={"command": "echo hello"})
check("permission_hook allows safe bash", permission_hook(block_ok) is None)

# Path escape test
block_escape = SimpleNamespace(name="write_file", input={"path": "/etc/passwd"})
check("permission_hook blocks path escape",
      permission_hook(block_escape) is not None)

block_safe = SimpleNamespace(name="write_file", input={"path": "test.txt"})
check("permission_hook allows safe path", permission_hook(block_safe) is None)

# ══════════════════════════════════════════════════════════════════
section("s04 — Hooks: PreToolUse / PostToolUse / Stop / UserPromptSubmit")

from Agent.protocols.events import HOOKS, trigger_hooks, register_hook

check("PreToolUse hook registered", len(HOOKS["PreToolUse"]) > 0)
check("PostToolUse hook registered", len(HOOKS["PostToolUse"]) > 0)
check("Stop hook registered", len(HOOKS["Stop"]) > 0)
check("UserPromptSubmit hook registered", len(HOOKS["UserPromptSubmit"]) > 0)

# Test custom hook
called_with = []

def custom_hook(*args):
    called_with.append(args)

register_hook("Stop", custom_hook)
trigger_hooks("Stop", [{"role": "user", "content": "test"}])
check("Custom Stop hook fired", len(called_with) == 1)
HOOKS["Stop"].remove(custom_hook)

# ══════════════════════════════════════════════════════════════════
section("s05 — TodoWrite: CURRENT_TODOS / todo_write tool")

from Agent.tools.task import run_todo_write, CURRENT_TODOS

r = run_todo_write([
    {"content": "Fix bug in login", "status": "pending"},
    {"content": "Write tests", "status": "in_progress"},
])
check("todo_write accepts valid list", "Updated 2 todos" in r)

r = run_todo_write([{"content": "bad", "status": "invalid"}])
check("todo_write rejects invalid status", "invalid status" in r.lower())

r = run_todo_write([{"status": "pending"}])
check("todo_write rejects missing content", "missing" in r.lower())

# ══════════════════════════════════════════════════════════════════
section("s06 — Subagent: spawn_subagent / fresh messages / isolation")

from Agent.executor.subagent import spawn_subagent, SUB_SYSTEM, SUB_TOOLS, SUB_HANDLERS

check("SUB_SYSTEM has isolation instruction",
      "Complete the task" in SUB_SYSTEM and "Do not spawn more agents" in SUB_SYSTEM)
check("Subagent has 5 tools (bash, read, write, edit, glob)",
      len(SUB_TOOLS) == 5, f"{len(SUB_TOOLS)}")
check("Subagent handlers match tools", len(SUB_HANDLERS) == len(SUB_TOOLS))

# ══════════════════════════════════════════════════════════════════
section("s07 — Skill Loading: SKILL_REGISTRY / load_skill")

from Agent.memory.short_term import SKILL_REGISTRY, load_skill, list_skills, scan_skills

scan_skills()
skills_list = list_skills()
check("Skills catalog has entries", len(SKILL_REGISTRY) > 0, f"{len(SKILL_REGISTRY)} skills")
check("Skills listed", "agent-builder" in skills_list or "code-review" in skills_list)

for name, skill in SKILL_REGISTRY.items():
    content = load_skill(name)
    check(f"load_skill('{name}') returns content", len(content) > 100, f"{len(content)} chars")

check("load_skill unknown returns error", "Skill not found" in load_skill("nonexistent_skill"))

# ══════════════════════════════════════════════════════════════════
section("s08 — Context Compact: 4-layer compression pipeline")

from Agent.memory.compactor import (
    estimate_size, tool_result_budget, snip_compact, micro_compact,
    compact_history, reactive_compact, prepare_context,
    collect_tool_results, persist_large_output, write_transcript,
    TOOL_RESULTS_DIR,
)
from Agent.infra.config import CONTEXT_LIMIT, PERSIST_THRESHOLD, KEEP_RECENT_TOOL_RESULTS

# Layer 1: tool_result_budget
for f in TOOL_RESULTS_DIR.glob("*.txt"): f.unlink()
msgs = [{"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "t1", "content": "A" * 80000},
    {"type": "tool_result", "tool_use_id": "t2", "content": "B" * 80000},
    {"type": "tool_result", "tool_use_id": "t3", "content": "C" * 80000},
]}]
result = tool_result_budget(msgs, 200_000)
files = list(TOOL_RESULTS_DIR.glob("*.txt"))
check("s08 L1: tool_result_budget persists large outputs", len(files) >= 1, f"{len(files)} files")
check("s08 L1: persisted-output marker present",
      any("<persisted-output>" in str(b.get("content","")) for b in result[0]["content"]))
for f in files: f.unlink()

# Layer 2: snip_compact
large = [{"role": "user", "content": f"msg {i}"} for i in range(80)]
snipped = snip_compact(large, 50)
check(f"s08 L2: snip_compact trims to <= 50", len(snipped) <= 50, f"{len(snipped)}")
check("s08 L2: snipped marker present", any("snipped" in str(m["content"]) for m in snipped))
check("s08 L2: head preserved", snipped[0]["content"] == "msg 0")
check("s08 L2: tail preserved", "msg 79" in snipped[-1]["content"])

# Layer 3: micro_compact
def make_history(n, size=200):
    msgs = []
    for i in range(n):
        msgs.append({"role": "user", "content": f"Q{i}"})
        blocks = [{"type": "text", "text": f"A{i}"*size}]
        if i < n-1:
            blocks.append({"type": "tool_use", "id": f"t{i}", "name": "bash", "input": {}})
        msgs.append({"role": "assistant", "content": blocks})
        if i < n-1:
            msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": f"r{i}_"*size}]})
    return msgs

h = make_history(10, 50)
compacted = micro_compact(h)
tr = collect_tool_results(compacted)
old_truncated = any("[Earlier tool result compacted" in str(b.get("content","")) for _,_,b in tr[:-KEEP_RECENT_TOOL_RESULTS])
recent_intact = all("[Earlier tool result compacted" not in str(b.get("content","")) for _,_,b in tr[-KEEP_RECENT_TOOL_RESULTS:])
check("s08 L3: old tool results truncated", old_truncated)
check("s08 L3: recent tool results intact", recent_intact)

# Layer 4: compact_history (write_transcript tested; summarize calls LLM)
h = make_history(8)
transcript = write_transcript(h)
check("s08 L4: transcript saved to JSONL", transcript.exists())
lines = transcript.read_text(encoding="utf-8").splitlines()
check("s08 L4: transcript has content", len(lines) > 0, f"{len(lines)} lines")
for i, line in enumerate(lines[:3]):
    try: json.loads(line)
    except: check(f"s08 L4: transcript line {i} valid JSON", False, line[:60])
    else: check(f"s08 L4: transcript line {i} valid JSON", True)
transcript.unlink()

# persist_large_output edge cases
check("persist_large_output keeps small under threshold", persist_large_output("x", "small") == "small")
big = persist_large_output("big", "X" * (PERSIST_THRESHOLD + 100))
check("persist_large_output persists large output", "<persisted-output>" in big and "Preview" in big)
for f in TOOL_RESULTS_DIR.glob("*.txt"): f.unlink()

# prepare_context full pipeline
s = make_history(3)
sc = list(s)
prepare_context(sc)
check("prepare_context: small history unchanged", len(sc) == len(s))

# estimate_size
check("estimate_size: empty < 1000", estimate_size([]) < 1000)
check("estimate_size: grows with content", estimate_size(make_history(10)) > estimate_size(make_history(2)))

# ══════════════════════════════════════════════════════════════════
section("s09 — Memory: write / read / list / extract / consolidate")

from Agent.memory.writer import (
    write_memory_file, read_memory_index, read_memory_file,
    list_memory_files, load_memories, extract_memories, consolidate_memories,
    build_memory_system_prompt, _rebuild_index,
)
from Agent.infra.config import MEMORY_DIR, MEMORY_INDEX

# Clean slate
for f in MEMORY_DIR.glob("*.md"): f.unlink()

# write
p = write_memory_file("user-pref", "user", "prefers tabs", "Use tabs for indentation.")
check("s09: write_memory_file creates file", p.exists())
check("s09: frontmatter has name", "name: user-pref" in p.read_text(encoding="utf-8"))

# index rebuild
idx = read_memory_index()
check("s09: index rebuilt after write", "user-pref" in idx)

# list
files = list_memory_files()
check("s09: list_memory_files returns 1 entry", len(files) == 1, f"{len(files)}")
check("s09: memory type preserved", files[0]["type"] == "user")
check("s09: memory body preserved", "Use tabs" in files[0]["body"])

# read
content = read_memory_file("user-pref.md")
check("s09: read_memory_file works", content is not None and "tabs" in content)
check("s09: read_memory_file missing returns None", read_memory_file("nonexistent.md") is None)

# build_memory_system_prompt
prompt = build_memory_system_prompt()
check("s09: build_memory_system_prompt includes index", "user-pref" in prompt)

# load_memories with keyword fallback (no LLM needed for fallback path)
msgs = [{"role": "user", "content": "I prefer using tabs for indentation in my code"}]
relevant = load_memories(msgs)
check("s09: load_memories selects relevant by keyword", len(relevant) > 0, f"len={len(relevant)}")

# load_memories with no match
msgs2 = [{"role": "user", "content": "hello world"}]
# This may or may not select by keyword; it should not crash
try:
    load_memories(msgs2)
    check("s09: load_memories gracefully handles no match", True)
except Exception as e:
    check("s09: load_memories gracefully handles no match", False, str(e))

# Cleanup memory files
for f in MEMORY_DIR.glob("*.md"): f.unlink()

# ══════════════════════════════════════════════════════════════════
section("s10 — System Prompt: runtime assembly / sections")

from Agent.memory.short_term import assemble_system_prompt, PROMPT_SECTIONS

check("s10: PROMPT_SECTIONS has identity", "identity" in PROMPT_SECTIONS)
check("s10: PROMPT_SECTIONS has tools", "tools" in PROMPT_SECTIONS)
check("s10: PROMPT_SECTIONS has workspace", "workspace" in PROMPT_SECTIONS)
check("s10: PROMPT_SECTIONS has memory", "memory" in PROMPT_SECTIONS)

ctx = {"memories": "", "connected_mcp": [], "active_teammates": []}
prompt = assemble_system_prompt(ctx)
check("s10: identity in prompt", "coding agent" in prompt.lower() or "Act, don't explain" in prompt)
check("s10: tools listed", "bash" in prompt)
check("s10: workspace in prompt", str(WORKDIR) in prompt)
check("s10: current time in prompt", "Current time" in prompt)
check("s10: skills catalog in prompt", "Skills catalog" in prompt)

# Test with populated context
ctx2 = {"memories": "- [test](test.md)", "connected_mcp": [], "active_teammates": ["bob"]}
prompt2 = assemble_system_prompt(ctx2)
check("s10: memories injected", "- [test](test.md)" in prompt2)

# MCP servers appear in prompt only when actually connected (checked via mcp_clients global)
from Agent.infra.mcp import connect_mcp, mcp_clients
connect_mcp("docs")
prompt3 = assemble_system_prompt(ctx2)
check("s10: MCP servers listed when connected", "docs" in prompt3)
mcp_clients.clear()

# ══════════════════════════════════════════════════════════════════
section("s11 — Error Recovery: RecoveryState / retry / escalation / fallback")

from Agent.infra.llm import RecoveryState, with_retry, is_prompt_too_long_error
from Agent.infra.config import MAX_RETRIES, DEFAULT_MAX_TOKENS, ESCALATED_MAX_TOKENS

state = RecoveryState()
check("s11: RecoveryState starts fresh", not state.has_escalated)
check("s11: RecoveryState recovery_count=0", state.recovery_count == 0)
check("s11: RecoveryState consecutive_529=0", state.consecutive_529 == 0)
check("s11: RecoveryState current_model = PRIMARY_MODEL", state.current_model == MODEL)

check("s11: DEFAULT_MAX_TOKENS < ESCALATED_MAX_TOKENS", DEFAULT_MAX_TOKENS < ESCALATED_MAX_TOKENS)
check("s11: MAX_RETRIES >= 2", MAX_RETRIES >= 2)

# is_prompt_too_long_error
class FakeError(Exception): pass
check("s11: detects 'prompt too long'",
      is_prompt_too_long_error(Exception("prompt too long error")))
check("s11: detects 'context_length_exceeded'",
      is_prompt_too_long_error(Exception("context_length_exceeded")))
check("s11: ignores unrelated errors",
      not is_prompt_too_long_error(Exception("something else")))

# with_retry with a failing function
call_count = [0]
def fail_twice():
    call_count[0] += 1
    if call_count[0] < 3:
        raise Exception("429 rate limit exceeded")
    return "success"

state2 = RecoveryState()
result = with_retry(fail_twice, state2)
check("s11: with_retry succeeds after 429 retries", result == "success" and call_count[0] == 3)

# ══════════════════════════════════════════════════════════════════
section("s12 — Task System: Task record / blockedBy / persistence")

from Agent.tools.task import (
    Task, create_task, save_task, load_task, list_tasks,
    can_start, claim_task, complete_task, get_task_json,
)
from Agent.infra.config import TASKS_DIR

# Clean
for f in TASKS_DIR.glob("task_*.json"): f.unlink()

t1 = create_task("Design database", "Create ERD")
check("s12: create_task returns Task", isinstance(t1, Task))
check("s12: task status is pending", t1.status == "pending")
check("s12: task saved to disk", (TASKS_DIR / f"{t1.id}.json").exists())

# blockedBy
t2 = create_task("Implement API", "Based on design", blockedBy=[t1.id])
check("s12: blockedBy stored", t1.id in t2.blockedBy)
check("s12: can_start false when blocked", not can_start(t2.id))

# claim_task
r = claim_task(t1.id)
check("s12: claim_task succeeds for pending", "Claimed" in r)
check("s12: task now in_progress", load_task(t1.id).status == "in_progress")

# complete_task
r = complete_task(t1.id)
check("s12: complete_task succeeds", "Completed" in r)
check("s12: task now completed", load_task(t1.id).status == "completed")

# t2 unblocked
check("s12: can_start true after deps complete", can_start(t2.id))

# claim rejections
r = claim_task(t1.id)
check("s12: claim_task rejects completed task", "cannot claim" in r.lower())

# list_tasks
tasks = list_tasks()
check("s12: list_tasks returns all tasks", len(tasks) == 2, f"{len(tasks)}")

# get_task_json
json_str = get_task_json(t1.id)
check("s12: get_task_json returns valid JSON", "Design database" in json_str)

# Complete t2
claim_task(t2.id)
complete_task(t2.id)

for f in TASKS_DIR.glob("task_*.json"): f.unlink()

# ══════════════════════════════════════════════════════════════════
section("s13 — Background Tasks: thread execution / notification queue")

from Agent.executor.executor import (
    is_slow_operation, should_run_background, start_background_task,
    collect_background_results, background_tasks, background_results,
    background_lock,
)

check("s13: pip install is slow", is_slow_operation("bash", {"command": "pip install numpy"}))
check("s13: npm install is slow", is_slow_operation("bash", {"command": "npm install react"}))
check("s13: echo is not slow", not is_slow_operation("bash", {"command": "echo hello"}))

check("s13: run_in_background triggers background",
      should_run_background("bash", {"command": "echo x", "run_in_background": True}))
check("s13: normal command does not trigger bg",
      not should_run_background("bash", {"command": "echo x"}))

# Start a background task and verify it completes
block = SimpleNamespace(id="bgtest", name="bash", input={"command": "echo bg_test_result"})
bg_id = start_background_task(block, {"bash": lambda command, **kw: f"bg_out: {command}"})
check("s13: background task id returned", bg_id.startswith("bg_"))
time.sleep(0.5)  # Give thread time to finish

# collect
notes = collect_background_results()
check("s13: background result collected", len(notes) > 0, f"{len(notes)} notes")
check("s13: notification has task_id", all("task_id" in n for n in notes))

with background_lock:
    background_tasks.clear()
    background_results.clear()

# ══════════════════════════════════════════════════════════════════
section("s14 — Cron Scheduler: cron_matches / durable / lifecycle")

from Agent.infra.scheduler import (
    CronJob, cron_matches, validate_cron, schedule_job, cancel_job,
    scheduled_jobs, cron_lock, load_durable_jobs, save_durable_jobs,
    cron_scheduler_loop,
)
from datetime import datetime

# cron validation
check("s14: validate valid cron", validate_cron("*/5 * * * *") is None)
check("s14: validate rejects bad field count", validate_cron("* * *") is not None)
check("s14: validate rejects out of range", validate_cron("70 * * * *") is not None)

# cron_matches
dt = datetime(2026, 5, 30, 14, 30, 0)  # 14:30
check("s14: cron_matches '30 14 * * *' at 14:30", cron_matches("30 14 * * *", dt))
check("s14: cron_matches '*/5 * * * *' at :30", cron_matches("*/5 * * * *", dt))
check("s14: cron_matches '* * * * 6' on Saturday",
      cron_matches("* * * * 6", dt), f"dow={dt.weekday()}")

# schedule_job
with cron_lock: scheduled_jobs.clear()

job = schedule_job("57 8 * * *", "morning check", recurring=True, durable=False)
check("s14: schedule_job returns CronJob", isinstance(job, CronJob))
check("s14: job has id", job.id.startswith("cron_"))
check("s14: job stored in scheduled_jobs", job.id in scheduled_jobs)

# cancel
r = cancel_job(job.id)
check("s14: cancel_job removes from registry", "Cancelled" in r)
check("s14: job gone after cancel", job.id not in scheduled_jobs)

with cron_lock: scheduled_jobs.clear()

# ══════════════════════════════════════════════════════════════════
section("s15 — Agent Teams: MessageBus / spawn_teammate / inbox")

from Agent.protocols.messaging import BUS, MAILBOX_DIR
from Agent.infra.config import active_teammates

# Clean
for f in MAILBOX_DIR.glob("*.jsonl"): f.unlink()
active_teammates.clear()

# MessageBus send
BUS.send("lead", "worker1", "Process task 42", "message", {"priority": "high"})
inbox_file = MAILBOX_DIR / "worker1.jsonl"
check("s15: inbox file created on send", inbox_file.exists())

# MessageBus read_inbox
msgs = BUS.read_inbox("worker1")
check("s15: read_inbox returns sent message", len(msgs) == 1, f"{len(msgs)}")
check("s15: message content matches", msgs[0]["content"] == "Process task 42")
check("s15: message metadata preserved", msgs[0]["metadata"]["priority"] == "high")
check("s15: inbox file consumed after read", not inbox_file.exists())

# read empty
check("s15: empty inbox returns []", BUS.read_inbox("nobody") == [])

# Clean
for f in MAILBOX_DIR.glob("*.jsonl"): f.unlink()

# ══════════════════════════════════════════════════════════════════
section("s16 — Team Protocols: shutdown handshake / plan approval / request_id")

from Agent.protocols.approval import (
    ProtocolState, pending_requests, new_request_id,
    request_shutdown, request_plan, review_plan,
    consume_lead_inbox, match_response,
)

# Clean
pending_requests.clear()
for f in MAILBOX_DIR.glob("*.jsonl"): f.unlink()

# request_shutdown
r = request_shutdown("worker1")
check("s16: shutdown request sent", "Shutdown request sent" in r)

# Check pending request
check("s16: pending_requests has entry", len(pending_requests) == 1)
req = list(pending_requests.values())[0]
check("s16: request type is shutdown", req.type == "shutdown")
check("s16: request status is pending", req.status == "pending")

# Simulate response
BUS.send("worker1", "lead", "Shutting down.", "shutdown_response",
         {"request_id": req.request_id, "approve": True})
consume_lead_inbox(route_protocol=True)
check("s16: shutdown approved via consume", pending_requests[req.request_id].status == "approved")

# request_plan
r = request_plan("worker2", "Implement feature X")
check("s16: plan request sent", "asked worker2" in r.lower() or "Asked worker2" in r)

# review_plan with missing request
r = review_plan("req_nonexistent", True)
check("s16: review_plan rejects unknown request", "not found" in r)

# Cleanup
pending_requests.clear()
for f in MAILBOX_DIR.glob("*.jsonl"): f.unlink()

# ══════════════════════════════════════════════════════════════════
section("s17 — Autonomous Agents: idle_poll / auto-claim / idle timeout")

from Agent.protocols.team import (
    scan_unclaimed_tasks, idle_poll, IDLE_POLL_INTERVAL, IDLE_TIMEOUT,
)
from Agent.infra.config import TASKS_DIR as _TD

# scan_unclaimed_tasks with no tasks
check("s17: scan_unclaimed_tasks empty", scan_unclaimed_tasks() == [])

# Create a pending task for auto-claim
for f in _TD.glob("task_*.json"): f.unlink()
from Agent.tools.task import create_task as _ct
t = _ct("Auto-claim test task", "Test autonomous agent")
check("s17: pending task exists for scan", t.status == "pending")
unclaimed = scan_unclaimed_tasks()
check("s17: scan finds unclaimed task", len(unclaimed) == 1, f"{len(unclaimed)}")

# Clean
for f in _TD.glob("task_*.json"): f.unlink()

# ══════════════════════════════════════════════════════════════════
section("s18 — Worktree Isolation: create / remove / keep / validation")

from Agent.tools.git import (
    create_worktree, remove_worktree, keep_worktree,
    validate_worktree_name, WORKTREES_DIR as _WD,
)

# Validation
check("s18: validate allows valid name", validate_worktree_name("test-wt") is None)
check("s18: validate rejects empty", validate_worktree_name("") is not None)
check("s18: validate rejects '..'", validate_worktree_name("..") is not None)
check("s18: validate rejects name > 64 chars", validate_worktree_name("a" * 65) is not None)

# keep_worktree (no git needed)
for f in _WD.glob("events.jsonl"): f.unlink()
r = keep_worktree("review-wt")
check("s18: keep_worktree logs event", "kept for review" in r.lower() or "Kept" in r)

# Clean
for f in _WD.glob("events.jsonl"): f.unlink()

# ══════════════════════════════════════════════════════════════════
section("s19 — MCP Plugin: connect / tool discovery / pool assembly")

from Agent.infra.mcp import (
    MCPClient, connect_mcp, normalize_mcp_name,
    mcp_clients, MOCK_SERVERS,
)

# Clean
mcp_clients.clear()

# normalize
check("s19: normalize_mcp_name replaces spaces", normalize_mcp_name("hello world") == "hello_world")
check("s19: normalize_mcp_name preserves valid chars", normalize_mcp_name("abc-123_ABC") == "abc-123_ABC")

# connect_mcp
r = connect_mcp("docs")
check("s19: connect_mcp docs succeeds", "Connected to MCP" in r)
check("s19: docs client registered", "docs" in mcp_clients)
check("s19: docs has tools", len(mcp_clients["docs"].tools) > 0)

# Call discovered tool via client
result = mcp_clients["docs"].call_tool("search", {"query": "auth"})
check("s19: MCP tool call works", "[docs]" in result and "auth" in result)

# connect unknown
r = connect_mcp("unknown_server")
check("s19: connect_mcp rejects unknown server", "Unknown server" in r)

# Already connected
r = connect_mcp("docs")
check("s19: connect_mcp detects duplicate", "already connected" in r)

# Tool pool assembly with MCP
tools, handlers = assemble_tool_pool()
mcp_tools = [t for t in tools if t["name"].startswith("mcp__")]
check("s19: MCP tools in assembled pool", len(mcp_tools) >= 2, f"{len(mcp_tools)} MCP tools")
check("s19: mcp__docs__search in pool", any(t["name"] == "mcp__docs__search" for t in tools))
check("s19: mcp__docs__search has handler", "mcp__docs__search" in handlers)

mcp_clients.clear()

# ══════════════════════════════════════════════════════════════════
section("s20 — Comprehensive Agent: all mechanisms integrated")

# Verify main entry point
from Agent.main import main as _main_fn
check("s20: main() function exists", callable(_main_fn))

# Verify the agent loop integrates memory + compaction + hooks + background
from Agent.planner.workflow import agent_loop as _al, _build_request
check("s20: _build_request helper exists", callable(_build_request))

# _build_request test: prepends memory to user message
msgs = [{"role": "user", "content": "original question"}]
result = _build_request(msgs, "<relevant_memories>\nmem content\n</relevant_memories>", 0)
check("s20: _build_request prepends memory to user message",
      "<relevant_memories>" in result[0]["content"] and "original question" in result[0]["content"])
check("s20: _build_request does not mutate original",
      msgs[0]["content"] == "original question")

# Skip if no memory (memory_turn=None)
result2 = _build_request(msgs, "some content", None)
check("s20: _build_request skips when memory_turn None", result2 == msgs)

# out of bounds memory_turn
result3 = _build_request(msgs, "some content", 999)
check("s20: _build_request skips when memory_turn OOB", result3 == msgs)

# Verify context integration
from Agent.memory.long_term import update_context, after_turn_memories
ctx = update_context({}, [])
check("s20: context dict has all keys",
      all(k in ctx for k in ["memories", "connected_mcp", "active_teammates"]))

# Verify after_turn_memories is callable (memory extraction uses LLM, skip actual call)
check("s20: after_turn_memories callable", callable(after_turn_memories))

# ══════════════════════════════════════════════════════════════════
# FINAL SUMMARY
print("\n" + "=" * 60)

# Count pass/fail per chapter
print(f"\n\033[1mRESULTS: {PASS} passed, {FAIL} failed\033[0m")
print("=" * 60)

# Cleanup test artifacts
cleanup("*.json")
cleanup("*.jsonl")
cleanup("*.md")
cleanup("*.txt")
for f in _PROJECT_ROOT.glob(".scheduled_tasks.json"): f.unlink()
for p in [_PROJECT_ROOT / d for d in [".transcripts", ".task_outputs/tool-results",
         ".tasks", ".worktrees", ".mailboxes", ".memory"]]:
    if p.exists():
        for f in p.iterdir():
            try: f.unlink()
            except: pass

sys.exit(0 if FAIL == 0 else 1)
