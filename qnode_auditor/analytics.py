"""Small, optional SQLite store for private aggregate website usage."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta


class VisitorStore:
    def __init__(self, path: str):
        if not path.startswith("/"):
            raise ValueError("VISITOR_METRICS_DB must be an absolute SQLite file path")
        self.path = path

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS visitors ("
            "visitor_hash TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS daily_views ("
            "day TEXT PRIMARY KEY, page_views INTEGER NOT NULL)"
        )
        return connection

    def record(self, browser_token: str, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        timestamp = now.isoformat()
        visitor_hash = hashlib.sha256(browser_token.encode("ascii")).hexdigest()
        with closing(self._connection()) as connection, connection:
            connection.execute(
                "INSERT INTO visitors(visitor_hash, first_seen, last_seen) VALUES (?, ?, ?) "
                "ON CONFLICT(visitor_hash) DO UPDATE SET last_seen=excluded.last_seen",
                (visitor_hash, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO daily_views(day, page_views) VALUES (?, 1) "
                "ON CONFLICT(day) DO UPDATE SET page_views=page_views+1",
                (now.date().isoformat(),),
            )

    def snapshot(self, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        cutoff = (now - timedelta(days=30)).isoformat()
        with closing(self._connection()) as connection:
            unique_browsers, recent_browsers, first_seen = connection.execute(
                "SELECT COUNT(*), SUM(last_seen >= ?), MIN(first_seen) FROM visitors", (cutoff,)
            ).fetchone()
            page_views = connection.execute(
                "SELECT COALESCE(SUM(page_views), 0) FROM daily_views"
            ).fetchone()[0]
        return {
            "unique_browsers": unique_browsers,
            "recent_browsers": recent_browsers or 0,
            "page_views": page_views,
            "since": first_seen,
        }
