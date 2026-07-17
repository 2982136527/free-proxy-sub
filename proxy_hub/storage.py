"""SQLite storage for proxy sources and nodes."""
import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Dict


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "proxy_hub.db"


class Storage:
    _cache: dict[str, sqlite3.Connection] = {}

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(DB_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self):
        # Share one connection per db_path (important for :memory:)
        if self.db_path not in self._cache:
            if self.db_path == ":memory:":
                c = sqlite3.connect(self.db_path)
            else:
                c = sqlite3.connect(self.db_path, timeout=10)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=5000")
            self._cache[self.db_path] = c
            # Create tables on first connection
            self._create_tables(c)
        return self._cache[self.db_path]

    def _create_tables(self, c):
        c.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                url         TEXT    UNIQUE NOT NULL,
                source_type TEXT    DEFAULT 'github',
                source_repo TEXT,
                fmt         TEXT,
                added_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                last_fetched TEXT,
                error_count INTEGER DEFAULT 0,
                last_error  TEXT,
                is_active   INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS proxies (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id    INTEGER REFERENCES sources(id),
                proxy_type   TEXT    NOT NULL,
                name         TEXT,
                host         TEXT    NOT NULL,
                port         INTEGER NOT NULL,
                cipher       TEXT,
                uuid         TEXT,
                password     TEXT,
                plugin       TEXT,
                plugin_opts  TEXT,
                raw_link     TEXT,
                is_alive     INTEGER DEFAULT 0,
                latency_ms   REAL,
                last_checked TEXT,
                added_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                dead_count   INTEGER DEFAULT 0,
                extra        TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pr_host_port ON proxies(host, port);
            CREATE INDEX IF NOT EXISTS idx_pr_alive   ON proxies(is_alive);
            CREATE INDEX IF NOT EXISTS idx_src_url    ON sources(url);
        """)

    def _init_db(self):
        """Ensure tables exist."""
        self._conn()

    # ── sources ──────────────────────────────────────────────

    def add_source(self, url: str, source_type="github",
                   source_repo=None, fmt=None) -> bool:
        try:
            c = self._conn()
            c.execute(
                "INSERT OR IGNORE INTO sources(url,source_type,source_repo,fmt) VALUES(?,?,?,?)",
                (url, source_type, source_repo, fmt))
            return True
        except Exception:
            return False

    def get_sources(self, active_only=True) -> List[Dict]:
        c = self._conn()
        if active_only:
            rows = c.execute(
                "SELECT * FROM sources WHERE is_active=1").fetchall()
        else:
            rows = c.execute("SELECT * FROM sources").fetchall()
        return [dict(r) for r in rows]

    def mark_source_ok(self, url: str):
        c = self._conn()
        c.execute(
            "UPDATE sources SET error_count=0, last_fetched=datetime('now') WHERE url=?",
            (url,))

    def mark_source_err(self, url: str, error: str):
        c = self._conn()
        c.execute(
            "UPDATE sources SET error_count=error_count+1, last_error=?, last_fetched=datetime('now') WHERE url=?",
            (error, url))

    # ── proxies ──────────────────────────────────────────────

    def add_proxy(self, p: dict) -> bool:
        try:
            c = self._conn()
            existing = c.execute(
                "SELECT id FROM proxies WHERE host=? AND port=? AND proxy_type=?",
                (p["host"], p["port"], p["proxy_type"])).fetchone()
            if existing:
                c.execute(
                    """UPDATE proxies SET source_id=?,name=?,cipher=?,uuid=?,
                       password=?,raw_link=?,extra=? WHERE id=?""",
                    (p.get("source_id"), p.get("name"), p.get("cipher"),
                     p.get("uuid"), p.get("password"), p.get("raw_link"),
                     json.dumps(p.get("extra", {})), existing["id"]))
            else:
                c.execute(
                    """INSERT INTO proxies
                       (source_id,proxy_type,name,host,port,cipher,uuid,
                        password,plugin,plugin_opts,raw_link,extra)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (p.get("source_id"), p["proxy_type"], p.get("name"),
                     p["host"], p["port"], p.get("cipher"), p.get("uuid"),
                     p.get("password"), p.get("plugin"),
                     p.get("plugin_opts"), p.get("raw_link"),
                     json.dumps(p.get("extra", {}))))
            return True
        except Exception:
            return False

    def get_proxies_for_validation(self, limit=150) -> List[Dict]:
        c = self._conn()
        rows = c.execute(
            """SELECT * FROM proxies
               WHERE last_checked IS NULL
                  OR datetime('now','-5 minutes')>last_checked
               ORDER BY last_checked ASC NULLS FIRST LIMIT ?""",
            (limit,)).fetchall()
        return [dict(r) for r in rows]

    def update_proxy_status(self, pid: int, alive: bool,
                            latency: float | None = None):
        c = self._conn()
        if alive:
            c.execute(
                """UPDATE proxies SET is_alive=1,latency_ms=?,
                   last_checked=datetime('now'),dead_count=0 WHERE id=?""",
                (latency, pid))
        else:
            c.execute(
                """UPDATE proxies SET is_alive=0,latency_ms=NULL,
                   last_checked=datetime('now'),dead_count=dead_count+1 WHERE id=?""",
                (pid,))

    def get_alive_proxies(self, limit=200) -> List[Dict]:
        c = self._conn()
        rows = c.execute(
            "SELECT * FROM proxies WHERE is_alive=1 ORDER BY latency_ms ASC NULLS LAST LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]

    def cleanup_dead(self, max_dead=3):
        c = self._conn()
        c.execute("DELETE FROM proxies WHERE dead_count>=?", (max_dead,))
        c.execute("DELETE FROM sources WHERE error_count>=5")

    def stats(self) -> dict:
        c = self._conn()
        total = c.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
        alive = c.execute(
            "SELECT COUNT(*) FROM proxies WHERE is_alive=1").fetchone()[0]
        src = c.execute(
            "SELECT COUNT(*) FROM sources WHERE is_active=1").fetchone()[0]
        return {"total": total, "alive": alive, "sources": src}
