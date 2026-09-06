# Security review: task-tracker API

**Target:** `vulnerable/app.py`, a Flask + SQLite JSON API (register, log in, create and
read tasks, search, admin user listing).
**Method:** source review, then each suspected defect reproduced against a local instance
with two accounts, `alice` (victim) and `mallory` (attacker).
**Result:** 8 findings. All 8 are fixed in `fixed/app.py` and each fix is held in place by a
test in `tests/test_security.py`.

Severity is the practical one a client cares about: what an attacker gets, assuming they
can register an ordinary account, which anyone can.

| # | Finding | Severity | Fixed in |
|---|---|---|---|
| 1 | Any user can read and delete any other user's tasks | **Critical** | `get_task`, `delete_task` |
| 2 | SQL injection in task search | **Critical** | `search_tasks` |
| 3 | Passwords stored as unsalted MD5 | **High** | `register`, `login` |
| 4 | Registration lets the client set `is_admin` | **High** | `register` |
| 5 | Admin listing needs only a login, and returns password hashes | **High** | `admin_users` |
| 6 | Session tokens are unsigned and never expire | **Critical** | `current_user`, `login` |
| 7 | Login reveals which usernames exist, and is unlimited | **Medium** | `login` |
| 8 | Unhandled errors return the exception text | **Low** | `handle` |

---

## 1. Broken object-level authorization on `/tasks/<id>` — Critical

**Where.** `get_task` and `delete_task`.

The handlers check that *somebody* is logged in and then look the task up by id alone:

```python
row = db().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
```

**Reproduction.** As `mallory`, request `GET /tasks/1`, a task belonging to `alice`. The
response is 200 with her title and notes. `DELETE /tasks/1` removes it.

**Impact.** Every task in the database is readable and destroyable by any account, and task
ids are sequential, so the whole table can be walked in one loop. This is the single most
expensive defect here: it needs no craft, only a counter.

**Fix.** Make the owner part of the lookup rather than a separate check that can be
forgotten, and answer 404 rather than 403 so the response does not confirm that the id
exists:

```python
row = db().execute(
    "SELECT * FROM tasks WHERE id = ? AND owner_id = ?", (task_id, user["id"])
).fetchone()
```

`delete_task` does the same and returns 404 when `rowcount` is 0.

**Verified by** `test_finding_1_read_another_users_task`, `test_finding_1_delete_another_users_task`.

---

## 2. SQL injection in `/tasks/search` — Critical

**Where.** `search_tasks`.

```python
query = f"SELECT * FROM tasks WHERE owner_id = {user['id']} AND title LIKE '%{term}%'"
```

Both the user id and the search term are formatted into the statement.

**Reproduction.** `GET /tasks/search?q=%' OR 1=1 --` returns every task in the table,
including `alice`'s, to `mallory`. The trailing `--` comments out the rest of the pattern.

**Impact.** Reading the whole database, including the `users` table via a `UNION`. Because
`executescript` is not in play the blast radius stops short of arbitrary DDL, but reading
is enough: the password hashes live in the same file.

**Fix.** Bind both values as parameters, so the term can only ever be data:

```python
rows = db().execute(
    "SELECT * FROM tasks WHERE owner_id = ? AND title LIKE ?",
    (user["id"], f"%{term}%"),
).fetchall()
```

**Verified by** `test_finding_2_sql_injection_in_search`.

---

## 3. Passwords stored as unsalted MD5 — High

**Where.** `_hash`.

```python
return hashlib.md5(password.encode()).hexdigest()
```

**Reproduction.** The row for `alice` stores exactly
`md5("correct-horse-battery-staple")`. The test recomputes that digest and compares.

**Impact.** MD5 is fast and unsalted, so a stolen database is a list of plaintext
passwords: rainbow tables cover common choices, and identical passwords produce identical
rows, which exposes reuse across accounts. Finding 2 is one way that dump gets taken.

**Fix.** `werkzeug.security.generate_password_hash` (scrypt by default: salted, work
factored) and `check_password_hash` on the way back in.

**Note.** Existing hashes cannot be converted. In a real migration, re-hash each password
on the user's next successful login and mark the row as upgraded.

**Verified by** `test_finding_3_passwords_are_not_stored_as_bare_md5`.

---

## 4. Mass assignment at registration — High

**Where.** `register` builds its `INSERT` from whatever keys the client sent:

```python
columns = ", ".join(payload.keys())
```

**Reproduction.** `POST /register {"username": "sneaky", "password": "x", "is_admin": 1}`
creates an administrator.

**Impact.** Anyone can grant themselves whatever any column in `users` controls. Today that
is `is_admin`; the more serious version of this bug is that it keeps working as the schema
grows, so a column added next year is exposed the day it lands.

**Fix.** Read the two fields the endpoint actually accepts, by name, and ignore everything
else. An allowlist, never a denylist.

**Verified by** `test_finding_4_privilege_escalation_at_registration`.

---

## 5. Admin listing is gated on authentication, not authorization — High

**Where.** `admin_users` checks `user is None` and nothing more, then selects the password
column along with the rest.

**Reproduction.** `mallory`, an ordinary user, calls `GET /admin/users` and receives every
account with its hash.

**Impact.** Full user enumeration plus the hashes, which combined with finding 3 is a
credential dump. Two mistakes are stacked here: the missing role check, and the fact that
hashes are in the query at all.

**Fix.** Require `user["is_admin"]` and return 403 otherwise, and narrow the query to
`id, username, is_admin` so a hash cannot leave the process even for a legitimate admin.

**Verified by** `test_finding_5_admin_listing_needs_more_than_a_login`,
`test_finding_5_admin_listing_never_returns_password_hashes`.

---

## 6. Session tokens are unsigned and never expire — Critical

**Where.** `_make_token` and `_read_token`.

```python
base64.urlsafe_b64encode(f"{user_id}:{username}".encode())
```

Base64 is an encoding, not a signature. The server decodes the token and believes it.

**Reproduction.** Without logging in at all, send
`Authorization: Bearer ` + `base64("1:alice")`. The API treats the caller as `alice`. Since
ids are sequential, every account can be impersonated by counting.

**Impact.** Complete authentication bypass, including the administrator once finding 4 or 5
has created one. There is also no expiry, so any token that ever leaks is valid forever.

**Fix.** Sign the token and give it a lifetime. `itsdangerous.URLSafeTimedSerializer` is
already a Flask dependency:

```python
serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="task-api-token")
user_id = serializer.loads(token, max_age=TOKEN_TTL_SECONDS)
```

The key is read from `TASK_API_SECRET`, never hardcoded. A tampered or stale token raises
`BadSignature` / `SignatureExpired` and the request is rejected.

**Verified by** `test_finding_6_token_can_be_forged`.

---

## 7. Login is a username oracle, and unlimited — Medium

**Where.** `login` answers `404 {"error": "no such user"}` for an unknown name and
`401 {"error": "wrong password"}` for a known one, with no limit on attempts.

**Reproduction.** Compare the two responses; they differ in both status and body. Then send
any number of guesses at the same account without being slowed down.

**Impact.** An attacker can build a list of real usernames cheaply and then guess passwords
against them at full speed. On its own this is a nuisance; combined with finding 3 it is
how the whole user table gets opened.

**Fix.** One answer, `401 {"error": "invalid username or password"}`, for both cases, and a
per-username attempt counter that returns 429 after five failures in five minutes.

**Caveat, stated rather than hidden.** The counter lives in process memory, so it is per
worker. Behind more than one worker it needs a shared store such as Redis, and it should be
paired with a per-IP limit at the proxy. The demo keeps it in memory on purpose so the test
suite needs no external service.

**Verified by** `test_finding_7_login_reveals_which_usernames_exist`,
`test_finding_7_login_is_rate_limited`.

---

## 8. Error handler returns the exception text — Low

**Where.** The catch-all handler returns `str(error)` and the exception class name.

**Reproduction.** `GET /tasks/search?q='` produces an unbalanced quote, and the response is
500 with `sqlite3.OperationalError` and the malformed statement.

**Impact.** On its own, information disclosure. In practice it is what turns finding 2 from
a guess into a fast, guided attack: the error text tells the attacker exactly how their
payload landed.

**Fix.** Log the exception with `app.logger.exception` and return a flat
`{"error": "internal server error"}`.

**Verified by** `test_finding_8_errors_do_not_describe_the_backend`.

---

## What was checked and found clean

Recording this so the review is not read as "everything not listed is untested":

- `POST /tasks` writes `owner_id` from the token, not from the request body.
- `GET /tasks` filters by owner and was correct in the original.
- The schema is identical between the two copies; the fixes are behavioural, not structural
  (`test_database_schema_matches_between_copies`).
- The fixes do not break normal use: an owner can still read, search and list their own
  tasks (`test_owner_can_still_use_the_api`).

## Out of scope for this review

Not examined, and not claimed to be safe: transport security (this is HTTP in the demo),
CORS, CSRF for any browser client, dependency versions, deployment configuration, and
logging retention. Nothing here was tested against any system other than the local copy in
this folder.
