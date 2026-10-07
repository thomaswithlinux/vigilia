"""Stockage SQLite : historique des evenements, alertes, mesures, appareils, configurations, notes, audit."""
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, t REAL, sev TEXT, sw TEXT, text TEXT, kind TEXT, port TEXT, ip TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS alert_hist(id INTEGER PRIMARY KEY, key TEXT, sw TEXT, ip TEXT, title TEXT, sev TEXT, kind TEXT, port TEXT, opened REAL, closed REAL);
CREATE TABLE IF NOT EXISTS metrics(t REAL, ip TEXT, cpu REAL, mem REAL, temp REAL, tin REAL, tout REAL);
CREATE INDEX IF NOT EXISTS ix_metrics ON metrics(ip, t);
CREATE TABLE IF NOT EXISTS port_events(t REAL, ip TEXT, port TEXT, kind TEXT);
CREATE INDEX IF NOT EXISTS ix_pe ON port_events(t);
CREATE TABLE IF NOT EXISTS macs(mac TEXT PRIMARY KEY, vlan INTEGER, ip TEXT, port TEXT, first_seen REAL, last_seen REAL, moves INTEGER);
CREATE TABLE IF NOT EXISTS inventory(ip TEXT PRIMARY KEY, json TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS configs(id INTEGER PRIMARY KEY, ip TEXT, name TEXT, t REAL, sha TEXT, path TEXT, size INTEGER);
CREATE INDEX IF NOT EXISTS ix_cfg ON configs(ip, id);
CREATE TABLE IF NOT EXISTS notes(key TEXT PRIMARY KEY, text TEXT, updated REAL, by TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, t REAL, user TEXT, action TEXT, detail TEXT, ip TEXT);
"""

RETENTION = {"metrics": 35 * 86400, "events": 180 * 86400, "port_events": 180 * 86400, "audit": 365 * 86400}


class Db:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.c = sqlite3.connect(str(path), check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        with self.lock:
            self.c.execute("PRAGMA journal_mode=WAL")
            self.c.executescript(SCHEMA)
            cols = {r[1] for r in self.c.execute("PRAGMA table_info(events)")}
            for col in ("kind", "port", "ip", "detail"):  # migration des anciennes bases
                if col not in cols:
                    self.c.execute(f"ALTER TABLE events ADD COLUMN {col} TEXT")
            self.c.execute("CREATE INDEX IF NOT EXISTS ix_events_t ON events(t)")
            self.c.commit()
        self.prune()

    def execute(self, sql, args=()):
        with self.lock:
            cur = self.c.execute(sql, args)
            self.c.commit()
            return cur.lastrowid

    def query(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.c.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.query(sql, args)
        return rows[0] if rows else None

    def prune(self):
        now = time.time()
        for table, ttl in RETENTION.items():
            col = "t"
            self.execute(f"DELETE FROM {table} WHERE {col} < ?", (now - ttl,))

    # ---- raccourcis
    def audit(self, user, action, detail="", ip=""):
        self.execute("INSERT INTO audit(t,user,action,detail,ip) VALUES(?,?,?,?,?)", (time.time(), user, action, detail[:300], ip))
