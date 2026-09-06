"""The findings in REVIEW.md, written as attacks.

Every test runs twice: once against ../vulnerable/app.py and once against
../fixed/app.py. Each one asserts that the attack works on the first and is
stopped on the second, so the report cannot drift away from the code.
"""
from __future__ import annotations

import base64
import importlib.util
import pathlib
import sqlite3
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
VICTIM = {"username": "alice", "password": "correct-horse-battery-staple"}
ATTACKER = {"username": "mallory", "password": "hunter2"}
SECRET_TASK_TITLE = "alice private key rotation"
LOGIN_MAX_ATTEMPTS = 5


def _load(name: str) -> object:
    path = ROOT / name / "app.py"
    spec = importlib.util.spec_from_file_location(f"taskapi_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["vulnerable", "fixed"])
def target(request):
    """A client plus the two users, for whichever copy of the app is under test."""
    module = _load(request.param)
    app = module.create_app()
    client = app.test_client()

    client.post("/register", json=VICTIM)
    client.post("/register", json=ATTACKER)
    victim_token = client.post("/login", json=VICTIM).get_json()["token"]
    attacker_token = client.post("/login", json=ATTACKER).get_json()["token"]
    task_id = client.post(
        "/tasks",
        json={"title": SECRET_TASK_TITLE, "notes": "root password is in the vault"},
        headers={"Authorization": f"Bearer {victim_token}"},
    ).get_json()["id"]

    return {
        "vulnerable": request.param == "vulnerable",
        "client": client,
        "connection": app.config["connection"],
        "victim_token": victim_token,
        "attacker_token": attacker_token,
        "victim_task_id": task_id,
    }


def _as_attacker(target: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {target['attacker_token']}"}


def test_finding_1_read_another_users_task(target):
    """Object-level authorization: a task belongs to whoever asks for it."""
    response = target["client"].get(f"/tasks/{target['victim_task_id']}", headers=_as_attacker(target))
    leaked = response.status_code == 200 and SECRET_TASK_TITLE in response.get_data(as_text=True)
    assert leaked is target["vulnerable"]


def test_finding_1_delete_another_users_task(target):
    """The same missing check on a destructive verb."""
    client, task_id = target["client"], target["victim_task_id"]
    client.delete(f"/tasks/{task_id}", headers=_as_attacker(target))
    still_there = client.get(
        f"/tasks/{task_id}", headers={"Authorization": f"Bearer {target['victim_token']}"}
    ).status_code == 200
    assert still_there is not target["vulnerable"]


def test_finding_2_sql_injection_in_search(target):
    """A crafted search term escapes the owner filter and returns other rows."""
    injection = "%' OR 1=1 --"
    response = target["client"].get(
        "/tasks/search", query_string={"q": injection}, headers=_as_attacker(target)
    )
    body = response.get_data(as_text=True)
    leaked = response.status_code == 200 and SECRET_TASK_TITLE in body
    assert leaked is target["vulnerable"]


def test_finding_3_passwords_are_not_stored_as_bare_md5(target):
    """What a database dump would be worth to whoever took it."""
    import hashlib

    stored = target["connection"].execute(
        "SELECT password FROM users WHERE username = ?", (VICTIM["username"],)
    ).fetchone()["password"]
    cracked = stored == hashlib.md5(VICTIM["password"].encode()).hexdigest()
    assert cracked is target["vulnerable"]


def test_finding_4_privilege_escalation_at_registration(target):
    """Mass assignment: the client decides which columns it writes."""
    client = target["client"]
    client.post("/register", json={"username": "sneaky", "password": "x", "is_admin": 1})
    row = target["connection"].execute(
        "SELECT is_admin FROM users WHERE username = ?", ("sneaky",)
    ).fetchone()
    escalated = row is not None and bool(row["is_admin"])
    assert escalated is target["vulnerable"]


def test_finding_5_admin_listing_needs_more_than_a_login(target):
    """Authentication is not authorization."""
    response = target["client"].get("/admin/users", headers=_as_attacker(target))
    assert (response.status_code == 200) is target["vulnerable"]


def test_finding_5_admin_listing_never_returns_password_hashes(target):
    """Even the allowed caller should not receive hashes."""
    connection = target["connection"]
    connection.execute("UPDATE users SET is_admin = 1 WHERE username = ?", (ATTACKER["username"],))
    connection.commit()
    response = target["client"].get("/admin/users", headers=_as_attacker(target))
    body = response.get_data(as_text=True)
    assert ("password" in body) is target["vulnerable"]


def test_finding_6_token_can_be_forged(target):
    """An unsigned token is a claim, not a credential."""
    victim_id = target["connection"].execute(
        "SELECT id FROM users WHERE username = ?", (VICTIM["username"],)
    ).fetchone()["id"]
    forged = base64.urlsafe_b64encode(f"{victim_id}:{VICTIM['username']}".encode()).decode()
    response = target["client"].get(
        f"/tasks/{target['victim_task_id']}", headers={"Authorization": f"Bearer {forged}"}
    )
    accepted = response.status_code == 200
    assert accepted is target["vulnerable"]


def test_finding_7_login_reveals_which_usernames_exist(target):
    """Two different answers are a username oracle."""
    client = target["client"]
    unknown = client.post("/login", json={"username": "nobody-here", "password": "x"})
    known = client.post("/login", json={"username": VICTIM["username"], "password": "wrong"})
    distinguishable = (
        unknown.status_code != known.status_code
        or unknown.get_json()["error"] != known.get_json()["error"]
    )
    assert distinguishable is target["vulnerable"]


def test_finding_7_login_is_rate_limited(target):
    """Guessing should get slower, not stay free."""
    client = target["client"]
    statuses = [
        client.post("/login", json={"username": VICTIM["username"], "password": f"guess-{n}"}).status_code
        for n in range(LOGIN_MAX_ATTEMPTS + 2)
    ]
    unlimited = 429 not in statuses
    assert unlimited is target["vulnerable"]


def test_finding_8_errors_do_not_describe_the_backend(target):
    """A malformed term should not come back as a database error message."""
    response = target["client"].get(
        "/tasks/search", query_string={"q": "'"}, headers=_as_attacker(target)
    )
    body = response.get_data(as_text=True)
    leaked = response.status_code == 500 and "OperationalError" in body
    assert leaked is target["vulnerable"]


def test_owner_can_still_use_the_api(target):
    """The fixes must not break the feature they protect."""
    client = target["client"]
    headers = {"Authorization": f"Bearer {target['victim_token']}"}
    own = client.get(f"/tasks/{target['victim_task_id']}", headers=headers)
    assert own.status_code == 200
    assert own.get_json()["title"] == SECRET_TASK_TITLE

    found = client.get(
        "/tasks/search", query_string={"q": "rotation"}, headers=headers
    ).get_json()
    assert [task["title"] for task in found] == [SECRET_TASK_TITLE]

    listed = client.get("/tasks", headers=headers).get_json()
    assert len(listed) == 1


def test_database_schema_matches_between_copies():
    """The two apps differ in behaviour, not in shape."""
    schemas = []
    for name in ("vulnerable", "fixed"):
        connection = sqlite3.connect(":memory:")
        connection.executescript(_load(name).SCHEMA)
        schemas.append(
            sorted(
                row[0]
                for row in connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'table'"
                )
            )
        )
    assert schemas[0] == schemas[1]
