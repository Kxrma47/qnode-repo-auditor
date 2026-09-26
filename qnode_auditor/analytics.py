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
        connection.execute(
            "CREATE TABLE IF NOT EXISTS daily_scans ("
            "day TEXT NOT NULL, kind TEXT NOT NULL, scans INTEGER NOT NULL, "
            "PRIMARY KEY(day, kind))"
        )
        return connection

    def record_scan(self, kind: str, *, now: datetime | None = None) -> None:
        if kind not in {"repository", "pull_request"}:
            raise ValueError("invalid scan kind")
        now = now or datetime.now(UTC)
        with closing(self._connection()) as connection, connection:
            connection.execute(
                "INSERT INTO daily_scans(day, kind, scans) VALUES (?, ?, 1) "
                "ON CONFLICT(day, kind) DO UPDATE SET scans=scans+1",
                (now.date().isoformat(), kind),
            )

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
            scan_rows = connection.execute(
                "SELECT kind, SUM(scans) FROM daily_scans GROUP BY kind"
            ).fetchall()
        scans = dict(scan_rows)
        return {
            "unique_browsers": unique_browsers,
            "recent_browsers": recent_browsers or 0,
            "page_views": page_views,
            "since": first_seen,
            "repository_scans": scans.get("repository", 0),
            "pull_request_scans": scans.get("pull_request", 0),
        }
