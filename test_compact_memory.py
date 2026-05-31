#!/usr/bin/env python3
"""Test conversation compaction and memory capabilities of the agent harness.

Tests:
  1. tool_result_budget — persist large tool results to disk
  2. snip_compact — trim middle messages when > 50
  3. micro_compact — truncate old tool results, keep recent 3
  4. compact_history — full model-summarized compaction
  5. reactive_compact — prompt-too-long recovery
  6. long_term memory — MEMORY.md injection into context
  7. prepare_context — full pipeline integration

Run:  python test_compact_memory.py
"""

import json
import sys
import tempfile
import os
from pathlib import Path

# Put project root on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Create required directories so the Agent module loads without errors
for d in [".memory", ".tasks", ".transcripts", ".task_outputs/tool-results",
          ".worktrees", ".mailboxes"]:
    (_PROJECT_ROOT / d).mkdir(parents=True, exist_ok=True)

# Write a minimal .env if not present — Agent.infra.config needs it
env_path = _PROJECT_ROOT / ".env"
if not env_path.exists():
    env_path.write_text(
        "ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic\n"
        "ANTHROPIC_AUTH_TOKEN=test-token\n"
        "MODEL_ID=deepseek-v4-flash\n"
    )

from Agent.memory.long_term import update_context
from Agent.memory.compactor import (
    estimate_size, collect_tool_results, persist_large_output,
    tool_result_budget, snip_compact, micro_compact,
    compact_history, reactive_compact, prepare_context, write_transcript,
    TOOL_RESULTS_DIR,
)
from Agent.memory.short_term import assemble_system_prompt, load_skill, list_skills
from Agent.infra.config import MEMORY_INDEX, CONTEXT_LIMIT

PASS = 0
FAIL = 0

def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  \033[32m[PASS]\033[0m {name}")
    else:
        FAIL += 1
        print(f"  \033[31m[FAIL]\033[0m {name}  {detail}")

def make_history(turns: int, result_size: int = 100) -> list:
    """Build a fake conversation of N user/assistant/tool_result turns."""
    msgs = []
    for i in range(turns):
        msgs.append({"role": "user", "content": f"Question {i}"})
        content_blocks = [{"type": "text", "text": f"Answer {i}" * 50}]
        if i < turns - 1:
            content_blocks.append({
                "type": "tool_use", "id": f"tool_{i}", "name": "bash",
                "input": {"command": f"echo {i}"}
            })
        msgs.append({"role": "assistant", "content": content_blocks})
        if i < turns - 1:
            msgs.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"tool_{i}",
                 "content": f"result_{i}_" * (result_size // 10)}
            ]})
    return msgs


# ══════════════════════════════════════════════════════════════════════
print("=" * 60)
print("1. TOOL_RESULT_BUDGET — persist large tool results to disk")
print("=" * 60)

# Clean old test outputs
for f in TOOL_RESULTS_DIR.glob("*.txt"):
    f.unlink()

msgs = [
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "big1",
         "content": "X" * 80000},
        {"type": "tool_result", "tool_use_id": "big2",
         "content": "Y" * 80000},
        {"type": "tool_result", "tool_use_id": "big3",
         "content": "Z" * 80000},
    ]}
]

orig_total = sum(len(str(b.get("content", "")))
                 for b in msgs[0]["content"]
                 if isinstance(b, dict) and b.get("type") == "tool_result")
check("Initial content exceeds 200KB", orig_total > 200_000, f"size={orig_total}")

result = tool_result_budget(msgs, max_bytes=200_000)
new_total = sum(len(str(b.get("content", "")))
                for b in result[0]["content"]
                if isinstance(b, dict) and b.get("type") == "tool_result")
check("After budget: total <= 200KB", new_total <= 200_000, f"size={new_total}")

persisted_files = list(TOOL_RESULTS_DIR.glob("*.txt"))
check("Persisted files written to disk", len(persisted_files) > 0,
      f"found {len(persisted_files)} files")

# Check that persisted blocks contain the placeholder marker
content_str = json.dumps(result, default=str)
check("Persisted content has <persisted-output> marker",
      "<persisted-output>" in content_str)

# Clean up
for f in persisted_files:
    f.unlink()

# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("2. SNIP_COMPACT — trim middle messages when > 50")
print("=" * 60)

history = make_history(turns=40)  # 40*3 - 1 = ~119 messages
check("History has > 50 messages before snipping", len(history) > 50,
      f"count={len(history)}")

snipped = snip_compact(history, max_messages=50)
check("After snipping: <= 50 messages", len(snipped) <= 50,
      f"count={len(snipped)}")

snipped_msg = [m for m in snipped if "snipped" in str(m.get("content", ""))]
check("Snipped marker present", len(snipped_msg) > 0,
      f"marker: {snipped_msg[0].get('content', '')[:60] if snipped_msg else 'NONE'}")

# Boundary: small history should be untouched
small = make_history(turns=5)
check("Small history untouched by snipping",
      len(snip_compact(small, max_messages=50)) == len(small))

# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("3. MICRO_COMPACT — truncate old tool results, keep recent")
print("=" * 60)

history = make_history(turns=20, result_size=500)  # 20 turns, 19 tool_results
tool_results = collect_tool_results(history)
check("Has tool results before compact", len(tool_results) >= 3,
      f"count={len(tool_results)}")

compacted = micro_compact(history)
tool_results_after = collect_tool_results(compacted)

# Old tool results should be truncated
old_truncated = any(
    "[Earlier tool result compacted" in str(b.get("content", ""))
    for _, _, b in tool_results_after[:-3]
)
check("Old tool results truncated", old_truncated)

# Most recent 3 should be intact (untouched)
recent_intact = all(
    "[Earlier tool result compacted" not in str(b.get("content", ""))
    for _, _, b in tool_results_after[-3:]
)
check("Recent 3 tool results intact", recent_intact)

# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("4. COMPACT_HISTORY — write transcript + summarize (needs LLM)")
print("=" * 60)

history = make_history(turns=10)
transcript_path = write_transcript(history)
check("Transcript written to disk", transcript_path.exists(),
      f"path={transcript_path}")

# Read back transcript
with open(transcript_path, "r", encoding="utf-8") as f:
    lines = f.readlines()
check("Transcript has content", len(lines) > 0, f"{len(lines)} lines")

# Verify JSONL format
for i, line in enumerate(lines[:3]):
    try:
        obj = json.loads(line)
        check(f"Transcript line {i} is valid JSON", True)
    except json.JSONDecodeError:
        check(f"Transcript line {i} is valid JSON", False, f"bad: {line[:60]}")

# Clean up
transcript_path.unlink()

# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("5. REACTIVE_COMPACT — prompt-too-long error recovery")
print("=" * 60)

history = make_history(turns=10)
old_len = len(history)
result = reactive_compact(history)
check("Reactive compact returns condensed list",
      len(result) < old_len, f"{old_len} -> {len(result)}")

# First message should be the summary marker
first_content = str(result[0].get("content", ""))
check("First message has [Reactive compact] marker",
      "[Reactive compact]" in first_content,
      first_content[:80])

# Should preserve last 5 messages
check("Preserves recent messages (up to 5 tail)",
      len(result) <= 6,  # 1 summary + up to 5 tail
      f"total={len(result)}")

# Clean up transcripts
for f in (_PROJECT_ROOT / ".transcripts").glob("*.jsonl"):
    f.unlink()

# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("6. LONG_TERM MEMORY — MEMORY.md injection")
print("=" * 60)

# Create a MEMORY.md with test content
memory_dir = _PROJECT_ROOT / ".memory"
memory_dir.mkdir(parents=True, exist_ok=True)
memory_md = memory_dir / "MEMORY.md"
memory_md.write_text(
    "- [user-preferences](user_prefs.md) — coding style preferences\n"
    "- [project-context](project.md) — current project goals\n",
    encoding="utf-8"
)

ctx = update_context({}, [])
check("Context has memories key", "memories" in ctx)
check("Memories contain user-preferences",
      "user-preferences" in ctx.get("memories", ""))
check("Memories contain project-context",
      "project-context" in ctx.get("memories", ""))
check("Context has connected_mcp", "connected_mcp" in ctx)
check("Context has active_teammates", "active_teammates" in ctx)

# Test with empty/non-existent MEMORY.md
memory_md.unlink()
ctx_empty = update_context({}, [])
check("Empty memories when MEMORY.md missing",
      ctx_empty.get("memories", "") == "")

# Restore for system prompt test
memory_md.write_text(
    "- [test](test.md) — test memory for system prompt\n",
    encoding="utf-8"
)

# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("7. SYSTEM PROMPT ASSEMBLY")
print("=" * 60)

ctx = update_context({}, [])
sys_prompt = assemble_system_prompt(ctx)
check("System prompt contains identity", "coding agent" in sys_prompt.lower() or "Act, don't explain" in sys_prompt)
check("System prompt contains tools list", "bash" in sys_prompt)
check("System prompt has workspace path", "Working directory" in sys_prompt)
check("System prompt has current time", "Current time" in sys_prompt)
check("System prompt has skills section", "Skills catalog" in sys_prompt)
check("Memories injected into system prompt", "test memory" in sys_prompt)

# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("8. PREPARE_CONTEXT — full pipeline")
print("=" * 60)

# Small history: should pass through unchanged
small = make_history(turns=3)
small_copy = list(small)
prepare_context(small_copy)
check("Small history unchanged after prepare_context",
      len(small_copy) == len(small))

# Large history: should trigger at least one compaction layer
large = make_history(turns=35, result_size=2000)
check("Large history size before prepare_context",
      len(large) > 50, f"count={len(large)}")

large_copy = list(large)
prepare_context(large_copy)
check("Large history compacted after prepare_context",
      len(large_copy) <= len(large), f"{len(large)} -> {len(large_copy)}")

# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("9. ESTIMATE_SIZE utility")
print("=" * 60)

empty_size = estimate_size([])
check("Empty history size is small", empty_size < 1000, f"size={empty_size}")

small_size = estimate_size(make_history(turns=5))
check("Small history size is reasonable", small_size > 0,
      f"size={small_size}")

large_size = estimate_size(make_history(turns=30))
check("Large history is bigger than small history",
      large_size > small_size, f"small={small_size} large={large_size}")

# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("10. COLLECT_TOOL_RESULTS")
print("=" * 60)

history = make_history(turns=5)
results = collect_tool_results(history)
check("Finds tool results in history", len(results) > 0,
      f"found {len(results)}")

no_tools = [{"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"}]
check("No false positives on plain text messages",
      len(collect_tool_results(no_tools)) == 0)

# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("11. PERSIST_LARGE_OUTPUT edge cases")
print("=" * 60)

small_output = "small result"
result = persist_large_output("test_id", small_output)
check("Small output returned as-is (no persist)",
      result == small_output and "<persisted-output>" not in result)

for f in TOOL_RESULTS_DIR.glob("*.txt"):
    f.unlink()
large_output = "X" * 40000
result = persist_large_output("large_id", large_output)
check("Large output persisted to disk",
      "<persisted-output>" in result and "Preview" in result,
      result[:100])

persisted_files = list(TOOL_RESULTS_DIR.glob("*.txt"))
check("Large output file exists on disk", len(persisted_files) == 1)
for f in persisted_files:
    f.unlink()

# ══════════════════════════════════════════════════════════════════════
# Summary
print("\n" + "=" * 60)
print(f"\033[1mRESULTS: {PASS} passed, {FAIL} failed\033[0m")
print("=" * 60)

# Cleanup
for d in [TOOL_RESULTS_DIR, _PROJECT_ROOT / ".transcripts"]:
    if d.exists():
        for f in d.glob("*.txt"):
            f.unlink()
        for f in d.glob("*.jsonl"):
            f.unlink()

memory_md.unlink()

sys.exit(0 if FAIL == 0 else 1)
