"""Short-term memory: skill loading, memory index, and context assembly."""

from datetime import datetime

from ..infra.config import WORKDIR, SKILLS_DIR, MEMORY_DIR, MEMORY_INDEX
from .writer import build_memory_system_prompt
from ..infra.mcp import mcp_clients
from ..infra.config import active_teammates


# ── Skill system ──

SKILL_REGISTRY: dict[str, dict] = {}


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, parts[2].strip()


def scan_skills():
    SKILL_REGISTRY.clear()
    if not SKILLS_DIR.exists():
        return
    for directory in sorted(SKILLS_DIR.iterdir()):
        if not directory.is_dir():
            continue
        manifest = directory / "SKILL.md"
        if not manifest.exists():
            continue
        raw = manifest.read_text(encoding="utf-8")
        meta, _ = _parse_frontmatter(raw)
        name = meta.get("name", directory.name)
        desc = meta.get("description", raw.split("\n")[0].lstrip("#").strip())
        SKILL_REGISTRY[name] = {
            "name": name,
            "description": desc,
            "content": raw,
        }


# Scan on first import.
scan_skills()


def list_skills() -> str:
    if not SKILL_REGISTRY:
        return "(no skills found)"
    return "\n".join(
        f"- {skill['name']}: {skill['description']}"
        for skill in SKILL_REGISTRY.values())


def load_skill(name: str) -> str:
    skill = SKILL_REGISTRY.get(name)
    if not skill:
        available = ", ".join(SKILL_REGISTRY.keys()) or "(none)"
        return f"Skill not found: {name}. Available: {available}"
    return skill["content"]


# ── System prompt assembly ──

PROMPT_SECTIONS = {
    "identity": "You are a coding agent. Act, don't explain.",
    "platform": (
        f"OS: {__import__('os').name} | "
        f"Shell: {__import__('os').environ.get('COMSPEC', 'cmd.exe')} | "
        f"Python: {__import__('sys').version.split()[0]}"
    ),
    "tools": "Available tools: bash, read_file, write_file, edit_file, glob, "
             "todo_write, task, load_skill, compact, "
             "create_task, list_tasks, get_task, claim_task, complete_task, "
             "schedule_cron, list_crons, cancel_cron, "
             "spawn_teammate, send_message, check_inbox, "
             "request_shutdown, request_plan, review_plan, "
             "create_worktree, remove_worktree, keep_worktree, "
             "connect_mcp, list_memories, read_memory, write_memory. "
             "MCP tools are prefixed mcp__{server}__{tool}.",
    "workspace": f"Working directory: {WORKDIR}",
    "rules": (
        "RULES:\n"
        "1. Use only Windows-compatible shell commands "
        "(dir not ls, del not rm, type not cat, findstr not grep). "
        "Prefer Python for cross-platform file operations.\n"
        "2. Only use todo_write for multi-step tasks (3+ distinct steps). "
        "Do NOT create todos for single commands or simple questions.\n"
        "3. Only write memories for: user preferences, project structure, "
        "long-term goals. Do NOT memorize one-off command results."
    ),
    "memory": ("Relevant memories are injected below when available. "
               "When the user says 'remember' or expresses a clear preference, "
               "use write_memory to persist it. "
               "Use list_memories and read_memory to check existing memories."),
}


def assemble_system_prompt(context: dict) -> str:
    sections = [PROMPT_SECTIONS["identity"],
                PROMPT_SECTIONS["platform"],
                PROMPT_SECTIONS["tools"],
                PROMPT_SECTIONS["rules"],
                PROMPT_SECTIONS["workspace"]]
    sections.append(f"Current time: {datetime.now().isoformat(timespec='seconds')}")
    sections.append("Skills catalog:\n" + list_skills() +
                    "\nUse load_skill(name) when a skill is relevant.")
    if context.get("memories"):
        sections.append(f"Relevant memories:\n{context['memories']}")
    else:
        mem_prompt = build_memory_system_prompt()
        if mem_prompt:
            sections.append(mem_prompt)
    mcp_names = list(mcp_clients.keys())
    if mcp_names:
        sections.append(f"Connected MCP servers: {', '.join(mcp_names)}")
    return "\n\n".join(sections)
