# wardrobe: project notes

Pi: `/home/claude/projects/wardrobe` (git repo, repo-local identity `claude <claude@pi>`).
PC mirror: `C:\pi-work\wardrobe`. How to use it: README.md. Original plan: PLAN.md (deviations below).

## Status log
- **2026-10-24: Stage 0 (audit) done.** Read-only; results at the bottom.
- **2026-10-24: Stage 1 (plan).** Approved by the user. Port 8484 OK; no login for now (LAN only);
  run stages 2–5 without stopping, but keep these notes current. NEEDS_ADMIN A1 (`libopenjp2-7`)
  was installed by the user.
- **2026-10-24: Stages 2–5 done.** venv + pinned deps; app with upload, URL import, browse/search/sort,
  edit, delete with confirmation, and editable categories; backup/restore/update; `pull-backups.sh`; README.
  36 tests pass on the Pi. Service `wardrobe.service` is running and enabled.
  Verified live: all pages, create→edit→delete, real-internet og:image extraction, SSRF block
  of 192.168.0.1 and 127.0.0.1:8443, backup + checksum, `./wardrobe.sh restore`, `pull-backups.sh`.
  One smoke-test backup (empty DB) exists: `backups/wardrobe-20261024-213616.tar.gz` (also on the PC).
- **Open:** whether the user wants a daily backup timer. URL import has only been tested against
  fixtures and non-store sites so far; the user should try real stores and send pages that fail.

## Key facts
- **URL:** `http://192.168.0.129:8484`. TCP 8484, bound to 192.168.0.129 only. No firewall changes.
- **Process:** systemd user unit `~/.config/systemd/user/wardrobe.service` (generated from
  `deploy/wardrobe.service` by `wardrobe.sh`). It runs `.venv/bin/python -m app serve` (uvicorn, 1 worker),
  with `ExecStartPre` running migrations. Restart=on-failure every 10 s, forever.
- **Stop:** `./wardrobe.sh stop`. **Remove:** `./wardrobe.sh remove` (unit only), then
  `rm -rf /home/claude/projects/wardrobe`.
- **Logs:** `./wardrobe.sh logs` (user journal works on this Pi). The access log is off.
- **Data:** `data/wardrobe.db` (SQLite, WAL) and `data/images/{orig,display,thumb}/<uuid>.*`;
  staged uploads in `data/staging/`; temp files in `data/tmp/` (TMPDIR for the service).
- No Docker; nothing is shared with matrix-hub.

## Memory (no memory cgroup on this Pi)
Measured on the Pi, 2026-10-24:
- Idle: RSS ~46–56 MB, virtual ~62–70 MB.
- Peak extra RSS while processing one upload: 24 MP JPEG +47 MB · 40 MP JPEG +92 MB ·
  6 MP WebP +94 MB · 8.4 MP RGBA PNG +73 MB · 4K screenshot PNG +51 MB.
  Worst case live: **VmHWM 144 MB**, VmPeak 206 MB. Memory returns to ~50 MB afterwards.
- How: JPEG `draft()` decodes at 1/2–1/8 scale (the request box must have the image's aspect ratio,
  or draft does nothing). Non-JPEG formats decode at full size, so they have pixel caps
  (PNG/GIF/other 8.5 MP, WebP 6 MP; Pillow's WebP decoder uses about 3× the pixel size). Alpha is
  flattened before resizing (Pillow's RGBA resize makes a premultiplied full-size copy), the source
  is freed before resampling, there is one image at a time (semaphore), the threadpool is 8,
  1 MB thread stacks, and MALLOC_ARENA_MAX=2.
- Safety net: `LimitAS=512M` (an rlimit, which works without cgroups). Override with
  `LIMIT_AS=… ./wardrobe.sh restart`.
- Bug found while measuring (fixed, regression-tested): re-encoded originals were saved under the old
  extension, leaving an orphan file. The startup cleanup now also removes unreferenced image files older than a day.

## Deviations from PLAN.md
- Display image is **1500 px**, not 1600, so a 3000 px JPEG original decodes at exactly 1/2.
- PNG/WebP originals are **kept as uploaded** (the pixel caps bound them). Only JPEGs over 3000 px and
  GIF/BMP/TIFF are re-encoded to JPEG.
- The pixel caps above (the plan said 40 MP for everything).
- `og:site_name` is **not** used as the brand: it's the store's name (e.g. "Zalando"), not the brand.
- Routes are in `app/routes/{items,add,categories}.py`. The domain logic is in `app/services/library.py`.
- Image downloads ask CDNs for JPEG first (cheap to decode), and the store preview image is loaded
  directly from the store in your browser for the confirmation step only. It's saved on the Pi when
  you continue.
- No `/api/...` endpoints for rembg yet (that's for later; the design is in PLAN.md §8).

## Versions (Python 3.9.2; full list in requirements.lock)
fastapi 0.128.8 · starlette 0.49.3 · pydantic 2.13.5 / pydantic-core 2.46.5 · sqlmodel 0.0.34 ·
SQLAlchemy 2.0.52 · alembic 1.16.5 · uvicorn 0.39.0 · python-multipart 0.0.20 · pillow 11.2.1 ·
httpx 0.28.1 · beautifulsoup4 4.15.0 · jinja2 3.1.6 · pytest 8.4.2 · htmx 2.0.4 (vendored,
sha256 e209dda5…fb447). These are the last releases for 3.9; newer ones need an OS upgrade (Bookworm).

## Backups
- `./wardrobe.sh backup` → `backups/wardrobe-YYYYMMDD-HHMMSS.tar.gz` + `.sha256`, keeps 7.
  Contents: DB snapshot (SQLite backup API), `images/orig/`, `manifest.json`. Gzip level 1.
  Display images and thumbnails are not included (they're rebuilt on restore).
- Expected size: ~1–2 MB per item (the original photo). 200 items ≈ 300 MB per backup, ≈ 2 GB for 7.
- Off-Pi: `bash C:\pi-work\wardrobe\pull-backups.sh` (manual), keeps 14 on the PC.
- Restore: `./wardrobe.sh restore FILE` (README). The old data is kept as `data.before-restore-*`.

## Security notes
- No login: anyone on the LAN or VPN can view and edit. The user accepted this for now. Basic auth via
  `.env` is easy to add.
- SSRF guard (`app/services/fetch.py`): http/https only; every resolved address must be public; every
  redirect hop is re-checked; max 5 redirects; 10 s timeout; 3 MB HTML / 20 MB image caps.
  Remaining gap: DNS could change between the check and the connect (DNS rebinding). That's
  acceptable for a LAN-only app.
- Uploads are capped at 20 MB by a middleware before parsing; Pillow's decompression-bomb guard is
  an error, not a warning.
- Templates are auto-escaped; the source URL must be http(s), so there are no `javascript:` links.

## Extension points (not built)
- **Color sorting:** `item_color` (rank, hex, share, Lab, hue) is filled on every upload.
- **Outfits:** the `outfit` and `outfit_item` tables exist (migration 0001). Deleting an item also
  removes its outfit links.
- **AI:** `app/services/ai.py` is the only place for Claude API calls (httpx + Messages API; key
  `ANTHROPIC_API_KEY` in `.env`, chmod 600, git-ignored). The stubs raise NotImplementedError.
- **Background removal:** `item.cutout_file` column; plan is rembg on the Windows PC (PLAN.md §8).

## Stage 0 audit (2026-10-24, read-only)
- **Python:** 3.9.2 (`/usr/bin/python3`), armhf userland on an aarch64 kernel.
- **venv:** `python3-venv` 3.9.2-3 is installed. **pip:** 20.3.4 system (24.3.1 in the venv).
- **piwheels:** set up in `/etc/pip.conf`.
- **Disk:** 59 GB root, 42 GB free. **RAM:** 7.6 GiB, ~6.3 GiB available; swap 99 MiB.
- **Lingering:** on for `claude`.
- **Tools:** git, curl present; `tmux`, `sqlite3` CLI, `/usr/bin/time` and `bc` missing (not needed).
- **Pillow libraries:** all present after A1 (`libopenjp2-7` 2.4.0-3+deb11u3).
- **Listening ports before wardrobe** (`ss -tlnu`):
  - TCP: 22, 80, 5335 + 8953 (127.0.0.1), 8443 (192.168.0.129, matrix-hub), 8581, 51761, 54096.
  - UDP: 5335, 5353, 36952, 38397, **<vpn-port>, <vpn-port> (VPN; never bind)**.
  - Added by wardrobe: **TCP 192.168.0.129:8484**.
