# Runbook: closing a publicly exposed application port behind a reverse proxy

The procedure, in the order it has to happen. This is the document a client
receives alongside the change, because on infrastructure work the written record
is worth as much as the edit: it is what lets someone else undo it at 3am.

Substitute your own service name, port and proxy. The lab in `lab/` runs the
whole thing end to end so the steps can be rehearsed before they touch anything
that matters.

---

## 0. Before touching anything

**Take a snapshot.** A provider snapshot if there is one, and in every case a
copy of the files you are about to change:

```
cp docker-compose.yml docker-compose.yml.bak
cp Caddyfile Caddyfile.bak
```

**Keep your way in open.** If you are going to enable a firewall, allow SSH
first and confirm it, in that order:

```
ufw allow OpenSSH
ufw status
```

Know the out-of-band route too (provider console), because the failure mode of
getting this wrong is losing the box entirely.

## 1. Establish what actually depends on the port

This is the step people skip, and it is the one that breaks production.

**Where does the proxy send traffic?** Read the Caddyfile or nginx config. If the
upstream is the service name on the compose network (`reverse_proxy app:80`),
binding the publish to loopback changes nothing for the proxy. If the upstream
is the *host* port (`127.0.0.1:8080`, `host.docker.internal:8080`), then the
proxy depends on the publish you are about to move, and the site goes down with
the port unless you switch it to the container first.

**What URLs does the application hand out?** For n8n specifically, check
`WEBHOOK_URL`, `N8N_HOST`, `N8N_PROTOCOL` and `N8N_EDITOR_BASE_URL`. If the app
generates callback URLs containing `host:8080`, every integration holding one
breaks the moment the port closes. Repoint them at the public hostname first.

**Who else is calling it?** `docker ps` for other containers, then the app and
proxy logs for recent direct hits on the port from anything not in the list you
were given:

```
docker compose logs --since 24h app | grep -F ':8080'
```

Cron jobs and internal tools are where the surprise lives.

## 2. Make the change

One line in the compose file:

```yaml
ports:
  - "127.0.0.1:8080:80"   # was "8080:80"
```

Then recreate the container. The publish is set at creation time, so a restart
is not enough:

```
docker compose up -d
```

## 3. Understand what the firewall does and does not do here

Do not rely on `ufw deny 8080` to close a published container port, and do not
assume it is useless either. Measured on Ubuntu with a native Docker daemon,
probed from a separate host (`sample/03-ufw-linux.txt`):

- **Docker's default (userland proxy on):** the published port is an ordinary
  host socket held by `docker-proxy`, packets arrive in `INPUT`, and the ufw
  rule **works**.
- **`userland-proxy: false`:** `nat PREROUTING` DNATs the packet to the container
  address, so it is routed rather than delivered locally. It traverses `FORWARD`,
  never `INPUT`, and the same ufw rule **does nothing** while the port answers
  the internet.

So the state of the firewall tells you nothing on its own. Check which
configuration you are in:

```
cat /etc/docker/daemon.json          # userland-proxy setting, if any
ss -tlnp | grep 8080                 # docker-proxy present, or dockerd/DNAT only
iptables -t nat -S DOCKER | grep 8080
```

A rule that must hold regardless belongs in `DOCKER-USER`, which `FORWARD`
reaches before Docker's own chain:

```
iptables -I DOCKER-USER -p tcp --dport 8080 -j DROP
```

Verified: that rule blocks the port even in the configuration where the ufw rule
does not.

The bind in step 2 remains the change that actually matters, because it removes
the listener from every routable address and therefore holds in both
configurations. Treat the firewall as a second layer, and check for a
provider-level firewall (Hetzner Cloud Firewall, AWS security group) as a third.

## 4. Verify from somewhere else

Checking from the server proves nothing: loopback always answers. Use a routable
address, and cover both address families, because a publish on `0.0.0.0`
generally brings a `::` listener with it and firewall rules are per-family.

```
python verify.py --app-port 8080 --proxy-port 8081
```

or by hand, from another machine:

```
nmap -Pn -p 8080 <host>          # expect closed or filtered, not open
curl --max-time 5 http://<host>:8080/   # expect refusal or timeout
nmap -6 -Pn -p 8080 <host>
docker port <container>          # expect 127.0.0.1:8080, no 0.0.0.0 and no [::]
ss -tlnp | grep 8080
```

Then prove the thing the client cares about still works: request the public
hostname through the proxy, and re-run whatever endpoint check exists for the
webhooks or integrations.

## 5. Write it down

What changed, what was checked, what the verification returned, and the exact
rollback:

```
cp docker-compose.yml.bak docker-compose.yml
docker compose up -d
```

## Failure modes worth naming in advance

| Symptom after the change | Cause |
|---|---|
| Site down, port also closed | Proxy upstream pointed at the host port, not the container |
| Port still open from outside | Relied on ufw; the publish is still `0.0.0.0`, or a `DOCKER-USER` rule is needed |
| Open on IPv6 only | Rule or bind covered IPv4 only; the `::` listener survived |
| Webhooks stop firing | The app was handing out URLs containing `host:port` |
| Locked out of the server | Firewall enabled before SSH was allowed |
