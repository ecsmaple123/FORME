#!/usr/bin/env bash
# Run on the PC (Git Bash): copies wardrobe backups from the Pi that aren't here yet,
# verifies their checksums, and keeps the newest $KEEP locally (default 14).
set -euo pipefail
cd "$(dirname "$0")"
KEEP="${KEEP:-14}"
REMOTE=/home/claude/projects/wardrobe/backups
mkdir -p backups
for b in $(ssh pi "ls -1 $REMOTE | grep -E '^wardrobe-[0-9]{8}-[0-9]{6}\.tar\.gz$'" 2>/dev/null); do
  [[ -f "backups/$b" ]] && continue
  scp -q "pi:$REMOTE/$b" "backups/$b.partial" 2>/dev/null
  scp -q "pi:$REMOTE/$b.sha256" "backups/$b.sha256" 2>/dev/null
  expected=$(cut -d' ' -f1 "backups/$b.sha256")
  actual=$(sha256sum "backups/$b.partial" | cut -d' ' -f1)
  if [[ "$expected" != "$actual" ]]; then
    echo "checksum mismatch for $b; not kept" >&2
    rm -f "backups/$b.partial" "backups/$b.sha256"
    continue
  fi
  mv "backups/$b.partial" "backups/$b"
  echo "pulled $b"
done
ls -1 backups/wardrobe-*.tar.gz 2>/dev/null | head -n -"$KEEP" | while read -r old; do
  rm -f "$old" "$old.sha256"
done
echo "Local backups: $(ls -1 backups/wardrobe-*.tar.gz 2>/dev/null | wc -l) in $(pwd)/backups"
