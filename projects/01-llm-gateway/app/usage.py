"""SQLite Trace / Usage / Cost 记录。"""

import sqlite3
from pathlib import Path


class UsageStore:
    def __init__(self, path: str | Path = "gateway_usage.sqlite3"):
        self.path = str(path)
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS calls (
                    trace_id TEXT PRIMARY KEY,
                    requested_model TEXT NOT NULL,
                    resolved_model TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    total_tokens INTEGER,
                    cost REAL,
                    latency_ms REAL NOT NULL,
                    attempts INTEGER NOT NULL,
                    fallback_used INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_code TEXT
                )
            """)

    def _connect(self):
        return sqlite3.connect(self.path)

    def record(self, result, *, status="completed", error_code=None):
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.trace_id,
                    result.requested_model,
                    result.resolved_model,
                    result.provider,
                    result.usage.prompt_tokens,
                    result.usage.completion_tokens,
                    result.usage.total_tokens,
                    None,
                    result.latency_ms,
                    result.attempts,
                    int(result.fallback_used),
                    status,
                    error_code,
                ),
            )

    def recent(self, limit=50):
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute("SELECT * FROM calls ORDER BY rowid DESC LIMIT ?", (limit,))]
