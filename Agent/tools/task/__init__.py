"""Task system — SQLite-backed task records with dependency graph."""

import json, time
from dataclasses import dataclass, asdict

from ...infra.storage.db import (
    task_create as _db_create, task_get, task_list, task_update, task_delete,
)

CURRENT_TODOS: list[dict] = []


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]
    worktree: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> "Task":
        return cls(
            id=row["id"],
            subject=row["subject"],
            description=row.get("description", ""),
            status=row.get("status", "pending"),
            owner=row.get("owner"),
            blockedBy=row.get("blocked_by", []),
            worktree=row.get("worktree"),
        )


def create_task(subject: str, description: str = "",
                blockedBy: list[str] | None = None) -> Task:
    row = _db_create(subject, description, blockedBy or [])
    return Task.from_row(row)


def save_task(task: Task):
    task_update(task.id, subject=task.subject, description=task.description,
                status=task.status, owner=task.owner,
                blocked_by=task.blockedBy, worktree=task.worktree)


def load_task(task_id: str) -> Task:
    row = task_get(task_id)
    if row is None:
        raise FileNotFoundError(f"Task {task_id} not found")
    return Task.from_row(row)


def list_tasks() -> list[Task]:
    return [Task.from_row(r) for r in task_list()]


def get_task_json(task_id: str) -> str:
    return json.dumps(task_get(task_id) or {}, indent=2)


def can_start(task_id: str) -> bool:
    task = task_get(task_id)
    if not task:
        return False
    for dep_id in task.get("blocked_by", []):
        dep = task_get(dep_id)
        if dep is None or dep.get("status") != "completed":
            return False
    return True


def claim_task(task_id: str, owner: str = "agent") -> str:
    row = task_get(task_id)
    if row is None:
        return f"Task {task_id} not found"
    if row["status"] != "pending":
        return f"Task {task_id} is {row['status']}, cannot claim"
    if row.get("owner"):
        return f"Task {task_id} already owned by {row['owner']}"
    if not can_start(task_id):
        deps = [d for d in row.get("blocked_by", [])
                if task_get(d) and task_get(d).get("status") != "completed"]
        missing = [d for d in row.get("blocked_by", []) if not task_get(d)]
        parts = []
        if deps: parts.append(f"blocked by: {deps}")
        if missing: parts.append(f"missing deps: {missing}")
        return "Cannot start — " + ", ".join(parts)
    task_update(task_id, owner=owner, status="in_progress")
    print(f"  \033[36m[claim] {row['subject']} -> in_progress\033[0m")
    return f"Claimed {task_id} ({row['subject']})"


def complete_task(task_id: str) -> str:
    row = task_get(task_id)
    if row is None:
        return f"Task {task_id} not found"
    if row["status"] != "in_progress":
        return f"Task {task_id} is {row['status']}, cannot complete"
    task_update(task_id, status="completed")
    tasks = task_list()
    unblocked = [t["subject"] for t in tasks
                 if t["status"] == "pending" and t.get("blocked_by")
                 and task_get(t["id"]) and can_start(t["id"])]
    print(f"  \033[32m[complete] {row['subject']} OK\033[0m")
    msg = f"Completed {task_id} ({row['subject']})"
    if unblocked:
        msg += f"\nUnblocked: {', '.join(unblocked)}"
    return msg


def run_todo_write(todos: list) -> str:
    global CURRENT_TODOS
    for i, todo in enumerate(todos):
        if "content" not in todo or "status" not in todo:
            return f"Error: todos[{i}] missing 'content' or 'status'"
        if todo["status"] not in ("pending", "in_progress", "completed"):
            return f"Error: todos[{i}] has invalid status '{todo['status']}'"
    CURRENT_TODOS = todos
    print(f"  \033[33m[todo] updated {len(CURRENT_TODOS)} item(s)\033[0m")
    return f"Updated {len(CURRENT_TODOS)} todos"
