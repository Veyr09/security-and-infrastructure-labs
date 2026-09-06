# Onboarding a new tenant: the written procedure

What a client receives with the work. The lab in this repository is the same
procedure with two tenants and a probe script attached.

## Before touching anything

1. **Decide the boundary and write it down.** Separate database per tenant, or
   separate schema in one instance? Per-tenant databases remove the network path
   between tenants and make restore-one-client trivial; a shared instance is
   cheaper and simpler to operate, and puts the whole weight of separation on
   the application. There is no wrong answer, but an undecided one produces a
   deployment that is neither.
2. **Confirm what the application does when a query forgets its tenant.** Ask
   for one record by id as the wrong tenant, before the client has any data in
   it. If it comes back, that is the first thing to fix, whatever the deployment
   looks like.
3. **Record the rollback.** For a new tenant this is usually "remove the compose
   project and the volume", which is only true if nothing was added to a shared
   resource.

## The change

4. Create the tenant's own network, volume and database. Nothing is shared with
   another tenant except the proxy.
5. **Generate a fresh signing key for this tenant.** Do not copy the previous
   tenant's `.env`. This is the single most common way two isolated tenants stop
   being isolated, and it leaves no trace in the application logs, because every
   request is correctly signed.
6. Publish no ports from the application or the database. The proxy is the only
   service with a `ports:` entry, and it binds to loopback if anything else
   terminates TLS in front of it.
7. Point the proxy at the service name on the tenant's network, not at a host
   port. That is what keeps the site reachable when the published port goes away.

## Verification, before handover

8. Authenticate as the new tenant, list its records: it sees its own.
9. **Authenticate as the new tenant and ask for an existing tenant's record by
   id.** Expect a 404. If anything comes back, separation is not real yet
   whatever the login screen says.
10. Mint a session at the new tenant and present it to an existing one, and the
    reverse. Expect 401 both ways. If either is accepted, step 5 was skipped.
11. From inside the new tenant's application container, try to open a socket to
    another tenant's database. Expect it to fail to resolve.
12. Read `docker compose ps` and confirm the proxy is the only service
    publishing a port. Read the bindings, do not trust the compose file.
13. Certificate valid, and renewal actually exercised rather than assumed.
14. Backup taken **and one restore performed** into a scratch database. An
    untested backup is a hope.

## Failure modes worth naming in advance

- **A shared signing key.** Covered above; it is invisible in logs.
- **A shared cache or queue.** Separate databases do not help if both tenants
  read the same Redis keyspace. Whatever else is shared needs the same question
  asked of it.
- **Sequential ids across tenants.** Not a vulnerability by itself, but it makes
  a missing tenant predicate trivially exploitable by anyone who can count. It
  also tells every tenant roughly how many records the others have.
- **Backups restored to the wrong tenant.** Name the artefacts by tenant, and
  make the restore procedure require the tenant as an argument.
- **The proxy as the shared component.** It has to reach every tenant, so it is
  the one thing that spans them. Keep it doing hostname routing and TLS, and
  nothing else.
