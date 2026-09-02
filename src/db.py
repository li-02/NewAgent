"""SQLite：记录已见条目，用于跨天去重"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    url_hash   TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    title      TEXT,
    first_seen TEXT NOT NULL
);
"""


class DB:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def known_hashes(self, hashes: list[str]) -> set[str]:
        if not hashes:
            return set()
        marks = ",".join("?" * len(hashes))
        rows = self.conn.execute(
            f"SELECT url_hash FROM seen WHERE url_hash IN ({marks})", hashes
        )
        return {r[0] for r in rows}

    def add_seen(self, url_hash: str, url: str, title: str, now: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen VALUES (?, ?, ?, ?)",
            (url_hash, url, title, now),
        )

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
