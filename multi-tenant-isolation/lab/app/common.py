"""Shared plumbing for the two copies of the timesheet service.

Everything that is not the isolation decision lives here, so that the diff
between vulnerable.py and fixed.py is only the isolation decision.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg

DB_CONNECT_RETRY_SECONDS = 30
DB_RETRY_INTERVAL_SECONDS = 0.5
# Both tenants start at once and, in the shared-database stacks, run this
# setup against the same server. CREATE TABLE IF NOT EXISTS is not atomic
# against a concurrent CREATE - the loser gets a unique violation on the
# type name - and two callers can both see an empty table and both seed it.
# One advisory lock covers both races.
SETUP_LOCK_KEY = 8_675_309

TENANT_ID = os.environ["TENANT_ID"]
SESSION_SECRET = os.environ["SESSION_SECRET"].encode()
DATABASE_URL = os.environ["DATABASE_URL"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id        SERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    worker    TEXT NOT NULL,
    hours     NUMERIC NOT NULL,
    note      TEXT NOT NULL
);
"""

# Both tenants are seeded into whichever database they are pointed at. In the
# shared-database stacks that puts all six rows in one table, which is the whole
# point: the id space is global, so id 4 is reachable from tenant-a's session
# unless something stops it.
SEED = {
    "tenant-a": [("A. Nowak", 7.5, "Foundations, plot 12"),
                 ("A. Nowak", 8.0, "Formwork, plot 12"),
                 ("J. Kowalski", 6.0, "Rebar delivery")],
    "tenant-b": [("M. Dubois", 8.0, "Roofing, site 3"),
                 ("M. Dubois", 4.5, "Safety briefing"),
                 ("L. Bernard", 7.0, "Scaffolding strike")],
}


def connect() -> psycopg.Connection:
    """Open a connection, waiting for Postgres to accept them.

    Compose starts the database and the app together; without the wait the app
    exits before Postgres has finished its first-boot initialisation and the
    stack looks broken for a reason that has nothing to do with isolation.
    """
    deadline = time.monotonic() + DB_CONNECT_RETRY_SECONDS
    last = None
    while time.monotonic() < deadline:
        try:
            return psycopg.connect(DATABASE_URL, autocommit=True)
        except psycopg.OperationalError as exc:
            last = exc
            time.sleep(DB_RETRY_INTERVAL_SECONDS)
    raise RuntimeError(f"database never accepted a connection: {last}")


def ensure_seed(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (SETUP_LOCK_KEY,))
        try:
            cur.execute(SCHEMA)
            for tenant, rows in SEED.items():
                cur.execute(
                    "SELECT count(*) FROM entries WHERE tenant_id = %s", (tenant,))
                if cur.fetchone()[0]:
                    continue
                for worker, hours, note in rows:
                    cur.execute(
                        "INSERT INTO entries (tenant_id, worker, hours, note)"
                        " VALUES (%s, %s, %s, %s)", (tenant, worker, hours, note))
        finally:
            cur.execute("SELECT pg_advisory_unlock(%s)", (SETUP_LOCK_KEY,))


def mint_token(tenant: str, user: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"tenant": tenant, "user": user}).encode()).decode()
    signature = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def read_token(token: str) -> dict | None:
    """Return the payload if the signature is valid under *this* service's secret."""
    payload, _, signature = token.partition(".")
    if not signature:
        return None
    expected = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None


class BaseHandler(BaseHTTPRequestHandler):
    """Routing and I/O. Subclasses supply the two isolation decisions."""

    server_version = "timesheet/1.0"
    conn: psycopg.Connection

    def accept_session(self, token: str) -> dict | None:
        raise NotImplementedError

    def fetch_entry(self, entry_id: int, session: dict) -> tuple | None:
        raise NotImplementedError

    def reply(self, status: int, body: dict) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def session(self) -> dict | None:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        return self.accept_session(header[len("Bearer "):])

    def do_POST(self) -> None:
        if self.path != "/login":
            return self.reply(404, {"error": "no such route"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.reply(400, {"error": "body is not JSON"})
        user = body.get("user")
        if not user:
            return self.reply(400, {"error": "user is required"})
        # No password check: this lab is about what a *valid* session can reach,
        # and a login defect here would only muddy that.
        self.reply(200, {"token": mint_token(TENANT_ID, user), "tenant": TENANT_ID})

    def do_GET(self) -> None:
        if self.path == "/healthz":
            return self.reply(200, {"ok": True, "tenant": TENANT_ID})

        session = self.session()
        if session is None:
            return self.reply(401, {"error": "no valid session"})

        if self.path == "/whoami":
            return self.reply(200, {"tenant": TENANT_ID, "session": session})

        if self.path == "/entries":
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT id, worker, hours, note FROM entries"
                    " WHERE tenant_id = %s ORDER BY id", (TENANT_ID,))
                rows = cur.fetchall()
            return self.reply(200, {"entries": [
                {"id": r[0], "worker": r[1], "hours": float(r[2]), "note": r[3]}
                for r in rows]})

        if self.path.startswith("/entries/"):
            raw = self.path[len("/entries/"):]
            if not raw.isdigit():
                return self.reply(400, {"error": "entry id must be a number"})
            row = self.fetch_entry(int(raw), session)
            if row is None:
                return self.reply(404, {"error": "no such entry"})
            return self.reply(200, {"id": row[0], "tenant_id": row[1], "worker": row[2],
                                    "hours": float(row[3]), "note": row[4]})

        self.reply(404, {"error": "no such route"})

    def log_message(self, fmt: str, *args) -> None:
        print(f"{TENANT_ID} {fmt % args}", flush=True)


def run(handler: type[BaseHandler]) -> None:
    conn = connect()
    ensure_seed(conn)
    handler.conn = conn
    print(f"{TENANT_ID} listening on 8000", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8000), handler).serve_forever()
