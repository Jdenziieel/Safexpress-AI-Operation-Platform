"""Quick offline smoke test for migrate_sqlite_to_dynamodb.py.

Builds tiny temp `threads.db` + `logs.db` files with the supervisor schema,
then dry-runs the migration script and asserts the row counts.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    tmp = Path(tempfile.gettempdir()) / "phase7_smoke"
    tmp.mkdir(exist_ok=True)
    threads_db = tmp / "threads.db"
    logs_db = tmp / "logs.db"
    for f in (threads_db, logs_db):
        if f.exists():
            f.unlink()

    # ------------ threads.db ------------
    c = sqlite3.connect(str(threads_db))
    cu = c.cursor()
    cu.execute(
        """CREATE TABLE threads (
            thread_id TEXT PRIMARY KEY, user_id TEXT, created_at TEXT,
            updated_at TEXT, title TEXT, message_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active', last_message_preview TEXT, tags TEXT
        )"""
    )
    cu.execute(
        "CREATE TABLE thread_states (thread_id TEXT PRIMARY KEY, conversation_state TEXT)"
    )
    cu.execute(
        "CREATE TABLE memory_states (thread_id TEXT PRIMARY KEY, memory_state TEXT)"
    )
    cu.execute(
        """CREATE TABLE messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT,
            role TEXT, content TEXT, created_at TEXT,
            file_name TEXT, file_type TEXT, file_size INTEGER
        )"""
    )
    cu.execute(
        """CREATE TABLE conversation_states (
            conversation_id TEXT PRIMARY KEY, state_json TEXT, updated_at TEXT
        )"""
    )
    cu.execute(
        "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)",
        ("t1", "u1", "2026-01-01", "2026-01-01", "first", 2, "active", "hi", json.dumps(["a"])),
    )
    cu.execute(
        "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)",
        ("t2", "u1", "2026-01-02", "2026-01-02", "second", 0, "archived", None, None),
    )
    cu.execute("INSERT INTO thread_states VALUES (?,?)", ("t1", json.dumps({"x": 1})))
    cu.execute("INSERT INTO memory_states VALUES (?,?)", ("t1", json.dumps({"sum": None})))
    cu.execute(
        "INSERT INTO messages (thread_id,role,content,created_at) VALUES (?,?,?,?)",
        ("t1", "user", "hi", "2026-01-01"),
    )
    cu.execute(
        "INSERT INTO messages (thread_id,role,content,created_at) VALUES (?,?,?,?)",
        ("t1", "assistant", "hello", "2026-01-01"),
    )
    cu.execute(
        "INSERT INTO conversation_states VALUES (?,?,?)", ("c1", "{}", "2026-01-01")
    )
    c.commit()
    c.close()

    # ------------ logs.db ------------
    c = sqlite3.connect(str(logs_db))
    cu = c.cursor()
    cu.execute(
        """CREATE TABLE logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, level TEXT,
            logger TEXT, message TEXT, request_id TEXT, conversation_id TEXT,
            thread_id TEXT, component TEXT, operation TEXT, data TEXT
        )"""
    )
    cu.execute(
        """CREATE TABLE llm_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, request_id TEXT,
            conversation_id TEXT, user_id TEXT, service TEXT, model TEXT,
            tier TEXT, operation TEXT, input_tokens INTEGER, output_tokens INTEGER,
            total_tokens INTEGER, estimated_cost_usd REAL, duration_ms REAL,
            success INTEGER, prompt_summary TEXT, error TEXT,
            cumulative_tokens INTEGER, cumulative_cost_usd REAL,
            cached_tokens INTEGER DEFAULT 0
        )"""
    )
    cu.execute(
        """CREATE TABLE agent_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, request_id TEXT,
            conversation_id TEXT, agent_name TEXT, tool_name TEXT,
            step_number INTEGER, total_steps INTEGER, inputs TEXT,
            success INTEGER, duration_ms REAL, output_summary TEXT, error TEXT
        )"""
    )
    cu.execute(
        """CREATE TABLE request_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE,
            conversation_id TEXT, thread_id TEXT, started_at TEXT, completed_at TEXT,
            total_duration_ms REAL, total_input_tokens INTEGER,
            total_output_tokens INTEGER, total_tokens INTEGER, total_cost_usd REAL,
            llm_call_count INTEGER, agent_call_count INTEGER, success INTEGER, error TEXT
        )"""
    )
    cu.execute(
        "INSERT INTO logs (timestamp,level,logger,message,request_id,conversation_id,thread_id,component,operation,data) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("2026-01-01", "INFO", "test", "hello", "r1", "c1", "t1", "ws", "startup", None),
    )
    cu.execute(
        "INSERT INTO llm_calls (timestamp,request_id,conversation_id,user_id,service,model,tier,operation,input_tokens,output_tokens,total_tokens,estimated_cost_usd,duration_ms,success,prompt_summary,error,cumulative_tokens,cumulative_cost_usd,cached_tokens) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("2026-01-01", "r1", "c1", "u1", "supervisor", "gpt-4o-mini", "planner", "plan",
         100, 50, 150, 0.0001, 420.0, 1, "p", "", 150, 0.0001, 0),
    )
    cu.execute(
        "INSERT INTO agent_calls (timestamp,request_id,conversation_id,agent_name,tool_name,step_number,total_steps,inputs,success,duration_ms,output_summary,error) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("2026-01-01", "r1", "c1", "calendar_agent", "list_events", 1, 3, "{}", 1, 200.0, "ok", None),
    )
    cu.execute(
        "INSERT INTO request_summaries (request_id,conversation_id,thread_id,started_at,completed_at,total_duration_ms,total_input_tokens,total_output_tokens,total_tokens,total_cost_usd,llm_call_count,agent_call_count,success,error) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("r1", "c1", "t1", "2026-01-01", "2026-01-01", 1500.0, 100, 50, 150, 0.0001, 1, 3, 1, None),
    )
    c.commit()
    c.close()

    print(f"  built threads.db rows ({threads_db.stat().st_size} bytes)")
    print(f"  built logs.db rows    ({logs_db.stat().st_size} bytes)")

    script = Path(__file__).resolve().parent / "migrate_sqlite_to_dynamodb.py"
    rc = subprocess.call(
        [
            sys.executable,
            str(script),
            "--dry-run",
            "--threads-db", str(threads_db),
            "--logs-db", str(logs_db),
        ]
    )
    if rc != 0:
        print(f"\n  smoke FAILED: migrate exited {rc}")
        return rc

    # Cleanup
    threads_db.unlink()
    logs_db.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
