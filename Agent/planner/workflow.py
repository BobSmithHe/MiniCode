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
from ..protocols.events import trigger_hooks
from ..infra.logging import terminal_print

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
            trigger_hooks("Stop", messages)
            after_turn_memories(pre_compress)
            return

        # Execute each tool_use block.
        results = []
        compacted_now = False
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"\033[36m> {block.name}\033[0m")

            if block.name == "compact":
                messages[:] = compact_history(messages)
                messages.append({"role": "user",
                                 "content": "[Compacted. Continue with summarized context.]"})
                compacted_now = True
                break

            blocked = trigger_hooks("PreToolUse", block)
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
            output = call_tool_handler(handler, block.input, block.name)
            trigger_hooks("PostToolUse", block, output)
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
