#!/usr/bin/env bash
# Control script for the wardrobe app (systemd user service). Run on the Pi.
#   ./wardrobe.sh start|stop|restart|status|logs [-f]|cutout-logs [-f]|cutouts [retry|redo]|
#                 backup|restore FILE|update|rebuild-images|test|remove|
#                 password [set|remove]|tunnel on|off|status
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

UNIT=wardrobe.service
CUTOUT=wardrobe-cutout.service
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_DST="$UNIT_DIR/$UNIT"
TIMER=wardrobe-backup.timer
PY=.venv/bin/python
LIMIT_AS="${LIMIT_AS:-512M}"  # see PROJECT_NOTES.md "Memory"
CUTOUT_LIMIT_AS="${CUTOUT_LIMIT_AS:-800M}"  # a batch measured 530 MB virtual, 348 MB RSS
# Background-removal model (U^2-Net-p, Apache-2.0), as published by the rembg project.
MODEL=models/u2netp.onnx
MODEL_URL=https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx
MODEL_SHA256=309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8
# Public address (opt-in): Cloudflare's tunnel client, 32-bit ARM build, from its GitHub release.
TUNNEL=wardrobe-tunnel.service
CLOUDFLARED=tunnel/cloudflared
CLOUDFLARED_URL=https://github.com/cloudflare/cloudflared/releases/download/2026.10.3/cloudflared-linux-armhf
CLOUDFLARED_SHA256=458928ef2729ad71ebf7c88c289f9ecb2ac8bc6810a3bd4d70778592b9b4268b

url() { "$PY" -c 'from app.config import get_settings as g; s=g(); print(f"http://{s.host}:{s.port}")'; }

fetch_model() {
  [[ -f "$MODEL" ]] && return 0
  mkdir -p models
  echo "downloading the background-removal model (4.6 MB)…"
  curl -fsSL --retry 3 -o "$MODEL.part" "$MODEL_URL"
  if [[ "$(sha256sum "$MODEL.part" | cut -d' ' -f1)" != "$MODEL_SHA256" ]]; then
    rm -f "$MODEL.part"; echo "model checksum mismatch; not installed" >&2; return 1
  fi
  mv "$MODEL.part" "$MODEL"
}

install_unit() {
  # Installs/refreshes the app service, the cutout worker and the daily backup timer from deploy/.
  mkdir -p "$UNIT_DIR"
  fetch_model || echo "warning: background removal stays off until the model downloads" >&2
  local changed=0 tmp f
  for f in wardrobe.service "$CUTOUT" wardrobe-backup.service wardrobe-backup.timer; do
    tmp=$(mktemp)
    sed -e "s|@DIR@|$PWD|g" -e "s|@LIMIT_AS@|$LIMIT_AS|g" \
        -e "s|@CUTOUT_LIMIT_AS@|$CUTOUT_LIMIT_AS|g" "deploy/$f" > "$tmp"
    if ! cmp -s "$tmp" "$UNIT_DIR/$f" 2>/dev/null; then
      mv "$tmp" "$UNIT_DIR/$f"; changed=1
    else
      rm -f "$tmp"
    fi
  done
  [[ $changed == 1 ]] && systemctl --user daemon-reload
  systemctl --user enable -q "$UNIT" "$CUTOUT"
  systemctl --user enable -q --now "$TIMER"
}

fetch_cloudflared() {
  [[ -x "$CLOUDFLARED" ]] && return 0
  mkdir -p tunnel
  echo "downloading cloudflared (37 MB)…"
  curl -fsSL --retry 3 -o "$CLOUDFLARED.part" "$CLOUDFLARED_URL"
  if [[ "$(sha256sum "$CLOUDFLARED.part" | cut -d' ' -f1)" != "$CLOUDFLARED_SHA256" ]]; then
    rm -f "$CLOUDFLARED.part"; echo "cloudflared checksum mismatch; not installed" >&2; return 1
  fi
  chmod +x "$CLOUDFLARED.part" && mv "$CLOUDFLARED.part" "$CLOUDFLARED"
}

public_address() {
  curl -fsS -m 2 http://127.0.0.1:8487/quicktunnel 2>/dev/null     | "$PY" -c 'import json,sys; h=json.load(sys.stdin).get("hostname"); print("https://"+h if h else "")'     2>/dev/null || true
}

wait_healthy() {
  local u; u="$(url)"
  for _ in $(seq 1 30); do
    if curl -fsS -m 2 "$u/healthz" >/dev/null 2>&1; then echo "up: $u"; return 0; fi
    sleep 1
  done
  echo "not answering on $u after 30 s; see ./wardrobe.sh logs" >&2
  return 1
}

case "${1:-}" in
  start)
    install_unit
    systemctl --user start "$UNIT" "$CUTOUT"
    wait_healthy ;;
  stop)
    systemctl --user stop "$CUTOUT" "$UNIT"; echo "stopped" ;;
  restart)
    install_unit
    systemctl --user restart "$UNIT" "$CUTOUT"
    wait_healthy ;;
  status)
    state=$(systemctl --user is-active "$UNIT" || true)
    echo "service: $state  ($(url))"
    pid=$(systemctl --user show -p MainPID --value "$UNIT")
    if [[ "$pid" != "0" ]]; then
      ps -o rss=,vsz= -p "$pid" | awk '{printf "memory: RSS %.0f MB, virtual %.0f MB\n", $1/1024, $2/1024}'
    fi
    curl -fsS -m 2 "$(url)/healthz" 2>/dev/null && echo || echo "health: not answering"
    echo "cutout worker: $(systemctl --user is-active "$CUTOUT" || true); $("$PY" -m app cutouts)"
    last=$(ls -1 backups/wardrobe-*.tar.gz 2>/dev/null | tail -1 || true)
    echo "last backup: ${last:-none}"
    echo "next backup: $(systemctl --user show -p NextElapseUSecRealtime --value "$TIMER" 2>/dev/null || echo unknown)"
    du -sh data 2>/dev/null | awk '{print "data size: " $1}' ;;
  logs)
    shift
    journalctl --user -u "$UNIT" -n 200 --no-pager "$@" ;;
  cutout-logs)
    shift
    journalctl --user -u "$CUTOUT" -n 200 --no-pager "$@" ;;
  cutouts)
    # no argument: counts per state; retry: redo failed ones; redo: redo every photo
    "$PY" -m app cutouts ${2:-} ;;
  backup)
    "$PY" -m app backup ;;
  restore)
    [[ -n "${2:-}" ]] || { echo "usage: $0 restore backups/wardrobe-YYYYMMDD-HHMMSS.tar.gz" >&2; exit 2; }
    was_active=$(systemctl --user is-active "$UNIT" || true)
    systemctl --user stop "$CUTOUT" "$UNIT" || true
    "$PY" -m app restore "$2"
    if [[ "$was_active" == "active" ]]; then systemctl --user start "$UNIT" "$CUTOUT"; wait_healthy; fi ;;
  update)
    "$PY" -m app backup
    if [[ -n "$(git remote)" ]]; then git pull --ff-only; else echo "no git remote; skipping pull"; fi
    .venv/bin/pip install -q --prefer-binary -r requirements.lock
    "$PY" -m app migrate
    install_unit
    systemctl --user restart "$UNIT" "$CUTOUT"
    wait_healthy ;;
  rebuild-images)
    "$PY" -m app rebuild-images ;;
  test)
    "$PY" -m pytest -q tests ;;
  password)
    "$PY" -m app password ${2:-} || true ;;
  tunnel)
    case "${2:-status}" in
      on)
        "$PY" -m app password >/dev/null || { echo "set a password first (Settings > Outside access, or ./wardrobe.sh password set)" >&2; exit 1; }
        fetch_cloudflared
        mkdir -p "$UNIT_DIR"
        sed -e "s|@DIR@|$PWD|g" -e "s|@URL@|$(url)|g" "deploy/$TUNNEL" > "$UNIT_DIR/$TUNNEL"
        systemctl --user daemon-reload
        systemctl --user enable -q "$TUNNEL"
        systemctl --user restart "$TUNNEL"
        for _ in $(seq 1 30); do a=$(public_address); [[ -n "$a" ]] && break; sleep 1; done
        echo "public address: ${a:-not ready yet; try ./wardrobe.sh tunnel status in a minute}" ;;
      off)
        systemctl --user disable --now "$TUNNEL" 2>/dev/null || true
        echo "tunnel off: FORME is only reachable at home" ;;
      status)
        echo "tunnel: $(systemctl --user is-active "$TUNNEL" 2>/dev/null || true)"
        a=$(public_address); echo "public address: ${a:-none}" ;;
      *) echo "usage: $0 tunnel on|off|status" >&2; exit 2 ;;
    esac ;;
  remove)
    systemctl --user disable --now "$TUNNEL" "$TIMER" "$CUTOUT" "$UNIT" 2>/dev/null || true
    rm -f "$UNIT_DST" "$UNIT_DIR/$CUTOUT" "$UNIT_DIR/wardrobe-backup.service" "$UNIT_DIR/$TIMER" "$UNIT_DIR/$TUNNEL"
    systemctl --user daemon-reload
    echo "services + backup timer removed. Data, backups and code are still in $PWD."
    echo "To delete everything: rm -rf $PWD" ;;
  *)
    sed -n '2,3p' "$0"; exit 2 ;;
esac
