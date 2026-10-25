# wardrobe: project notes

Pi: `/home/claude/projects/wardrobe` (git repo, repo-local identity Forest Li <GitHub noreply>).
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
- 2026-10-24 — **Public on GitHub as FORME** (the user's account). The UI and README
  now say FORME; the folder, service, commands and data keep the name `wardrobe`. Commits are now made as
  the user (Forest Li, GitHub noreply email). GitHub gets a cleaned copy built on the PC by
  `C:\pi-work\sync-repos.sh` (redaction + leak check); this repo is unchanged.
- **2026-10-25: Background removal built** (user: "auto crops out only the clothing item part and
  removes everything else ... displayed like that ... apply this to existing images"). Details in
  "Background removal" below. User choices: the small model (u2netp, ~350 MB peak in a separate
  process, over the 150 MB guide for the app itself, which stays under it) and installing the system
  libraries with apt (NEEDS_ADMIN A2) rather than bundling them. Migration 0003 queues every existing
  photo. Tested on a copy of the real data (10 photos, all "done", ~11 s each) with the libraries
  unpacked into `.segtest/`; 59 tests pass. Went live the same night after the user ran A2: all 10
  existing photos done (~12 s each), pre-rollout backup `backups/wardrobe-20261025-014734.tar.gz`.
  The user checked the result: "everything looks good".
- **2026-10-25: Bookmark confirmed on real stores** (user: "the bookmark works fine"). No open items;
  if a store page ever fails, the user will send it. Server-side URL import still only tested on
  fixtures and non-store sites (stores like Loro Piana block the Pi; the bookmark covers them).
- **2026-10-25: Home page, settings and dark mode** (user: "aesthetically pleasing home screen ... a few
  featured items (random for now but later ... ai recommend them based on the weather and style), a welcome
  message and weather display (with icons ...) ... dark mode ... settings page"). Commit dfdcf2d, 72 tests.
  Details in "Home, weather, settings" below. Migration 0004 (`setting` table) ran live after backup
  `backups/wardrobe-20261025-022422.tar.gz`. Checked with headless Edge screenshots (light/dark,
  desktop/390 px). The user hasn't seen it yet, and no weather location is set on the live app (the user
  picks one in Settings).
  Lesson: copying templates into the Pi tree before restarting broke the live app for a few minutes
  (old code + new templates → 500). Test in a separate checkout or restart immediately.

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

## Background removal (cutouts)
- **What:** each photo gets a transparent WebP cutout cropped to the subject (`data/images/cutout/
  <cutout_file>.webp` + `.thumb.webp`, new name on each redo). Templates show it via `media_url`
  unless the photo's `show_cutout` is off. The original and its display/thumb files are never changed.
  Item colors come from the cover's cutout when it's shown.
- **States** (`item_photo.cutout_status`): pending → done | none (no subject between 2% and 95% of the
  frame) | failed (exception, logged). "Try again" / `./wardrobe.sh cutouts retry` re-queue.
- **Model:** U^2-Net-p (`models/u2netp.onnx`, 4.6 MB, Apache-2.0) from the rembg release, downloaded by
  `wardrobe.sh` with a pinned SHA-256; not in git. Run with OpenCV DNN at 320x320, then refined at
  full size (guided filter, contrast curve, backdrop-color cleanup, hole filling, 1-3 px trim, speck
  removal); see `app/services/cutout.py`.
- **Why this model:** rembg itself needs onnxruntime, which has no armhf wheel. Compared on the user's
  photos (PC): `isnet-general-use` (178 MB) had crisper raw edges but ran 87 s/photo and 924 MB on the
  Pi, and its input size is fixed at 1024; `silueta` is quantized and OpenCV can't load it. u2netp
  with the refinement looked as good on these product shots.
- **Gotchas found:**
  - armhf OpenCV has **no NEON** (Baseline empty), so inference is ~10 s on 4 cores.
  - OpenCV 4.x `net.forward()` with no name returns the **last** layer (U^2-Net's coarsest side
    output, a blurry blob). Ask for the first output by name (OpenCV 5 on the PC hid this).
  - piwheels `opencv-python-headless` 4.12 claims numpy>=2 but is linked against numpy 1.x; 4.11
    is consistent (numpy 1.26.4). 4.10 and older have no armhf cp39 wheel: pip **compiles them from
    source** (always use `--only-binary=:all:` when trying versions).
- **Process:** `wardrobe-cutout.service` (Nice 19, CPU+IO idle class, LimitAS 800M) runs
  `python -m app cutout-worker`: a stdlib-sqlite poll every 5 s. Work starts
  `python -m app cutout-batch`, which loads the model, processes all pending photos one at a time, and
  exits (peak 348 MB RSS / 530 MB virtual). If OpenCV or the model is missing it exits 3 and the
  watcher waits 10 min. The detail page polls `/items/{id}/photos/{pid}/cutout` every 4 s while pending.
- **Backups** don't include cutouts. After a restore, `rebuild-images` re-queues every photo whose
  cutout file is missing.
- **Limits:** a photo of someone wearing the item keeps the whole person. Garment-only segmentation
  needs a clothing model (~176 MB `u2net_cloth_seg`), too slow and too big for this Pi.

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

## Home, weather, settings
- `/` = home (`app/routes/home.py`); browse moved to `/browse`. `/weather` and `/picks?shuffle=1`
  are HTMX partials (the weather card loads after the page, so a slow API never delays it).
- **Weather:** `app/services/weather.py`, Open-Meteo geocoding + forecast (free, no key, HTTPS outbound
  from the Pi; only the coordinates are sent). In-process cache: 30 min, failures 5 min. WMO code →
  label + icon (night variants), plus a one-line hint by feels-like °C. °F/mph come from the API itself.
- **Prefs:** `app/services/prefs.py`, key/value table `setting` (name, theme, units, place, latitude,
  longitude, timezone), cached per engine. Validated on save (theme/units sets, finite in-range coords,
  known IANA zone or blank).
- **Dark mode:** CSS tokens in `style.css`; `<html data-theme=system|light|dark>`; "system" follows
  `prefers-color-scheme`. Photo tiles in dark mode use a lit gradient so dark garments stay visible.
- **Icons:** hand-drawn inline SVG macros in `templates/_icons.html` (colors from `--wx-*` tokens).
  Jinja gotcha: numbers need a leading zero (`0.62`, not `.62`).
- **Featured picks:** `app/services/featured.py` `pick(session, day, weather=None, ...)`: random, seeded by
  date (same picks all day), cutout items first. The `weather` argument is the hook for the planned
  AI recommender (weather + style); the home route doesn't pass weather yet.

## Extension points (not built)
- **AI picks:** replace the body of `featured.pick` (see above); route and templates already show `Picks.reason`.
- **Color sorting:** `item_color` (rank, hex, share, Lab, hue) is filled on every upload.
- **Outfits:** the `outfit` and `outfit_item` tables exist (migration 0001). Deleting an item also
  removes its outfit links.
- **AI:** `app/services/ai.py` is the only place for Claude API calls (httpx + Messages API; key
  `ANTHROPIC_API_KEY` in `.env`, chmod 600, git-ignored). The stubs raise NotImplementedError.

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
