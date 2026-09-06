# Closing an exposed Docker port, with evidence

A runnable lab and the deliverable that goes with it. A container publishes its
port on every interface; the job is to make it unreachable from outside while the
site it serves keeps working, and to **prove** both halves from somewhere that is
not the server.

- `lab/compose.exposed.yml` — the "before": `ports: - "8080:80"`, the default that
  quietly puts an application on the public internet.
- `lab/compose.hardened.yml` — the "after": `ports: - "127.0.0.1:8080:80"`.
- `lab/Caddyfile` — the proxy, pointed at the **service name on the compose
  network**, not at the host port. That detail is what keeps the site up when the
  public port disappears.
- `verify.py` — the evidence. Probes from the host's routable address rather than
  loopback, reads `docker port` for the actual bindings, and confirms the proxy
  still serves the application.
- `RUNBOOK.md` — the written procedure a client receives: pre-checks, the change,
  what the firewall does and does not do, verification, rollback, and the failure
  modes worth naming in advance.

## Run it

```
cd lab
docker compose -f compose.exposed.yml up -d
cd ..
python verify.py --app-port 8080 --proxy-port 8081     # exits 1: exposed

cd lab
docker compose -f compose.exposed.yml down
docker compose -f compose.hardened.yml up -d
cd ..
python verify.py --app-port 8080 --proxy-port 8081     # exits 0: hardened

cd lab && docker compose -f compose.hardened.yml down
```

Needs Docker and Python 3.10+. No other dependencies; `verify.py` uses only the
standard library.

On a real engagement the probe has to run from a machine that is not the server,
so `verify.py --host <server>` names the target instead of probing the machine it
runs on. The loopback and `docker port` lines are then reported as not applicable,
because they only mean something on the box itself — which is the whole point: a
check run on the server passes whether the port is bound to 0.0.0.0 or to loopback.

## What the captured runs show

Real output, in `sample/`, from Docker 29.7.2 on 2026-09-06.

**Before** (`sample/01-exposed.txt`):

```
docker port hardening-app     : 80/tcp -> 0.0.0.0:8080
                                80/tcp -> [::]:8080
app  on 127.0.0.1:8080        : OPEN (connected)
app  on 192.168.1.13:8080     : OPEN (connected)
proxy serves the app          : yes (Hostname: 919d7657aa4e)

VERDICT: EXPOSED - the app port answers from a routable address
```

**After** (`sample/02-hardened.txt`):

```
docker port hardening-app     : 80/tcp -> 127.0.0.1:8080
app  on 127.0.0.1:8080        : OPEN (connected)
app  on 192.168.1.13:8080     : refused (ConnectionRefusedError)
proxy serves the app          : yes (Hostname: 79dd7956f20d)

VERDICT: HARDENED - app port refused from outside, proxy still serving
```

Two details worth pointing at, because both are where this goes wrong in practice:

- The exposed run also binds **`[::]:8080`**. A publish on `0.0.0.0` generally
  brings an IPv6 listener with it, and firewall rules are per-family, so a check
  that only covers IPv4 can report a closed port that is still reachable. In the
  hardened run that line is gone.
- The proxy keeps answering across the change (`proxy serves the app: yes` in
  both), which is the half a client actually cares about. Closing a port is easy;
  closing it without taking the service down is the job.

## Why loopback checks are worthless here

`verify.py` deliberately probes the host's routable address. A probe run on the
server against `localhost` succeeds whether the port is published on `0.0.0.0` or
bound to `127.0.0.1` — the check passes in both states, so it proves nothing. The
`app on 127.0.0.1` line is in the output only to make that visible: it stays OPEN
in both runs while the routable-address line flips from OPEN to refused.

## The firewall point, measured rather than repeated

"ufw does not protect Docker published ports" is repeated everywhere. It is
**conditional, not universal**, and this folder contains the measurement rather
than the folklore. `ufw-demo/` runs on Ubuntu with a native Docker daemon and a
real ufw, probed from a separate host; the full transcript is
`sample/03-ufw-linux.txt`.

| Configuration | `ufw deny 8080` | Port reachable from another host |
|---|---|---|
| Default Docker (userland proxy on) | rule present | **blocked** - ufw works |
| `userland-proxy: false` | same rule present | **OPEN** - ufw bypassed |
| `userland-proxy: false` + `DOCKER-USER` DROP | | blocked |
| Publish bound to `127.0.0.1` | | blocked |

Why the middle row happens: with the userland proxy off, the published port is
not a host socket. `nat PREROUTING` DNATs the packet to the container address,
so it is *routed* rather than delivered locally - it traverses `FORWARD`, never
`INPUT`, and ufw's INPUT rule is never consulted. The `FORWARD` chain reaches
`DOCKER-USER` and `DOCKER-FORWARD` before any ufw chain:

```
-P FORWARD DROP
-A FORWARD -j DOCKER-USER          <- reached first
-A FORWARD -j DOCKER-FORWARD
-A FORWARD -j ufw-before-forward
```

The practical consequence is an ordering, not a slogan: **bind the publish to
loopback**, put any rule that must hold regardless of configuration in
`DOCKER-USER`, and verify from another machine. That order is correct whichever
configuration you inherited, which is why it is the advice worth giving.

## Honest scope

Built for this portfolio, not client work. No third-party system was touched.
The lab is a local container pair; the value on offer is the procedure and the
verification, which are the parts that transfer.
