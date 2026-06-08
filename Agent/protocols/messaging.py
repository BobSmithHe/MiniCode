"""MessageBus — SQLite-backed team communication.

Team messages are stored in agent.db (messages table). The SQLite WAL mode
provides built-in locking for concurrent access from multiple threads.
"""

from ..infra.logging import terminal_print
from ..infra.storage.db import msg_send, msg_read


class MessageBus:
    def send(self, from_agent: str, to_agent: str, content: str,
             msg_type: str = "message", metadata: dict | None = None):
        msg_send(from_agent, to_agent, content, msg_type, metadata)
        terminal_print(f"  \033[33m[bus] {from_agent} -> {to_agent}: "
                       f"({msg_type}) {content[:50]}\033[0m")

    def read_inbox(self, agent: str) -> list[dict]:
        rows = msg_read(agent)
        return [{"from": r["from_agent"], "to": r["to_agent"],
                 "content": r["content"], "type": r["msg_type"],
                 "ts": r.get("ts", 0),
                 "metadata": r.get("metadata", {})} for r in rows]


BUS = MessageBus()
