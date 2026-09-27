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

    def recent_titles(self, since: str, until: str | None = None) -> list[str]:
        """返回 first_seen 落在 [since, until) 内的已收录标题，供跨天标题判重使用。

        since/until 用 ISO 字符串比较即可：add_seen 写入的是
        datetime.isoformat(timespec="seconds")，同格式下字典序等于时间序。

        until 用来排除「今天」：同一天可能重跑多次，若不排除，本次运行刚写入
        的条目会在下一次运行时把自身判为重复（表现为「38 条窗口内条目 → 只剩
        1 条候选」），越重跑稿子越少。跨天判重只应比较「今天之前」的标题。
        """
        if until:
            rows = self.conn.execute(
                "SELECT title FROM seen WHERE first_seen >= ? AND first_seen < ?"
                " AND title IS NOT NULL AND title != ''",
                (since, until),
            )
        else:
            rows = self.conn.execute(
                "SELECT title FROM seen WHERE first_seen >= ? AND title IS NOT NULL AND title != ''",
                (since,),
            )
        return [r[0] for r in rows]

    def add_seen(self, url_hash: str, url: str, title: str, now: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen VALUES (?, ?, ?, ?)",
            (url_hash, url, title, now),
        )

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
