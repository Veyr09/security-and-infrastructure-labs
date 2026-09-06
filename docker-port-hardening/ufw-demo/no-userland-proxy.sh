#!/usr/bin/env bash
# Re-run the same publish with Docker's userland proxy turned off, so the
# published port is served by iptables DNAT + FORWARD instead of a host socket.
set -u
DOCKER="/usr/bin/docker -H unix:///var/run/docker.sock"
PORT=8080
NAME=ufwdemo

mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'JSON'
{ "userland-proxy": false }
JSON
systemctl restart docker
sleep 6

$DOCKER rm -f "$NAME" >/dev/null 2>&1
$DOCKER run -d --name "$NAME" -p "${PORT}:80" traefik/whoami:v1.10 >/dev/null
sleep 3

printf '\n===== docker port =====\n'
$DOCKER port "$NAME"
printf '\n===== host sockets on %s (expect none: no docker-proxy) =====\n' "$PORT"
ss -tlnp | grep ":${PORT}" || echo "(no host socket - the port is served by DNAT, not by a process)"
printf '\n===== ufw still denies it =====\n'
ufw status | grep 8080
printf '\n===== nat PREROUTING sends it to DOCKER before any filter INPUT rule =====\n'
iptables -t nat -S PREROUTING
iptables -t nat -S DOCKER | grep -- "--dport ${PORT}" || echo "(no nat DOCKER dnat rule)"
printf '\n===== filter DOCKER chain now has the accept rule =====\n'
iptables -S DOCKER | grep -- "--dport 80" || echo "(no DOCKER rule)"
