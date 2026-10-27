"""sqlite dedupe. One table, one job: never send the same id twice."""

from __future__ import annotations

import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    id        TEXT PRIMARY KEY,
    first_seen REAL NOT NULL,
    sent_at   REAL
);
"""


class Store:
    def __init__(self, path: str = "alertbot.sqlite", ttl_days: float = 30.0):
        self.path = path
        self.ttl_seconds = ttl_days * 86400.0
        directory = os.path.dirname(os.path.abspath(path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def seen(self, item_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM seen WHERE id = ?", (item_id,)).fetchone()
        return row is not None

    def mark(self, item_id: str, sent: bool = False) -> None:
        now = time.time()
        self.conn.execute(
            "INSERT INTO seen (id, first_seen, sent_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET sent_at = COALESCE(excluded.sent_at, sent_at)",
            (item_id, now, now if sent else None),
        )
        self.conn.commit()

    def prune(self, now: float = None) -> int:
        now = time.time() if now is None else now
        cutoff = now - self.ttl_seconds
        cur = self.conn.execute("DELETE FROM seen WHERE first_seen < ?", (cutoff,))
        self.conn.commit()
        return cur.rowcount

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
