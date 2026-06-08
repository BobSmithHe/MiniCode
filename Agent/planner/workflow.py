"""Main agent loop — the central while-True orchestration.

One cycle: inject scheduled/background work, prepare context, call
the model, execute tool_use blocks, append tool_results, repeat.
"""

from ..infra import config as _cfg
from ..infra.llm import has_tool_use, is_prompt_too_long_error
from ..infra.llm import RecoveryState  # noqa: F401  (imported for type reference)
from ..infra.scheduler import consume_cron_queue
from ..memory.short_term import assemble_system_prompt
from ..memory.long_term import update_context, after_turn_memories
from ..memory.writer import load_memories
from ..memory.compactor import prepare_context, compact_history, reactive_compact
from ..tools.registry import assemble_tool_pool, call_tool_handler
from ..executor.dispatcher import build_user_content, inject_background_notifications
from ..executor.executor import should_run_background, start_background_task
from ..protocols import events as _events
from ..infra.logging import terminal_print, tool_start as _log_tool_start, tool_end as _log_tool_end, turn_start as _log_turn_start, turn_end as _log_turn_end

# Re-export assemble_tool_pool for convenience
from ..tools.registry import assemble_tool_pool  # noqa: F811


def call_llm(messages: list, context: dict, tools: list,
             state, max_tokens: int):
    """Call the LLM with retry/error recovery via the infra.llm layer."""
    from ..infra.config import client
    from ..infra.llm import with_retry

    system = assemble_system_prompt(context)
    return with_retry(
        lambda: client.messages.create(
            model=state.current_model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens),
        state)


def _build_request(messages: list, memories_content: str,
                   memory_turn: int | None) -> list:
    """Prepends relevant memory content to the user message at memory_turn (s09)."""
    if not memories_content or memory_turn is None or memory_turn >= len(messages):
        return messages
    request = messages.copy()
    request[memory_turn] = {
        **messages[memory_turn],
        "content": memories_content + "\n\n" + messages[memory_turn]["content"],
    }
    return request


def agent_loop(messages: list, context: dict):
    tools, handlers = assemble_tool_pool()
    state = RecoveryState()
    max_tokens = _cfg.DEFAULT_MAX_TOKENS
    _events._stop_turn_start = len(messages)
    _log_turn_start()

    # s09: load relevant memories once at turn entry
    memories_content = load_memories(messages)
    memory_turn = (len(messages) - 1
                   if messages and isinstance(messages[-1].get("content"), str)
                   else None)

    while True:
        # Inject scheduled jobs and background notifications.
        fired = consume_cron_queue()
        for job in fired:
            messages.append({"role": "user",
                             "content": f"[Scheduled] {job.prompt}"})
            print(f"  \033[35m[cron inject] {job.prompt[:60]}\033[0m")

        inject_background_notifications(messages)

        # Todo reminder every 3 turns.
        if _cfg.rounds_since_todo >= 3:
            messages.append({"role": "user",
                             "content": "<reminder>Update your todos.</reminder>"})
            _cfg.rounds_since_todo = 0

        pre_compress = [
            m if isinstance(m, dict) else {"role": m.role, "content": str(m.content)}
            for m in messages
        ]
        prepare_context(messages)
        context = update_context(context, messages)
        tools, handlers = assemble_tool_pool()

        # s09: prepend relevant memories to user message for this LLM call
        request_messages = _build_request(messages, memories_content, memory_turn)

        # LLM call with error recovery.
        print("  \033[90m...\033[0m")
        try:
            response = call_llm(request_messages, context, tools, state, max_tokens)
        except Exception as e:
            if is_prompt_too_long_error(e) and not state.has_attempted_reactive_compact:
                messages[:] = reactive_compact(messages)
                state.has_attempted_reactive_compact = True
                continue
            messages.append({"role": "assistant", "content": [
                {"type": "text", "text": f"[Error] {type(e).__name__}: {e}"}]})
            return

        # Max-tokens escalation / continuation.
        if response.stop_reason == "max_tokens":
            if not state.has_escalated:
                max_tokens = _cfg.ESCALATED_MAX_TOKENS
                state.has_escalated = True
                print(f"  \033[33m[max_tokens] retry with {max_tokens}\033[0m")
                continue
            messages.append({"role": "assistant", "content": response.content})
            if state.recovery_count < _cfg.MAX_RECOVERY_RETRIES:
                messages.append({"role": "user", "content": _cfg.CONTINUATION_PROMPT})
                state.recovery_count += 1
                continue
            return

        max_tokens = _cfg.DEFAULT_MAX_TOKENS
        state.has_escalated = False
        messages.append({"role": "assistant", "content": response.content})

        # No tool_use → stop. Extract memories from this turn.
        if not has_tool_use(response.content):
            _events.trigger_hooks("Stop", messages)
            _log_turn_end(sum(1 for b in response.content if b.type == "tool_use"))
            after_turn_memories(pre_compress)
            return

        # Execute each tool_use block.
        _TOOL_LABELS = {
            "read_file": "Read", "write_file": "Write", "edit_file": "Edit",
            "bash": "Bash", "glob": "Glob", "task": "Task",
            "todo_write": "Todo", "load_skill": "Skill",
            "create_task": "CreateTask", "list_tasks": "ListTasks",
            "get_task": "GetTask", "claim_task": "ClaimTask",
            "complete_task": "CompleteTask",
            "list_memories": "ListMemories", "read_memory": "ReadMemory",
            "write_memory": "WriteMemory",
            "spawn_teammate": "Spawn", "send_message": "Send",
            "schedule_cron": "Cron", "connect_mcp": "MCP",
        }
        results = []
        compacted_now = False
        for block in response.content:
            if block.type != "tool_use":
                continue
            label = _TOOL_LABELS.get(block.name, block.name)
            if block.name == "bash":
                cmd = block.input.get("command", "")[:60]
                print(f"  \033[36m{label}(\033[0m{cmd}\033[36m)\033[0m")
            elif block.name in ("read_file", "write_file", "edit_file"):
                path = block.input.get("path", "")
                print(f"  \033[36m{label}(\033[0m{path}\033[36m)\033[0m")
            else:
                print(f"  \033[36m{label}\033[0m")

            if block.name == "compact":
                messages[:] = compact_history(messages)
                messages.append({"role": "user",
                                 "content": "[Compacted. Continue with summarized context.]"})
                compacted_now = True
                break

            blocked = _events.trigger_hooks("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": str(blocked)})
                continue

            if should_run_background(block.name, block.input):
                bg_id = start_background_task(block, handlers)
                output = (f"[Background task {bg_id} started] "
                          "Result will arrive as a task_notification.")
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": output})
                continue

            handler = handlers.get(block.name)
            _log_tool_start(block.name, block.input)
            t0 = __import__("time").time()
            output = call_tool_handler(handler, block.input, block.name)
            t1 = __import__("time").time()
            _log_tool_end(block.name, output, (t1 - t0) * 1000)
            _events.trigger_hooks("PostToolUse", block, output)
            terminal_print(str(output)[:300])

            if block.name == "todo_write":
                _cfg.rounds_since_todo = 0
            else:
                _cfg.rounds_since_todo += 1

            results.append({"type": "tool_result",
                            "tool_use_id": block.id, "content": output})

        if compacted_now:
            continue

        messages.append({"role": "user", "content": build_user_content(results)})
