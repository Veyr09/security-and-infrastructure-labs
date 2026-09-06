"""Probe a running stack and check it behaves the way its compose file claims.

Usage:
    python verify.py --stack shared-vulnerable
    python verify.py --stack shared-fixed
    python verify.py --stack isolated

Exits 0 when every probe matches what that stack is supposed to do, 1 otherwise.
This is not "exits 1 if insecure": all three stacks are real configurations and
each has its own expected result. The script fails when a stack stops behaving
as documented - including when the fixed application regresses.
"""
from __future__ import annotations

import argparse
import http.client
import json
import subprocess
import sys
from pathlib import Path

LAB = Path(__file__).parent / "lab"
PROXY_HOST, PROXY_PORT = "127.0.0.1", 8080
TENANT_A, TENANT_B = "tenant-a.localhost", "tenant-b.localhost"
PROBE_TIMEOUT_SECONDS = 5
DOCKER_TIMEOUT_SECONDS = 60

# What each stack is supposed to do. Read this as the claim being tested.
EXPECTED = {
    "shared-vulnerable": {
        "cross_tenant_read": True,   # tenant A can read tenant B's row by id
        "token_replay": True,        # tenant A's token is accepted by tenant B
        "db_path_open": True,        # tenant A's app can reach tenant B's data
        "only_proxy_published": True,
    },
    "shared-fixed": {
        "cross_tenant_read": False,
        "token_replay": False,
        "db_path_open": True,        # one database still: the app holds the line
        "only_proxy_published": True,
    },
    "isolated": {
        "cross_tenant_read": False,
        "token_replay": False,
        "db_path_open": False,       # no network path to the other database
        "only_proxy_published": True,
    },
}

# In the shared stacks tenant B's rows live in the same server tenant A uses, so
# "the database holding tenant B's data" is that one host.
OTHER_TENANT_DB = {
    "shared-vulnerable": "db",
    "shared-fixed": "db",
    "isolated": "db-b",
}


def request(host: str, method: str, path: str, token: str | None = None,
            body: dict | None = None) -> tuple[int, dict]:
    """Talk to the proxy, choosing the tenant with the Host header."""
    conn = http.client.HTTPConnection(PROXY_HOST, PROXY_PORT,
                                      timeout=PROBE_TIMEOUT_SECONDS)
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Host": host}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=payload, headers=headers)
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    try:
        return response.status, json.loads(raw)
    except json.JSONDecodeError:
        return response.status, {"raw": raw.decode(errors="replace")}


def compose(stack: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", str(LAB / f"compose.{stack}.yml"), *args],
        capture_output=True, text=True, timeout=DOCKER_TIMEOUT_SECONDS)


def login(host: str) -> str:
    status, body = request(host, "POST", "/login", body={"user": "probe"})
    if status != 200 or "token" not in body:
        raise RuntimeError(f"login at {host} failed: {status} {body}")
    return body["token"]


def probe_cross_tenant_read(stack: str) -> tuple[bool, str]:
    """Authenticate as tenant A, ask for a row that belongs to tenant B."""
    token_b = login(TENANT_B)
    status, body = request(TENANT_B, "GET", "/entries", token=token_b)
    entries = body.get("entries") or []
    if status != 200 or not entries:
        raise RuntimeError(f"tenant B has no rows to target: {status} {body}")
    target = entries[0]["id"]

    token_a = login(TENANT_A)
    status, body = request(TENANT_A, "GET", f"/entries/{target}", token=token_a)
    if status == 200:
        return True, (f"tenant-a read entry {target}: "
                      f"{body.get('tenant_id')} / {body.get('worker')} / {body.get('note')}")
    return False, f"tenant-a asked for entry {target} and got HTTP {status}"


def probe_token_replay(stack: str) -> tuple[bool, str]:
    """Present tenant A's session to tenant B."""
    token_a = login(TENANT_A)
    status, body = request(TENANT_B, "GET", "/whoami", token=token_a)
    if status == 200:
        return True, f"tenant-b accepted tenant-a's token: {json.dumps(body)}"
    return False, f"tenant-b rejected tenant-a's token with HTTP {status}"


def probe_db_path_open(stack: str) -> tuple[bool, str]:
    """From tenant A's container, try to open a socket to the other database."""
    target = OTHER_TENANT_DB[stack]
    script = (
        "import socket,sys\n"
        f"s=socket.socket(); s.settimeout({PROBE_TIMEOUT_SECONDS})\n"
        "try:\n"
        f"    s.connect(('{target}',5432)); print('connected'); sys.exit(0)\n"
        "except Exception as e:\n"
        "    print(type(e).__name__+': '+str(e)); sys.exit(1)\n")
    result = compose(stack, "exec", "-T", "app-a", "python", "-c", script)
    detail = (result.stdout or result.stderr).strip().splitlines()[-1:] or [""]
    return result.returncode == 0, f"app-a -> {target}:5432 : {detail[0]}"


def probe_only_proxy_published(stack: str) -> tuple[bool, str]:
    """Read the real bindings rather than trusting the compose file."""
    result = compose(stack, "ps", "--format", "json")
    if result.returncode != 0:
        raise RuntimeError(f"docker compose ps failed: {result.stderr.strip()}")
    published = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        ports = row.get("Publishers") or []
        bound = [f"{p.get('URL') or '0.0.0.0'}:{p.get('PublishedPort')}"
                 for p in ports if p.get("PublishedPort")]
        if bound:
            published[row["Service"]] = sorted(set(bound))
    ok = set(published) == {"proxy"}
    return ok, f"published: {json.dumps(published, sort_keys=True) or '{}'}"


PROBES = {
    "cross_tenant_read": probe_cross_tenant_read,
    "token_replay": probe_token_replay,
    "db_path_open": probe_db_path_open,
    "only_proxy_published": probe_only_proxy_published,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack", required=True, choices=sorted(EXPECTED))
    args = parser.parse_args()
    expected = EXPECTED[args.stack]

    print(f"stack: {args.stack}\n")
    failures = 0
    for name, probe in PROBES.items():
        want = expected[name]
        try:
            got, detail = probe(args.stack)
        except Exception as exc:
            print(f"  ERROR  {name}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        mark = "ok  " if got == want else "FAIL"
        if got != want:
            failures += 1
        print(f"  {mark}   {name}: expected {want}, got {got}")
        print(f"           {detail}")

    print()
    if failures:
        print(f"{failures} probe(s) did not match what this stack claims")
        return 1
    print(f"all {len(PROBES)} probes match what this stack claims")
    return 0


if __name__ == "__main__":
    sys.exit(main())
