# Security review of a small Flask API

A worked example of how I do a security review: take a small service,
find what is wrong with it, prove each finding, fix it, and leave tests behind so the fix
cannot quietly regress.

- `vulnerable/app.py` — the API as received. Eight defects, each marked with its finding
  number. **Do not deploy it.** It exists so the findings can be reproduced.
- `fixed/app.py` — the same routes and responses with all eight closed.
- `REVIEW.md` — the deliverable a client actually gets: each finding with location, evidence,
  impact, fix, and the test that holds it.
- `tests/test_security.py` — the findings written as attacks.

## Run it

```
pip install flask pytest
cd portfolio/flask-api-review
python -m pytest tests -q
```

Expected: `25 passed`.

Every test runs twice, once per copy of the app. The assertions are written as
`assert attack_succeeded is target["vulnerable"]`, so the suite fails if a fix regresses
**and** if a finding turns out not to be real in the first place. That is the point: the
report cannot drift away from the code.

To poke at either copy by hand:

```
python -c "import sys; sys.path.insert(0, 'vulnerable'); from app import create_app; create_app().run(port=5000)"
```

## What each test proves

| Test | Finding |
|---|---|
| `test_finding_1_read_another_users_task` | any user reads any task |
| `test_finding_1_delete_another_users_task` | any user deletes any task |
| `test_finding_2_sql_injection_in_search` | search term escapes the owner filter |
| `test_finding_3_passwords_are_not_stored_as_bare_md5` | stored hash equals plain MD5 |
| `test_finding_4_privilege_escalation_at_registration` | client sets `is_admin` |
| `test_finding_5_admin_listing_needs_more_than_a_login` | ordinary user reaches `/admin/users` |
| `test_finding_5_admin_listing_never_returns_password_hashes` | hashes in the response |
| `test_finding_6_token_can_be_forged` | unsigned token accepted |
| `test_finding_7_login_reveals_which_usernames_exist` | username oracle |
| `test_finding_7_login_is_rate_limited` | unlimited password guessing |
| `test_finding_8_errors_do_not_describe_the_backend` | database error text returned |
| `test_owner_can_still_use_the_api` | the fixes did not break the feature |
| `test_database_schema_matches_between_copies` | the two copies differ in behaviour only |

## Honest scope

This is a demonstration built for the portfolio, not client work and not a finding against
anyone's system. The vulnerable copy was written for this folder so the review has a
subject; the defects in it are textbook classes chosen because they are the ones that
actually turn up in small production APIs. Nothing here was run against any system other
than this one.
