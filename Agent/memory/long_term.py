"""Long-term memory / context update — inject memory file and live state.

After each agent turn, memories are extracted from the conversation and persisted.
The memory INDEX is injected into the system prompt; relevant full content is
prepended to user messages in the agent loop (s09 pattern).
"""

from ..infra.mcp import mcp_clients
from ..infra.config import active_teammates
from .writer import read_memory_index, extract_memories, consolidate_memories


def update_context(context: dict, messages: list) -> dict:
    """Build context dict with memory index, MCP servers, and teammates."""
    return {
        "memories": read_memory_index(),
        "connected_mcp": list(mcp_clients.keys()),
        "active_teammates": list(active_teammates.keys()),
    }


def after_turn_memories(messages: list):
    """Called after each agent turn completes. Extracts and consolidates memories."""
    extract_memories(messages)
    consolidate_memories()
