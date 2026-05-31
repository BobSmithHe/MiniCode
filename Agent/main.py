#!/usr/bin/env python3
"""
Claude Code — modular agent harness.

Run from the project root:
  python -m agent

Requires: pip install anthropic python-dotenv + .env with ANTHROPIC_API_KEY / MODEL_ID
"""

import time, threading

from .infra import config as _cfg
from .infra.config import (
    PROMPT, agent_lock,
)
from .infra.logging import terminal_print
from .infra.scheduler import consume_cron_queue, load_durable_jobs, cron_scheduler_loop
from .memory.long_term import update_context
from .protocols.events import trigger_hooks
from .protocols.approval import consume_lead_inbox
from .planner.workflow import agent_loop


def print_turn_assistants(messages: list, turn_start: int):
    for msg in messages[turn_start:]:
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if getattr(block, "type", None) == "text":
                terminal_print(block.text)


def cron_autorun_loop(history: list, context: dict):
    while True:
        time.sleep(1)
        fired = consume_cron_queue()
        if not fired:
            continue
        with agent_lock:
            turn_start = len(history)
            for job in fired:
                history.append({"role": "user",
                                "content": f"[Scheduled] {job.prompt}"})
                terminal_print(
                    f"  \033[35m[cron auto] {job.prompt[:60]}\033[0m")
            agent_loop(history, context)
            context.update(update_context(context, history))
            print_turn_assistants(history, turn_start)


def main():
    _cfg.CLI_ACTIVE = True

    # Restore durable cron jobs and start the scheduler daemon.
    load_durable_jobs()
    threading.Thread(target=cron_scheduler_loop, daemon=True).start()

    print("Claude Code — modular agent harness")
    print("Enter a question, press Enter to send. Type q to quit.\n")

    history: list = []
    context = update_context({}, [])

    # Background cron auto-run thread.
    threading.Thread(target=cron_autorun_loop,
                     args=(history, context), daemon=True).start()

    while True:
        try:
            query = input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break

        trigger_hooks("UserPromptSubmit", query)
        turn_start = len(history)
        history.append({"role": "user", "content": query})

        with agent_lock:
            agent_loop(history, context)
            context = update_context(context, history)
            print_turn_assistants(history, turn_start)

        inbox = consume_lead_inbox(route_protocol=True)
        if inbox:
            def inbox_label(msg):
                req_id = msg.get("metadata", {}).get("request_id", "")
                suffix = f" req:{req_id}" if req_id else ""
                return f"{msg.get('type', 'message')}{suffix}"

            inbox_text = "\n".join(
                f"From {m['from']} [{inbox_label(m)}]: "
                f"{m['content'][:200]}" for m in inbox)
            history.append({"role": "user",
                            "content": f"[Inbox]\n{inbox_text}"})
        print()


if __name__ == "__main__":
    main()
