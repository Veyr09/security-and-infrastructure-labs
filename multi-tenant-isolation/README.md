# Multi-tenant isolation, in three deployments

One timesheet service, rolled out to two construction companies. Three ways of
deploying it, each in a compose file you can run, and a probe script that checks
each one behaves the way its compose file claims.

The question the lab exists to answer is the one that decides a multi-tenant
rollout: **separate databases, or separate schemas in one instance?** The answer
changes where the isolation boundary lives, and what happens when a query
forgets its tenant.

## The three stacks

| Stack | Database | Signing key | Application |
|---|---|---|---|
| `shared-vulnerable` | one, shared | one, shared | no tenant predicate |
| `shared-fixed` | one, shared | per tenant | tenant predicate in the query |
| `isolated` | one per tenant | per tenant | tenant predicate in the query |

`shared-vulnerable` is not a straw man. It is what a rollout looks like when
each new client is added by pointing another app at the same database and
copying the `.env` across. **Both tenants log in correctly and each sees only
its own rows on `/entries`.** Nothing on the screen is wrong.

## What the probes check

`verify.py` runs four probes and compares each against what that stack claims:

- **cross_tenant_read** — authenticate as tenant A, then ask for a row id that
  belongs to tenant B. This is the whole job in one request.
- **token_replay** — mint a session at tenant A and present it to tenant B.
- **db_path_open** — from inside tenant A's container, open a TCP socket to the
  database holding tenant B's rows.
- **only_proxy_published** — read the actual bindings from `docker compose ps`
  rather than trusting the compose file, and confirm the proxy is the only
  service publishing a port.

## Run it

```
cd lab
docker compose -f compose.shared-vulnerable.yml up -d --build
cd ..
python verify.py --stack shared-vulnerable      # exits 0: leaks, as claimed

cd lab
docker compose -f compose.shared-vulnerable.yml down -v
docker compose -f compose.shared-fixed.yml up -d --build
cd ..
python verify.py --stack shared-fixed           # exits 0: closed in the app

cd lab
docker compose -f compose.shared-fixed.yml down -v
docker compose -f compose.isolated.yml up -d --build
cd ..
python verify.py --stack isolated               # exits 0: closed in both layers

cd lab && docker compose -f compose.isolated.yml down -v
```

Needs Docker and Python 3.10+. `verify.py` uses only the standard library; the
service inside the containers uses `psycopg` and nothing else.

Give the containers a few seconds after `up` before probing. The app waits for
Postgres, but the proxy will answer 502 until the app behind it is listening.

## What actually happened

Captured runs are in `sample/`. From `sample/verify-shared-vulnerable.txt`:

```
  ok     cross_tenant_read: expected True, got True
           tenant-a read entry 4: tenant-b / M. Dubois / Roofing, site 3
  ok     token_replay: expected True, got True
           tenant-b accepted tenant-a's token: {"tenant": "tenant-b", "session": {"tenant": "tenant-a", "user": "probe"}}
```

The second line is the one worth reading twice. Tenant B is serving a request
under a session that says, in its own payload, that it belongs to tenant A. The
signature was valid, because both services were deployed with the same key.

From `sample/verify-isolated.txt`:

```
  ok     cross_tenant_read: expected False, got False
           tenant-a asked for entry 4 and got HTTP 404
  ok     db_path_open: expected False, got False
           app-a -> db-b:5432 : gaierror: [Errno -2] Name or service not known
```

## The two code changes

The difference between `lab/app/vulnerable.py` and `lab/app/fixed.py` is two
predicates. Everything else - routes, login, the shape of the queries - is the
same file.

```python
# vulnerable.py: the id space is global, so this returns whatever row has
# that id, whoever it belongs to.
"SELECT id, tenant_id, worker, hours, note FROM entries WHERE id = %s"

# fixed.py
"SELECT id, tenant_id, worker, hours, note FROM entries WHERE id = %s AND tenant_id = %s"
```

and, on the session:

```python
# vulnerable.py: checks the token is signed, and nothing else.
return read_token(token)

# fixed.py: a valid signature says someone holding the key issued this. It does
# not say it was issued for this tenant.
if session is None or session.get("tenant") != TENANT_ID:
    return None
```

That is the argument for putting the predicate in the query rather than in a
check after it: a row that is not this tenant's is *not found*, rather than
found and then withheld, so there is no ordering left to get wrong.

## Two things done deliberately

**Every database is seeded with both tenants' rows, including in the isolated
stack.** `sample/isolated-db-a-contents.txt` shows tenant B's three rows sitting
in tenant A's own database. That is not what a real per-tenant deployment would
look like, and it is on purpose: it means the isolated stack's 404 is the
application's tenant predicate doing the work, not an accident of the row being
absent. The isolated stack is tested under the harder condition.

**`db_path_open` is expected to be true in `shared-fixed`.** One database means
one network path, and the fixed application is what holds the line. Reporting
that honestly is the point of the table: `shared-fixed` closes the data leak
without closing the path, and `isolated` closes both. A client choosing between
them should see exactly that difference.

## The probes can fail

`sample/verify-negative-control.txt` is the `shared-fixed` expectations run
against the `shared-vulnerable` stack. Both HTTP probes report `FAIL` and the
script exits 1. A check that cannot fail is not evidence of anything, so it is
worth having the failing run on file next to the passing ones.

## One bug found while building this

Both apps start at once, and in the shared-database stacks they run
`CREATE TABLE IF NOT EXISTS` against the same server. That is not atomic against
a concurrent `CREATE`: one app won, the other died with
`UniqueViolation: duplicate key value violates unique constraint
"pg_type_typname_nsp_index"`, and the stack came up with one tenant missing. The
seed had the same race - two callers can both see an empty table and both fill
it. One Postgres advisory lock around setup covers both, and that is what
`common.py` does now.
