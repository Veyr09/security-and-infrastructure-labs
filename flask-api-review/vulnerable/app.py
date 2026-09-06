"""Task-tracker API, as received for review.

This is the "before" copy of a small Flask service. It is deliberately left as it
was found so the review can be reproduced and so the tests have something to
attack. Every defect is marked with the finding number it carries in REVIEW.md.
Do not deploy it.
"""
from __future__ import annotations

import base64
import hashlib
import sqlite3

from flask import Flask, g, jsonify, request

DATABASE_SENTINEL = ":memory:"
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


def _hash(password: str) -> str:
    # FINDING 3: unsalted MD5.
    return hashlib.md5(password.encode()).hexdigest()


def _make_token(user_id: int, username: str) -> str:
    # FINDING 6: the "token" is reversible encoding, not a signature.
    return base64.urlsafe_b64encode(f"{user_id}:{username}".encode()).decode()


def _read_token(token: str) -> int | None:
    try:
        user_id, _username = base64.urlsafe_b64decode(token.encode()).decode().split(":", 1)
        return int(user_id)
    except Exception:
        return None


def create_app(database: str = DATABASE_SENTINEL) -> Flask:
    app = Flask(__name__)
    connection = sqlite3.connect(database, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    connection.commit()
    app.config["connection"] = connection

    def db() -> sqlite3.Connection:
        return app.config["connection"]

    def current_user() -> sqlite3.Row | None:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        user_id = _read_token(header.removeprefix("Bearer "))
        if user_id is None:
            return None
        return db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    @app.post("/register")
    def register():
        payload = request.get_json(silent=True) or {}
        columns = ", ".join(payload.keys())
        placeholders = ", ".join("?" for _ in payload)
        values = list(payload.values())
        if "password" in payload:
            values[list(payload.keys()).index("password")] = _hash(payload["password"])
        # FINDING 4: every key the client sends becomes a column, is_admin included.
        cursor = db().execute(f"INSERT INTO users ({columns}) VALUES ({placeholders})", values)
        db().commit()
        return jsonify({"id": cursor.lastrowid}), 201

    @app.post("/login")
    def login():
        payload = request.get_json(silent=True) or {}
        row = db().execute(
            "SELECT * FROM users WHERE username = ?", (payload.get("username"),)
        ).fetchone()
        # FINDING 7: distinct answers tell an attacker which usernames exist,
        # and nothing limits how fast they may ask.
        if row is None:
            return jsonify({"error": "no such user"}), 404
        if row["password"] != _hash(payload.get("password", "")):
            return jsonify({"error": "wrong password"}), 401
        return jsonify({"token": _make_token(row["id"], row["username"])})

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
        # FINDING 1: authenticated, but never checked against the owner.
        row = db().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(dict(row))

    @app.delete("/tasks/<int:task_id>")
    def delete_task(task_id: int):
        user = current_user()
        if user is None:
            return jsonify({"error": "unauthorized"}), 401
        # FINDING 1 again, on a destructive verb.
        db().execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        db().commit()
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
        # FINDING 2: the search term is concatenated straight into SQL.
        query = f"SELECT * FROM tasks WHERE owner_id = {user['id']} AND title LIKE '%{term}%'"
        rows = db().execute(query).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.get("/admin/users")
    def admin_users():
        user = current_user()
        # FINDING 5: any authenticated caller reaches the admin listing.
        if user is None:
            return jsonify({"error": "unauthorized"}), 401
        rows = db().execute("SELECT id, username, password, is_admin FROM users").fetchall()
        return jsonify([dict(row) for row in rows])

    @app.errorhandler(Exception)
    def handle(error: Exception):
        # FINDING 8: the exception text goes to the caller.
        return jsonify({"error": str(error), "type": type(error).__name__}), 500

    return app
