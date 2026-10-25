#!/usr/bin/env bash
# Control script for the wardrobe app (systemd user service). Run on the Pi.
#   ./wardrobe.sh start|stop|restart|status|logs [-f]|backup|restore FILE|update|rebuild-images|test|remove
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

UNIT=wardrobe.service
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_DST="$UNIT_DIR/$UNIT"
TIMER=wardrobe-backup.timer
PY=.venv/bin/python
LIMIT_AS="${LIMIT_AS:-512M}"  # see PROJECT_NOTES.md "Memory"

url() { "$PY" -c 'from app.config import get_settings as g; s=g(); print(f"http://{s.host}:{s.port}")'; }

install_unit() {
  # Installs/refreshes the app service and the daily backup timer from deploy/.
  mkdir -p "$UNIT_DIR"
  local changed=0 tmp f
  for f in wardrobe.service wardrobe-backup.service wardrobe-backup.timer; do
    tmp=$(mktemp)
    sed -e "s|@DIR@|$PWD|g" -e "s|@LIMIT_AS@|$LIMIT_AS|g" "deploy/$f" > "$tmp"
    if ! cmp -s "$tmp" "$UNIT_DIR/$f" 2>/dev/null; then
      mv "$tmp" "$UNIT_DIR/$f"; changed=1
    else
      rm -f "$tmp"
    fi
  done
  [[ $changed == 1 ]] && systemctl --user daemon-reload
  systemctl --user enable -q "$UNIT"
  systemctl --user enable -q --now "$TIMER"
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
    systemctl --user start "$UNIT"
    wait_healthy ;;
  stop)
    systemctl --user stop "$UNIT"; echo "stopped" ;;
  restart)
    install_unit
    systemctl --user restart "$UNIT"
    wait_healthy ;;
  status)
    state=$(systemctl --user is-active "$UNIT" || true)
    echo "service: $state  ($(url))"
    pid=$(systemctl --user show -p MainPID --value "$UNIT")
    if [[ "$pid" != "0" ]]; then
      ps -o rss=,vsz= -p "$pid" | awk '{printf "memory: RSS %.0f MB, virtual %.0f MB\n", $1/1024, $2/1024}'
    fi
    curl -fsS -m 2 "$(url)/healthz" 2>/dev/null && echo || echo "health: not answering"
    last=$(ls -1 backups/wardrobe-*.tar.gz 2>/dev/null | tail -1 || true)
    echo "last backup: ${last:-none}"
    echo "next backup: $(systemctl --user show -p NextElapseUSecRealtime --value "$TIMER" 2>/dev/null || echo unknown)"
    du -sh data 2>/dev/null | awk '{print "data size: " $1}' ;;
  logs)
    shift
    journalctl --user -u "$UNIT" -n 200 --no-pager "$@" ;;
  backup)
    "$PY" -m app backup ;;
  restore)
    [[ -n "${2:-}" ]] || { echo "usage: $0 restore backups/wardrobe-YYYYMMDD-HHMMSS.tar.gz" >&2; exit 2; }
    was_active=$(systemctl --user is-active "$UNIT" || true)
    systemctl --user stop "$UNIT" || true
    "$PY" -m app restore "$2"
    if [[ "$was_active" == "active" ]]; then systemctl --user start "$UNIT"; wait_healthy; fi ;;
  update)
    "$PY" -m app backup
    if [[ -n "$(git remote)" ]]; then git pull --ff-only; else echo "no git remote; skipping pull"; fi
    .venv/bin/pip install -q --prefer-binary -r requirements.lock
    "$PY" -m app migrate
    install_unit
    systemctl --user restart "$UNIT"
    wait_healthy ;;
  rebuild-images)
    "$PY" -m app rebuild-images ;;
  test)
    "$PY" -m pytest -q tests ;;
  remove)
    systemctl --user disable --now "$TIMER" "$UNIT" 2>/dev/null || true
    rm -f "$UNIT_DST" "$UNIT_DIR/wardrobe-backup.service" "$UNIT_DIR/$TIMER"
    systemctl --user daemon-reload
    echo "service + backup timer removed. Data, backups and code are still in $PWD."
    echo "To delete everything: rm -rf $PWD" ;;
  *)
    sed -n '2,3p' "$0"; exit 2 ;;
esac
