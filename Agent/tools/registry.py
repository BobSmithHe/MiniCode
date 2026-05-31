"""Tool registry — schema definitions, handler dispatch, and dynamic pool assembly.

BUILTIN_TOOLS and BUILTIN_HANDLERS are populated at module load. MCP tools are
merged at call time by *assemble_tool_pool()*.
"""

from ..infra.mcp import mcp_clients, normalize_mcp_name
from ..memory.writer import (
    list_memory_files, read_memory_file, write_memory_file,
)

# ── Memory tool handlers ──

def run_list_memories() -> str:
    files = list_memory_files()
    if not files:
        return "(no memories)"
    return "\n".join(
        f"  [{mem['type']}] {mem['filename']} — {mem['name']}: {mem['description']}"
        for mem in files
    )


def run_read_memory(filename: str) -> str:
    content = read_memory_file(filename)
    if content is None:
        return f"Memory not found: {filename}"
    return content


def run_write_memory(name: str, mem_type: str, description: str, body: str) -> str:
    path = write_memory_file(name, mem_type, description, body)
    return f"Saved memory [{mem_type}] {name} -> {path.name}"


# ── Handler dispatch ──


def call_tool_handler(handler, args: dict, name: str) -> str:
    if not handler:
        return f"Unknown: {name}"
    try:
        return handler(**(args or {}))
    except TypeError as e:
        return f"Error: {e}"


# ── Import handler functions ──


from .shell import run_bash
from .file import run_read, run_write, run_edit, run_glob
from .task import run_todo_write
from .git import create_worktree, remove_worktree, keep_worktree

# Task CRUD wrappers  (also in tools.task but re-exported for registry)
from .task import (
    create_task as _create_task, list_tasks as _list_tasks,
    get_task_json, load_task, claim_task as _claim_task,
    complete_task as _complete_task,
)

# Scheduler and MCP wrappers
from ..infra.scheduler import run_schedule_cron, run_list_crons, run_cancel_cron
from ..infra.mcp import connect_mcp as _connect_mcp


# ── Task tool handler wrappers ──


def run_create_task(subject: str, description: str = "",
                    blockedBy: list[str] | None = None) -> str:
    task = _create_task(subject, description, blockedBy)
    deps = f" (blockedBy: {', '.join(blockedBy)})" if blockedBy else ""
    print(f"  \033[34m[create] {task.subject}{deps}\033[0m")
    return f"Created {task.id}: {task.subject}{deps}"


def run_list_tasks() -> str:
    tasks = _list_tasks()
    if not tasks:
        return "No tasks."
    return "\n".join(
        f"  {t.id}: {t.subject} [{t.status}]"
        + (f" (wt:{t.worktree})" if t.worktree else "")
        for t in tasks)


def run_get_task(task_id: str) -> str:
    try:
        return get_task_json(task_id)
    except FileNotFoundError:
        return f"Error: task {task_id} not found"


def run_claim_task(task_id: str) -> str:
    try:
        return _claim_task(task_id, owner="agent")
    except FileNotFoundError:
        return f"Error: task {task_id} not found"


def run_complete_task(task_id: str) -> str:
    try:
        return _complete_task(task_id)
    except FileNotFoundError:
        return f"Error: task {task_id} not found"


def run_create_worktree_w(name: str, task_id: str = "") -> str:
    return create_worktree(name, task_id)


def run_remove_worktree_w(name: str, discard_changes: bool = False) -> str:
    return remove_worktree(name, discard_changes)


def run_keep_worktree_w(name: str) -> str:
    return keep_worktree(name)


def run_connect_mcp(name: str) -> str:
    return _connect_mcp(name)


# ── Protocol / team handler stubs (filled by protocols layer at init time) ──

run_spawn_teammate = None   # type: callable | None
run_send_message = None      # type: callable | None
run_check_inbox = None       # type: callable | None
run_request_shutdown = None  # type: callable | None
run_request_plan = None      # type: callable | None
run_review_plan = None       # type: callable | None


def _resolve_protocol_handlers():
    """Wire protocol handlers once the protocols layer has been loaded."""
    global run_spawn_teammate, run_send_message, run_check_inbox
    global run_request_shutdown, run_request_plan, run_review_plan

    from ..protocols.team import spawn_teammate_thread as _spawn
    from ..protocols.messaging import BUS
    from ..protocols.approval import (
        consume_lead_inbox, request_shutdown as _shutdown,
        request_plan as _req_plan, review_plan as _rev_plan,
    )

    def _spawn_teammate(name: str, role: str, prompt: str) -> str:
        return _spawn(name, role, prompt)

    def _send_message(to: str, content: str) -> str:
        BUS.send("lead", to, content)
        return f"Sent to {to}"

    def _check_inbox() -> str:
        msgs = consume_lead_inbox(route_protocol=True)
        if not msgs:
            return "(inbox empty)"
        lines = []
        for m in msgs:
            meta = m.get("metadata", {})
            req_id = meta.get("request_id", "")
            tag = f" [{m['type']} req:{req_id}]" if req_id else f" [{m['type']}]"
            lines.append(f"  [{m['from']}]{tag} {m['content'][:200]}")
        return "\n".join(lines)

    run_spawn_teammate = _spawn_teammate
    run_send_message = _send_message
    run_check_inbox = _check_inbox
    run_request_shutdown = _shutdown
    run_request_plan = _req_plan
    run_review_plan = _rev_plan


# ── Subagent stub ──

run_subagent = None  # type: callable | None


def _resolve_subagent():
    from ..executor.subagent import spawn_subagent
    global run_subagent
    run_subagent = spawn_subagent


# ── Compact / skill stubs ──

run_compact = None    # type: callable | None
load_skill_fn = None  # type: callable | None


def _resolve_skill():
    from ..memory.short_term import load_skill
    global load_skill_fn
    load_skill_fn = load_skill


# ── Tool schema definitions ──

BUILTIN_TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object",
                      "properties": {"command": {"type": "string"},
                                     "run_in_background": {"type": "boolean"}},
                      "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "limit": {"type": "integer"},
                                     "offset": {"type": "integer"}},
                      "required": ["path"]}},
    {"name": "write_file", "description": "Write content to a file.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in a file once.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "old_text": {"type": "string"},
                                     "new_text": {"type": "string"}},
                      "required": ["path", "old_text", "new_text"]}},
    {"name": "glob", "description": "Find files matching a glob pattern.",
     "input_schema": {"type": "object",
                      "properties": {"pattern": {"type": "string"}},
                      "required": ["pattern"]}},
    {"name": "todo_write",
     "description": "Create and manage a task list for the current session.",
     "input_schema": {"type": "object",
                      "properties": {"todos": {"type": "array",
                          "items": {"type": "object",
                                    "properties": {
                                        "content": {"type": "string"},
                                        "status": {"type": "string",
                                                   "enum": ["pending", "in_progress", "completed"]}},
                                    "required": ["content", "status"]}}},
                      "required": ["todos"]}},
    {"name": "task",
     "description": "Launch a focused subagent. Returns only its final summary.",
     "input_schema": {"type": "object",
                      "properties": {"description": {"type": "string"}},
                      "required": ["description"]}},
    {"name": "load_skill",
     "description": "Load the full content of a skill by name.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "compact",
     "description": "Summarize earlier conversation and continue with compacted context.",
     "input_schema": {"type": "object",
                      "properties": {"focus": {"type": "string"}},
                      "required": []}},
    {"name": "create_task", "description": "Create a task.",
     "input_schema": {"type": "object",
                      "properties": {"subject": {"type": "string"},
                                     "description": {"type": "string"},
                                     "blockedBy": {"type": "array",
                                                   "items": {"type": "string"}}},
                      "required": ["subject"]}},
    {"name": "list_tasks", "description": "List all tasks.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_task", "description": "Get full task details.",
     "input_schema": {"type": "object",
                      "properties": {"task_id": {"type": "string"}},
                      "required": ["task_id"]}},
    {"name": "claim_task", "description": "Claim a pending task.",
     "input_schema": {"type": "object",
                      "properties": {"task_id": {"type": "string"}},
                      "required": ["task_id"]}},
    {"name": "complete_task", "description": "Complete an in-progress task.",
     "input_schema": {"type": "object",
                      "properties": {"task_id": {"type": "string"}},
                      "required": ["task_id"]}},
    {"name": "schedule_cron",
     "description": ("Schedule a cron job. cron is 5-field: min hour dom "
                     "month dow. For one-shot reminders, compute the target "
                     "minute and set recurring=false."),
     "input_schema": {"type": "object",
                      "properties": {"cron": {"type": "string"},
                                     "prompt": {"type": "string"},
                                     "recurring": {"type": "boolean"},
                                     "durable": {"type": "boolean"}},
                      "required": ["cron", "prompt"]}},
    {"name": "list_crons", "description": "List registered cron jobs.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "cancel_cron", "description": "Cancel a cron job by ID.",
     "input_schema": {"type": "object",
                      "properties": {"job_id": {"type": "string"}},
                      "required": ["job_id"]}},
    {"name": "spawn_teammate", "description": "Spawn an autonomous teammate.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"},
                                     "role": {"type": "string"},
                                     "prompt": {"type": "string"}},
                      "required": ["name", "role", "prompt"]}},
    {"name": "send_message", "description": "Send message to a teammate.",
     "input_schema": {"type": "object",
                      "properties": {"to": {"type": "string"},
                                     "content": {"type": "string"}},
                      "required": ["to", "content"]}},
    {"name": "check_inbox",
     "description": "Check inbox for messages and protocol responses.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "request_shutdown",
     "description": "Request a teammate to shut down.",
     "input_schema": {"type": "object",
                      "properties": {"teammate": {"type": "string"}},
                      "required": ["teammate"]}},
    {"name": "request_plan",
     "description": "Ask a teammate to submit a plan.",
     "input_schema": {"type": "object",
                      "properties": {"teammate": {"type": "string"},
                                     "task": {"type": "string"}},
                      "required": ["teammate", "task"]}},
    {"name": "review_plan",
     "description": "Approve or reject a submitted plan.",
     "input_schema": {"type": "object",
                      "properties": {"request_id": {"type": "string"},
                                     "approve": {"type": "boolean"},
                                     "feedback": {"type": "string"}},
                      "required": ["request_id", "approve"]}},
    {"name": "create_worktree",
     "description": "Create an isolated git worktree.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"},
                                     "task_id": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "remove_worktree",
     "description": "Remove a worktree. Refuses if changes exist.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"},
                                     "discard_changes": {"type": "boolean"}},
                      "required": ["name"]}},
    {"name": "keep_worktree",
     "description": "Keep a worktree for manual review.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "connect_mcp",
     "description": "Connect to an MCP server (docs, deploy) and discover tools.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "list_memories",
     "description": "List all persistent memory files.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_memory",
     "description": "Read a single memory file's full content.",
     "input_schema": {"type": "object",
                      "properties": {"filename": {"type": "string"}},
                      "required": ["filename"]}},
    {"name": "write_memory",
     "description": "Write a new persistent memory. Types: user, feedback, project, reference.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"},
                                     "mem_type": {"type": "string"},
                                     "description": {"type": "string"},
                                     "body": {"type": "string"}},
                      "required": ["name", "mem_type", "description", "body"]}},
]


def _build_handlers_dict() -> dict:
    """Build the builtin handler map, resolving protocol stubs if needed."""
    if run_spawn_teammate is None:
        _resolve_protocol_handlers()
    if run_subagent is None:
        _resolve_subagent()
    if load_skill_fn is None:
        _resolve_skill()

    return {
        "bash": run_bash, "read_file": run_read, "write_file": run_write,
        "edit_file": run_edit, "glob": run_glob,
        "todo_write": run_todo_write, "task": run_subagent,
        "load_skill": load_skill_fn,
        "create_task": run_create_task, "list_tasks": run_list_tasks,
        "get_task": run_get_task,
        "claim_task": run_claim_task, "complete_task": run_complete_task,
        "schedule_cron": run_schedule_cron,
        "list_crons": run_list_crons,
        "cancel_cron": run_cancel_cron,
        "spawn_teammate": run_spawn_teammate,
        "send_message": run_send_message, "check_inbox": run_check_inbox,
        "request_shutdown": run_request_shutdown,
        "request_plan": run_request_plan, "review_plan": run_review_plan,
        "create_worktree": run_create_worktree_w,
        "remove_worktree": run_remove_worktree_w,
        "keep_worktree": run_keep_worktree_w,
        "connect_mcp": run_connect_mcp,
        "list_memories": run_list_memories,
        "read_memory": run_read_memory,
        "write_memory": run_write_memory,
    }


def assemble_tool_pool() -> tuple[list[dict], dict]:
    """Merge builtin tools + all connected MCP tools into one pool."""
    tools = list(BUILTIN_TOOLS)
    handlers = _build_handlers_dict()
    for server_name, mcp_client in mcp_clients.items():
        safe_server = normalize_mcp_name(server_name)
        for tool_def in mcp_client.tools:
            safe_tool = normalize_mcp_name(tool_def["name"])
            prefixed = f"mcp__{safe_server}__{safe_tool}"
            tools.append({
                "name": prefixed,
                "description": tool_def.get("description", ""),
                "input_schema": tool_def.get("inputSchema", {}),
            })
            # Late-capture closure for the MCP tool handler.
            handlers[prefixed] = (
                lambda *, c=mcp_client, t=tool_def["name"], **kw: c.call_tool(t, kw))
    return tools, handlers
