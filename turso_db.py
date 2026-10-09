#!/usr/bin/env python3
"""
Turso database adapter for the Farah Gold AI Org Hub.
Provides a sqlite3-compatible interface backed by Turso's HTTP API.
Uses TURSO_URL and TURSO_AUTH_TOKEN env vars; falls back to local SQLite.
"""
import json
import os
import sqlite3
import urllib.request
import urllib.error


class TursoRow:
    """Dict-like row to mimic sqlite3.Row."""
    def __init__(self, cols, values):
        self._cols = cols
        self._values = values
        self._map = dict(zip(cols, values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def __iter__(self):
        return iter(self._values)

    def keys(self):
        return self._cols

    def __len__(self):
        return len(self._values)


class TursoCursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows = []
        self._cols = []
        self._pos = 0
        self.lastrowid = None

    def execute(self, sql, params=()):
        # Convert ? placeholders — Turso HTTP API uses ? too
        result = self._conn._execute(sql, params)
        raw_cols = result.get("cols", [])
        self._cols = [c.get("name") if isinstance(c, dict) else c for c in raw_cols]
        raw_rows = result.get("rows", [])
        self._rows = [
            TursoRow(self._cols, [self._convert_val(v) for v in row])
            for row in raw_rows
        ]
        self._pos = 0
        self.lastrowid = result.get("last_insert_rowid")
        return self

    def _convert_val(self, v):
        if v is None:
            return None
        t = v.get("type")
        val = v.get("value")
        if t == "integer":
            return int(val)
        if t == "float":
            return float(val)
        if t == "null":
            return None
        return val  # text, blob

    def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows

    def fetchone(self):
        if self._pos < len(self._rows):
            row = self._rows[self._pos]
            self._pos += 1
            return row
        return None

    def __iter__(self):
        return iter(self.fetchall())


class TursoConnection:
    """sqlite3-compatible connection backed by Turso HTTP API."""
    def __init__(self, url, auth_token):
        self._url = url.rstrip("/") + "/v2/pipeline"
        self._token = auth_token
        self.row_factory = None

    def _execute(self, sql, params=()):
        # Build the Hrana pipeline request
        stmt = {"sql": sql}
        if params:
            stmt["args"] = [{"type": "text", "value": str(p)} if not isinstance(p, (int, float)) else
                           {"type": "integer" if isinstance(p, int) else "float", "value": str(p)}
                           for p in params]
        # Handle None params
        if params:
            args = []
            for p in params:
                if p is None:
                    args.append({"type": "null"})
                elif isinstance(p, int):
                    args.append({"type": "integer", "value": str(p)})
                elif isinstance(p, float):
                    args.append({"type": "float", "value": str(p)})
                else:
                    args.append({"type": "text", "value": str(p)})
            stmt["args"] = args

        payload = {
            "requests": [
                {"type": "execute", "stmt": stmt},
            ]
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self._url,
            data=data,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:500]
            raise RuntimeError(f"Turso HTTP {e.code}: {body}")

        results = result.get("results", [])
        if not results:
            raise RuntimeError(f"Turso empty response: {json.dumps(result)[:300]}")
        first = results[0]
        if first.get("type") == "error":
            raise RuntimeError(f"Turso error: {json.dumps(first)[:500]}")
        return first["response"]["result"]

    def execute(self, sql, params=()):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def cursor(self):
        c = TursoCursor(self)
        return c

    def commit(self):
        pass  # Turso HTTP API auto-commits each statement

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def get_connection(db_path=None):
    """Return a Turso connection if env vars are set, else local SQLite."""
    turso_url = os.environ.get("TURSO_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")
    if turso_url and turso_token:
        # Normalize URL: Turso dashboard shows libsql://, HTTP API needs https://
        if turso_url.startswith("libsql://"):
            turso_url = "https://" + turso_url[len("libsql://"):]
        return TursoConnection(turso_url, turso_token)
    # Fallback to local SQLite
    if db_path is None:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "org.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
