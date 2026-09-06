"""Task-tracker API, patched.

Same routes and same responses as the version in ../vulnerable, with the eight
findings in REVIEW.md closed. The test suite runs against both copies: every
attack in it succeeds there and fails here.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import time

from flask import Flask, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

DATABASE_SENTINEL = ":memory:"
TOKEN_TTL_SECONDS = 60 * 60
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300
SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);
"""


def create_app(database: str = DATABASE_SENTINEL) -> Flask:
    app = Flask(__name__)
    # FIX 6: the signing key comes from the environment. Falling back to a random
    # per-process key is only acceptable because this demo keeps no state between runs.
    app.config["SECRET_KEY"] = os.environ.get("TASK_API_SECRET") or secrets.token_urlsafe(32)
    serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="task-api-token")

    connection = sqlite3.connect(database, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    connection.commit()
    app.config["connection"] = connection

    # FIX 7: per-username attempt counter. One process is enough for the demo; a real
    # deployment needs a shared store so the limit survives more than one worker.
    failures: dict[str, list[float]] = {}

    def db() -> sqlite3.Connection:
        return app.config["connection"]

    def too_many_failures(username: str) -> bool:
        cutoff = time.monotonic() - LOGIN_WINDOW_SECONDS
        recent = [at for at in failures.get(username, []) if at > cutoff]
        failures[username] = recent
        return len(recent) >= LOGIN_MAX_ATTEMPTS

    def record_failure(username: str) -> None:
        failures.setdefault(username, []).append(time.monotonic())

    def current_user() -> sqlite3.Row | None:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        try:
            user_id = serializer.loads(header.removeprefix("Bearer "), max_age=TOKEN_TTL_SECONDS)
        except (BadSignature, SignatureExpired):
            return None
        return db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    @app.post("/register")
    def register():
        payload = request.get_json(silent=True) or {}
        # FIX 4: only these two fields are ever read, so is_admin cannot be set from outside.
        username = payload.get("username")
        password = payload.get("password")
        if not username or not password:
            return jsonify({"error": "username and password are required"}), 400
        if db().execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            return jsonify({"error": "username is taken"}), 409
        cursor = db().execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            # FIX 3: salted, work-factored hash instead of MD5.
            (username, generate_password_hash(password)),
        )
        db().commit()
        return jsonify({"id": cursor.lastrowid}), 201

    @app.post("/login")
    def login():
        payload = request.get_json(silent=True) or {}
        username = payload.get("username", "")
        if too_many_failures(username):
            return jsonify({"error": "too many attempts, try again later"}), 429
        row = db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        # FIX 7: one answer for "no such user" and "wrong password" alike.
        if row is None or not check_password_hash(row["password"], payload.get("password", "")):
            record_failure(username)
            return jsonify({"error": "invalid username or password"}), 401
        failures.pop(username, None)
        return jsonify({"token": serializer.dumps(row["id"])})

    @app.get("/tasks")
    def list_tasks():
        user = current_user()
        if user is None:
            return jsonify({"error": "unauthorized"}), 401
        rows = db().execute("SELECT * FROM tasks WHERE owner_id = ?", (user["id"],)).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.get("/tasks/<int:task_id>")
    def get_task(task_id: int):
        user = current_user()
        if user is None:
            return jsonify({"error": "unauthorized"}), 401
        # FIX 1: the owner is part of the lookup, so another user's row is simply not
        # found. Answering 404 rather than 403 also hides whether the id exists.
        row = db().execute(
            "SELECT * FROM tasks WHERE id = ? AND owner_id = ?", (task_id, user["id"])
        ).fetchone()
        if row is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(dict(row))

    @app.delete("/tasks/<int:task_id>")
    def delete_task(task_id: int):
        user = current_user()
        if user is None:
            return jsonify({"error": "unauthorized"}), 401
        cursor = db().execute(
            "DELETE FROM tasks WHERE id = ? AND owner_id = ?", (task_id, user["id"])
        )
        db().commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "not found"}), 404
        return jsonify({"deleted": task_id})

    @app.post("/tasks")
    def create_task():
        user = current_user()
        if user is None:
            return jsonify({"error": "unauthorized"}), 401
        payload = request.get_json(silent=True) or {}
        cursor = db().execute(
            "INSERT INTO tasks (owner_id, title, notes) VALUES (?, ?, ?)",
            (user["id"], payload.get("title", ""), payload.get("notes", "")),
        )
        db().commit()
        return jsonify({"id": cursor.lastrowid}), 201

    @app.get("/tasks/search")
    def search_tasks():
        user = current_user()
        if user is None:
            return jsonify({"error": "unauthorized"}), 401
        term = request.args.get("q", "")
        # FIX 2: the term is bound as a parameter, so it can only ever be data.
        rows = db().execute(
            "SELECT * FROM tasks WHERE owner_id = ? AND title LIKE ?",
            (user["id"], f"%{term}%"),
        ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.get("/admin/users")
    def admin_users():
        user = current_user()
        if user is None:
            return jsonify({"error": "unauthorized"}), 401
        # FIX 5: being authenticated is not the same as being allowed.
        if not user["is_admin"]:
            return jsonify({"error": "forbidden"}), 403
        # Password hashes are never part of a response, not even for an admin.
        rows = db().execute("SELECT id, username, is_admin FROM users").fetchall()
        return jsonify([dict(row) for row in rows])

    @app.errorhandler(Exception)
    def handle(error: Exception):
        # FIX 8: the detail goes to the log, not to the caller.
        app.logger.exception("unhandled error on %s", request.path)
        return jsonify({"error": "internal server error"}), 500

    return app
