"""Shared SQLite database with WAL mode for concurrent access.

Replaces scattered JSON files with a single agent.db at AGENT_HOME.
All writes are serialized through a threading lock.
"""

import json, sqlite3, threading
from pathlib import Path

from ..config import AGENT_HOME

DB_PATH = AGENT_HOME / "agent.db"
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _init():
    """Create tables if they don't exist."""
    with _lock:
        conn = _connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id           TEXT PRIMARY KEY,
                subject      TEXT NOT NULL,
                description  TEXT DEFAULT '',
                status       TEXT DEFAULT 'pending',
                owner        TEXT,
                blocked_by   TEXT DEFAULT '[]',
                worktree     TEXT,
                created_at   REAL,
                updated_at   REAL
            );
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id        TEXT PRIMARY KEY,
                cron_expr TEXT NOT NULL,
                prompt    TEXT NOT NULL,
                recurring INTEGER DEFAULT 1,
                durable   INTEGER DEFAULT 1,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                from_agent TEXT NOT NULL,
                to_agent   TEXT NOT NULL,
                content    TEXT NOT NULL,
                msg_type   TEXT DEFAULT 'message',
                metadata   TEXT DEFAULT '{}',
                ts         REAL,
                consumed   INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_messages_to ON messages(to_agent, consumed);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        """)
        conn.commit()
        conn.close()


# ── Task operations ──

def task_create(subject: str, description: str = "",
                blocked_by: list[str] | None = None) -> dict:
    import time, random
    tid = f"task_{int(time.time())}_{random.randint(0, 9999):04d}"
    now = time.time()
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO tasks (id, subject, description, blocked_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tid, subject, description, json.dumps(blocked_by or []), now, now),
        )
        conn.commit()
        conn.close()
    return task_get(tid)


def task_get(task_id: str) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_dict(row)


def task_list(status: str | None = None) -> list[dict]:
    conn = _connect()
    if status:
        rows = conn.execute("SELECT * FROM tasks WHERE status = ? ORDER BY id", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def task_update(task_id: str, **fields) -> dict | None:
    import time
    if not fields:
        return task_get(task_id)
    if "blocked_by" in fields and isinstance(fields["blocked_by"], list):
        fields["blocked_by"] = json.dumps(fields["blocked_by"])
    fields["updated_at"] = time.time()
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    with _lock:
        conn = _connect()
        conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?", values)
        conn.commit()
        conn.close()
    return task_get(task_id)


def task_delete(task_id: str):
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        conn.close()


def _row_to_dict(row) -> dict:
    d = dict(row)
    if "blocked_by" in d and isinstance(d["blocked_by"], str):
        d["blocked_by"] = json.loads(d["blocked_by"])
    if "metadata" in d and isinstance(d["metadata"], str):
        d["metadata"] = json.loads(d["metadata"])
    return d


# ── Cron operations ──

def cron_list() -> list[dict]:
    conn = _connect()
    rows = conn.execute("SELECT * FROM cron_jobs ORDER BY id").fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def cron_add(job_id: str, cron_expr: str, prompt: str,
             recurring: bool = True, durable: bool = True):
    import time
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT OR REPLACE INTO cron_jobs (id, cron_expr, prompt, recurring, durable, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, cron_expr, prompt, int(recurring), int(durable), time.time()),
        )
        conn.commit()
        conn.close()


def cron_remove(job_id: str):
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()


# ── Message operations ──

def msg_send(from_agent: str, to_agent: str, content: str,
             msg_type: str = "message", metadata: dict | None = None):
    import time
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO messages (from_agent, to_agent, content, msg_type, metadata, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (from_agent, to_agent, content, msg_type,
             json.dumps(metadata or {}), time.time()),
        )
        conn.commit()
        conn.close()


def msg_read(agent: str) -> list[dict]:
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM messages WHERE to_agent = ? AND consumed = 0 ORDER BY id",
            (agent,),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE messages SET consumed = 1 WHERE id IN ({placeholders})",
                ids,
            )
            conn.commit()
        conn.close()
    return [_row_to_dict(r) for r in rows]


# Initialize on first import
_init()
