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
- **2026-10-24: Daily backup timer added** at the user's request ("back up just like matrix is"):
  `wardrobe-backup.timer` at 04:45 (+ up to 10 min random, Persistent=true), running at Nice 15 with
  idle I/O, same pattern as matrix-hub's 04:15 timer, 30 min later so the two never overlap. A test run
  through the service succeeded (`backups/wardrobe-20261024-214327.tar.gz`, checksum OK).
- **2026-10-24: Loro Piana (ca.loropiana.com) returns HTTP 403** to the Pi. The app showed the fallback
  as designed. Trying browser-imitating headers to get past their bot protection was refused (bot-check
  circumvention), so that stays off the table. Proposed instead: an "Add to wardrobe" browser bookmark that reads
  image/name/brand from the page in the user's own browser. Waiting for the user's decision.
- **2026-10-24: Bookmark + multiple photos per item built** (user: "build it", plus "multiple photo per
  item, such as one product photo, one real photo"). Details in "Bookmark" and "Photos" below. Migration
  0002 moved each item's image into `item_photo`. It ran live on the user's first real item ("Light Green
  Cashmere Quarter Zip", added by the user at 21:48 via the image-URL fallback), which came through intact.
  The pre-migration backup is `backups/wardrobe-20261024-215727.tar.gz` (schema 0001). 47 tests pass; the
  bookmark JS was tested in Node against a fake product page (PC only; nothing built on the Pi).
  Live: 3× 24 MP JPEG in one upload peaked at 100 MB RSS (processed one at a time).
- 2026-10-24 — **Public on GitHub as FORME:** GitHub. The UI and README
  now say FORME; the folder, service, commands and data keep the name `wardrobe`. Commits are now made as
  the user (Forest Li, GitHub noreply email). GitHub gets a cleaned copy built on the PC by
  `C:\pi-work\sync-repos.sh` (redaction + leak check); this repo is unchanged.
- **Open:** URL import has only been tested against
  fixtures and non-store sites so far; the user should try real stores and send pages that fail.

## Key facts
- **URL:** `http://192.168.0.129:8484`. TCP 8484, bound to 192.168.0.129 only. No firewall changes.
- **Backups:** daily via `wardrobe-backup.timer` (04:45) → `wardrobe-backup.service` → `python -m app backup`.
- **Process:** systemd user unit `~/.config/systemd/user/wardrobe.service` (generated from
  `deploy/wardrobe.service` by `wardrobe.sh`). It runs `.venv/bin/python -m app serve` (uvicorn, 1 worker),
  with `ExecStartPre` running migrations. Restart=on-failure every 10 s, forever.
- **Stop:** `./wardrobe.sh stop` (the timer keeps backing up; `systemctl --user disable --now wardrobe-backup.timer` to pause it). **Remove:** `./wardrobe.sh remove` (service + timer units), then
  `rm -rf /home/claude/projects/wardrobe`.
- **Logs:** `./wardrobe.sh logs` (user journal works on this Pi). The access log is off.
- **Data:** `data/wardrobe.db` (SQLite, WAL) and `data/images/{orig,display,thumb}/<uuid>.*`;
  staged uploads in `data/staging/`; temp files in `data/tmp/` (TMPDIR for the service).
- No Docker; nothing is shared with matrix-hub.

## Bookmark ("Add to wardrobe")
- Source: `app/bookmarklet.js` (no `//` comments, every statement ends with `;`, because
  `app/bookmarklet.py` joins the lines and percent-encodes them into a `javascript:` URL). The app's address
  comes from the request (`request.base_url`), so the bookmark points wherever you opened the app.
- In the browser it reads og:image / twitter:image, JSON-LD Product images (also `@graph`, `hasVariant`), and
  the biggest rendered `<img>`s (≥200 px, no logo/icon/sprite), plus the name and brand. Then it opens
  `GET /add/bookmark?url=&title=&brand=&img=…` (max 10 images) in a new tab. That page only renders a
  preview (no side effects); `clean_image_urls` drops anything that isn't http(s).
- Why: some stores (Loro Piana) block the Pi. Getting past bot checks from the Pi is off-limits; the bookmark
  works on a page the user has already loaded normally. The Pi still downloads the image files themselves
  (SSRF guard applies). If the image server blocks too, the user uploads instead.
- After changing the JS: `node --check app/bookmarklet.js` on the PC, and drag the button to the bookmarks
  bar again (the old bookmark keeps the old code).

## Photos (multiple per item)
- Table `item_photo` (position 0 = cover, kind ∈ product|real|detail|other, image_file/ext/sha256/
  width/height, cutout_file). The image columns were removed from `item` in migration 0002.
- Item colors (`item_color`) always come from the cover. "Make cover" and deleting the cover
  recalculate them from the thumbnail. The primary color field the user edits is left alone.
- Limits: 12 photos per item, 6 per request, 20 MB per file, 60 MB per request (spooled to disk).
- Migrations run on their own SQLite connection with foreign keys **off** (`migrations/env.py`), because
  batch table rebuilds would otherwise cascade-delete child rows. A `PRAGMA foreign_key_check` runs after.

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
- Upload photo type defaults to *Real photo*; URL/bookmark imports default to *Product photo*.
- No `/api/...` endpoints for rembg yet (that's for later; the design is in PLAN.md §8).

## Versions (Python 3.9.2; full list in requirements.lock)
fastapi 0.128.8 · starlette 0.49.3 · pydantic 2.13.5 / pydantic-core 2.46.5 · sqlmodel 0.0.34 ·
SQLAlchemy 2.0.52 · alembic 1.16.5 · uvicorn 0.39.0 · python-multipart 0.0.20 · pillow 11.2.1 ·
httpx 0.28.1 · beautifulsoup4 4.15.0 · jinja2 3.1.6 · pytest 8.4.2 · htmx 2.0.4 (vendored,
sha256 e209dda5…fb447). These are the last releases for 3.9; newer ones need an OS upgrade (Bookworm).

## Backups
- Daily automatically at ~04:45 (`wardrobe-backup.timer`); `./wardrobe.sh status` shows the next run.
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
