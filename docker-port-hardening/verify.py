"""Prove, from outside the host's loopback, whether a published port is exposed.

This is the deliverable a client actually pays for when they ask you to close a
port: not "I applied the change", but evidence that the port is unreachable from
somewhere other than the machine it runs on, and that the service they care
about still answers.

Checking from the server proves nothing. localhost always answers, so a probe
run there reports success whether the port is published on 0.0.0.0 or bound to
127.0.0.1. Every check below that matters uses a routable address instead.

Usage:
    python verify.py --app-port 8080 --proxy-port 8081
    python verify.py --app-port 8080 --proxy-port 8081 --json
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import urllib.error
import urllib.request

CONNECT_TIMEOUT_SECONDS = 3.0
HTTP_TIMEOUT_SECONDS = 5.0
LOOPBACK = "127.0.0.1"


def routable_address() -> str:
    """The host's own address on the network, which is not the loopback one.

    Uses a UDP socket so nothing is actually sent; connect() on UDP only picks
    the route, which is exactly the interface an outside caller would reach.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1, guaranteed not to be a real host
        return probe.getsockname()[0]
    finally:
        probe.close()


def tcp_reachable(host: str, port: int) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_SECONDS):
            return True, "connected"
    except OSError as error:
        return False, type(error).__name__


def http_body(host: str, port: int, path: str = "/") -> tuple[bool, str]:
    url = f"http://{host}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECONDS) as response:
            first_line = response.read(200).decode("utf-8", "replace").splitlines()
            return True, first_line[0] if first_line else ""
    except (urllib.error.URLError, OSError) as error:
        return False, type(error).__name__


def docker_publish_bindings(container: str) -> str:
    """What Docker says the publish is bound to. `docker port` is authoritative."""
    try:
        result = subprocess.run(
            ["docker", "port", container],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"unavailable ({type(error).__name__})"
    output = (result.stdout or result.stderr).strip()
    return output or "no published ports"


def run_checks(app_port: int, proxy_port: int, host: str | None = None) -> dict:
    # With no --host this probes the machine it runs on, via its own routable address
    # rather than loopback. On a client engagement it runs from a different machine and
    # --host names the server, which is the only arrangement that proves anything: a
    # check run on the box passes whether the port is bound to 0.0.0.0 or to loopback.
    outside = host or routable_address()

    if host:
        app_loopback_open, app_loopback_detail = (False, "skipped: probing a remote host")
    else:
        app_loopback_open, app_loopback_detail = tcp_reachable(LOOPBACK, app_port)
    app_outside_open, app_outside_detail = tcp_reachable(outside, app_port)
    proxy_outside_open, _ = tcp_reachable(outside, proxy_port)
    proxy_serves, proxy_first_line = http_body(outside, proxy_port)

    return {
        "routable_address": outside,
        "remote_host": host,
        "app_port": app_port,
        "proxy_port": proxy_port,
        "app_reachable_on_loopback": {"open": app_loopback_open, "detail": app_loopback_detail},
        "app_reachable_from_outside": {"open": app_outside_open, "detail": app_outside_detail},
        "proxy_reachable_from_outside": {"open": proxy_outside_open},
        "proxy_serves_app": {"ok": proxy_serves, "first_line": proxy_first_line},
        # Only meaningful when the containers are on this machine.
        "docker_publish_app": "n/a (remote host)" if host else docker_publish_bindings("hardening-app"),
        "docker_publish_proxy": "n/a (remote host)" if host else docker_publish_bindings("hardening-proxy"),
    }


def verdict(checks: dict) -> tuple[str, bool]:
    """Hardened means: not reachable from a routable address, but still served."""
    exposed = checks["app_reachable_from_outside"]["open"]
    served = checks["proxy_serves_app"]["ok"]
    if exposed and served:
        return "EXPOSED - the app port answers from a routable address", False
    if not exposed and served:
        return "HARDENED - app port refused from outside, proxy still serving", True
    if not exposed and not served:
        return "BROKEN - port is closed but the proxy no longer serves the app", False
    return "EXPOSED and proxy down - worst of both", False


def render(checks: dict) -> str:
    summary, _ = verdict(checks)
    outside = checks["routable_address"]
    lines = [
        "External port verification",
        "=" * 60,
        (f"Probing host                  : {outside} (from this machine)"
         if checks.get("remote_host") else
         f"Probing from routable address : {outside}"),
        f"Application port              : {checks['app_port']}",
        f"Proxy port                    : {checks['proxy_port']}",
        "",
        f"docker port hardening-app     : {checks['docker_publish_app']}",
        f"docker port hardening-proxy   : {checks['docker_publish_proxy']}",
        "",
        (f"app  on 127.0.0.1:{checks['app_port']:<6}      : not applicable "
         f"({checks['app_reachable_on_loopback']['detail']})"
         if checks.get("remote_host") else
         f"app  on 127.0.0.1:{checks['app_port']:<6}      : "
         f"{'OPEN' if checks['app_reachable_on_loopback']['open'] else 'refused'}"
         f" ({checks['app_reachable_on_loopback']['detail']})"),
        f"app  on {outside}:{checks['app_port']:<6} : "
        f"{'OPEN' if checks['app_reachable_from_outside']['open'] else 'refused'}"
        f" ({checks['app_reachable_from_outside']['detail']})",
        f"proxy on {outside}:{checks['proxy_port']:<6} : "
        f"{'OPEN' if checks['proxy_reachable_from_outside']['open'] else 'refused'}",
        f"proxy serves the app          : "
        f"{'yes' if checks['proxy_serves_app']['ok'] else 'no'}"
        f" ({checks['proxy_serves_app']['first_line']})",
        "",
        f"VERDICT: {summary}",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-port", type=int, required=True)
    parser.add_argument("--proxy-port", type=int, required=True)
    parser.add_argument("--host", help="probe this host instead of the machine this runs on; "
                                      "use it from a second machine on a real engagement")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    checks = run_checks(args.app_port, args.proxy_port, args.host)
    print(json.dumps(checks, indent=2) if args.json else render(checks))
    _, hardened = verdict(checks)
    return 0 if hardened else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
