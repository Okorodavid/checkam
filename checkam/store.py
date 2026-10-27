"""SQLite: shared scam reports, cached domain ages, live regulator notices, and check counts.

Privacy for a public bot: users are stored only as salted hashes, and message text is never stored.
Only the things scammers reuse (account numbers, phones, domains, handles) are kept, so one
person's report can warn the next.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (ts REAL, platform TEXT, user TEXT, kind TEXT, value TEXT, verdict TEXT);
CREATE INDEX IF NOT EXISTS reports_value ON reports(kind, value);
CREATE TABLE IF NOT EXISTS checks (ts REAL, platform TEXT, verdict TEXT, reasoner TEXT);
CREATE TABLE IF NOT EXISTS rdap (domain TEXT PRIMARY KEY, created TEXT, fetched REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS notices USING fts5(title, body, url UNINDEXED, regulator UNINDEXED, fetched UNINDEXED);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS warned (alias TEXT, name TEXT, title TEXT, url TEXT, regulator TEXT);
CREATE TABLE IF NOT EXISTS threats (host TEXT, url TEXT, source TEXT);
CREATE INDEX IF NOT EXISTS threats_host ON threats(host);
"""


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.salt = self._salt()

    def _salt(self) -> str:
        row = self.db.execute("SELECT value FROM meta WHERE key='salt'").fetchone()
        if row:
            return row[0]
        salt = hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:16]
        with self.lock, self.db:
            self.db.execute("INSERT INTO meta VALUES ('salt', ?)", (salt,))
        return salt

    def user_key(self, platform: str, user_id: object) -> str:
        return hashlib.sha256(f"{self.salt}:{platform}:{user_id}".encode()).hexdigest()[:20]

    # ---------------------------------------------------------------- reports

    def record(self, platform: str, user: str, lookups: list[tuple[str, str]], verdict: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self.lock, self.db:
            self.db.executemany("INSERT INTO reports VALUES (?,?,?,?,?,?)",
                                [(now, platform, user, k, v, verdict) for k, v in lookups])
            self.db.execute("INSERT INTO checks VALUES (?,?,?,?)", (now, platform, verdict, ""))

    def others_reporting(self, kind: str, value: str, user: str, since: float) -> int:
        """How many OTHER people sent this value since `since`."""
        row = self.db.execute(
            "SELECT COUNT(DISTINCT user) FROM reports WHERE kind=? AND value=? AND user<>? AND ts>=?",
            (kind, value, user, since)).fetchone()
        return int(row[0] or 0)

    def checks_since(self, since: float) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM checks WHERE ts>=?", (since,)).fetchone()[0])

    def stats(self, since: float) -> dict[str, int]:
        rows = self.db.execute("SELECT verdict, COUNT(*) FROM checks WHERE ts>=? GROUP BY verdict", (since,)).fetchall()
        return {v: n for v, n in rows}

    # ---------------------------------------------------------------- domain ages

    def rdap_get(self, domain: str, max_age: float = 7 * 86400) -> str | None:
        row = self.db.execute("SELECT created, fetched FROM rdap WHERE domain=?", (domain,)).fetchone()
        if row and time.time() - row[1] < max_age:
            return row[0]
        return None

    def rdap_put(self, domain: str, created: str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO rdap VALUES (?,?,?)", (domain, created, time.time()))

    # ---------------------------------------------------------------- regulator notices

    def put_notice(self, title: str, body: str, url: str, regulator: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM notices WHERE url=?", (url,))
            self.db.execute("INSERT INTO notices VALUES (?,?,?,?,?)", (title, body, url, regulator, time.time()))

    def search_notices(self, phrase: str, limit: int = 3) -> list[tuple[str, str, str, str]]:
        """Notices containing the exact phrase: (title, snippet, url, regulator)."""
        q = '"' + phrase.replace('"', " ").strip() + '"'
        try:
            return self.db.execute(
                "SELECT title, snippet(notices, 1, '', '', '…', 18), url, regulator FROM notices "
                "WHERE notices MATCH ? ORDER BY rank LIMIT ?", (q, limit)).fetchall()
        except sqlite3.OperationalError:
            return []

    def replace_warned(self, regulator: str, rows: list[tuple[str, str, str, str]]) -> None:
        """rows: (alias, name, title, url) for operators a regulator named in a warning."""
        with self.lock, self.db:
            self.db.execute("DELETE FROM warned WHERE regulator=?", (regulator,))
            self.db.executemany("INSERT INTO warned VALUES (?,?,?,?,?)", [(*r, regulator) for r in rows])

    def warned_aliases(self) -> list[tuple[str, str, str, str, str]]:
        return self.db.execute("SELECT alias, name, title, url, regulator FROM warned").fetchall()

    def notice_count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM notices").fetchone()[0])

    # ---------------------------------------------------------------- known-bad links (blocklists)

    def replace_threats(self, source: str, rows: list[tuple[str, str]]) -> None:
        """rows: (host, url) pairs. url may be '' for host-only lists."""
        with self.lock, self.db:
            self.db.execute("DELETE FROM threats WHERE source=?", (source,))
            self.db.executemany("INSERT INTO threats VALUES (?,?,?)", [(h, u, source) for h, u in rows])
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (f"threats:{source}", str(time.time())))

    def threat_hits(self, host: str, url: str) -> list[str]:
        """Blocklists that list this exact URL, or the whole host (host-only entries)."""
        rows = self.db.execute(
            "SELECT DISTINCT source FROM threats WHERE host=? AND (url='' OR url=? OR url=? OR url=?)",
            (host, url, url.rstrip("/"), url.rstrip("/") + "/")).fetchall()
        return [r[0] for r in rows]

    def threat_updated(self, source: str) -> float | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (f"threats:{source}",)).fetchone()
        return float(row[0]) if row else None

    def threat_count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM threats").fetchone()[0])
