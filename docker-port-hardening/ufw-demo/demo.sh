#!/usr/bin/env bash
# Runs inside a Linux host with a native Docker daemon and ufw.
# Prints the state; the reachability probe is deliberately run from another
# machine, because a probe on this host proves nothing.
set -u
DOCKER="/usr/bin/docker -H unix:///var/run/docker.sock"
PORT=8080
NAME=ufwdemo

step() { printf '\n===== %s =====\n' "$1"; }

case "${1:-}" in
  expose)
    $DOCKER rm -f "$NAME" >/dev/null 2>&1
    $DOCKER run -d --name "$NAME" -p "${PORT}:80" traefik/whoami:v1.10 >/dev/null
    sleep 3
    step "docker port (published on every interface)"
    $DOCKER port "$NAME"
    step "listening sockets"
    ss -tlnp | grep ":${PORT}" || echo "(none)"
    ;;
  ufw-deny)
    step "enabling ufw and denying the port"
    ufw --force enable >/dev/null
    ufw deny "${PORT}/tcp" >/dev/null
    ufw status verbose | sed -n '1,12p'
    step "ufw's own chain: the DENY rule is present"
    iptables -S ufw-user-input | grep -- "--dport ${PORT}" || echo "(no ufw rule for ${PORT})"
    step "Docker's chain, which is consulted first"
    iptables -S DOCKER | grep -- "--dport 80" || echo "(no DOCKER rule)"
    step "where FORWARD sends packets, in order"
    iptables -S FORWARD
    ;;
  docker-user)
    step "the rule that DOES apply to container traffic"
    iptables -I DOCKER-USER -p tcp --dport "${PORT}" -j DROP
    iptables -S DOCKER-USER
    ;;
  undo-docker-user)
    iptables -D DOCKER-USER -p tcp --dport "${PORT}" -j DROP 2>/dev/null
    step "DOCKER-USER restored"
    iptables -S DOCKER-USER
    ;;
  rebind)
    step "recreating the container bound to loopback"
    $DOCKER rm -f "$NAME" >/dev/null 2>&1
    $DOCKER run -d --name "$NAME" -p "127.0.0.1:${PORT}:80" traefik/whoami:v1.10 >/dev/null
    sleep 3
    $DOCKER port "$NAME"
    step "listening sockets"
    ss -tlnp | grep ":${PORT}" || echo "(none)"
    ;;
  cleanup)
    $DOCKER rm -f "$NAME" >/dev/null 2>&1
    iptables -D DOCKER-USER -p tcp --dport "${PORT}" -j DROP 2>/dev/null
    ufw --force disable >/dev/null
    echo "cleaned up: container removed, DOCKER-USER rule removed, ufw disabled"
    ;;
  *)
    echo "usage: demo.sh {expose|ufw-deny|docker-user|undo-docker-user|rebind|cleanup}" >&2
    exit 2
    ;;
esac
