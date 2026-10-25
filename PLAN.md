# wardrobe: plan (Stage 1, 2026-10-24)

A small wardrobe tracker on the Pi, on the LAN only. Status: **approved 2026-10-24 and built.**
This is the plan as approved; where the build differs, see PROJECT_NOTES.md → "Deviations from PLAN.md".

## 1. Runtime: venv + systemd user service, no Docker (I agree with your recommendation)

- A Python venv at `/home/claude/projects/wardrobe/.venv`, built from the system Python 3.9 and
  `python3-venv` (both already installed).
- FastAPI runs under uvicorn with **one worker**, no `--reload`, no `[standard]` extras
  (uvloop/httptools add native code and save no memory).
- The service is `~/.config/systemd/user/wardrobe.service`. Lingering is already on, so it starts at boot
  and keeps running after logout. `Restart=on-failure`.
- **Why not Docker:** this app is one Python process with no system dependencies beyond one
  shared library. Docker would add an image, a seccomp profile and coupling to the rootless daemon
  that matrix-hub depends on. Leaving Docker out means a wardrobe problem can never affect the hub.
  (Also, `systemctl` over ssh needs your approval for each call under the permission rules, so
  `wardrobe.sh` will wrap `systemctl --user`. You approve those calls the same way you do for `hub.sh`.)

### Python 3.9 pins (checked against PyPI and piwheels on 2026-10-24)
The Pi has Python 3.9.2 (Bullseye). Many current releases now need Python 3.10 or newer. The pins below
are the newest releases that support 3.9 **and** have a cp39 armv7l wheel on piwheels where native code is involved:

| package | pin | note |
|---|---|---|
| fastapi | 0.128.8 | last for 3.9 (Feb 2026) |
| starlette | 0.49.3 | pulled in by fastapi |
| pydantic / pydantic-core | 2.13.5 / 2.46.5 | piwheels armv7l wheel exists, no Rust build |
| sqlmodel | 0.0.34 | |
| sqlalchemy | 2.0.52 | newest with an armv7l cp39 wheel |
| alembic | 1.16.5 | |
| uvicorn | 0.39.0 | |
| python-multipart | 0.0.20 | for uploads |
| pillow | 11.2.1 | newest armv7l cp39 wheel; **needs `libopenjp2-7`** (NEEDS_ADMIN A1) |
| httpx 0.28.1, beautifulsoup4 4.15, jinja2 3.1.6 | | pure Python |
| pytest 8.4.2 | | dev only |

All exact versions go in `requirements.lock`. For HTML parsing I'll use the built-in `html.parser`, not lxml.
A newer Python is possible later, but only after an OS upgrade to Bookworm, because piwheels builds wheels per Debian release.

## 2. Network
- **Port: TCP 8484, bound to 192.168.0.129 only.** URL: `http://192.168.0.129:8484`.
- Ports already in use, so I avoided them: TCP 22, 80, 5335, 8443 (hub), 8581, 8953, 51761, 54096; UDP 5335,
  5353, 36952, 38397, **<vpn-port> and <vpn-port> (VPN)**. Nothing in the firewall or routing changes.
- If 192.168.0.129 isn't up yet at boot, the bind fails and systemd retries every 10 s.
- **No login.** Anyone on your LAN or VPN could reach it. That's OK for a home LAN. HTTP basic auth
  from `.env` is a one-hour add-on if you want it (see Questions).

## 3. Memory: keeping it under ~150 MB without cgroups
Expected RSS is about 60–80 MB idle (Python + FastAPI + SQLAlchemy + Pillow).
- Uploads stream to disk in chunks and are capped at 20 MB. URL downloads are also streamed with a 20 MB cap,
  and the HTML fetch is capped at 3 MB.
- `Image.MAX_IMAGE_PIXELS` is set to about 40 MP, so decompression bombs are rejected.
- JPEGs use `Image.draft()`, so the decoder works at 1/2, 1/4 or 1/8 scale. A 24 MP photo becomes
  about 1.5 MP in memory before resizing.
- Image processing goes through a 1-slot semaphore, so only one image is decoded at a time.
- Color extraction runs on a 96 px copy.
- **Safety net:** systemd `LimitAS=` (an rlimit, not a cgroup, so it does work here) caps the process's
  address space. If something goes wrong, the process gets a MemoryError and restarts instead of eating the Pi's RAM.
  I'll measure the real virtual size in Stage 2 and set the cap with headroom (probably 1 GB, since 32-bit
  thread stacks reserve a lot of address space). The threadpool is limited to 8 threads.
- `./wardrobe.sh status` shows the current RSS.

## 4. Layout
```
wardrobe/
  app/
    main.py            FastAPI app, routes mounted here
    config.py          settings from .env (port, paths, limits)
    db.py, models.py   SQLModel tables
    routes/            items.py, categories.py, imports.py
    services/
      images.py        save, thumbnail, dominant colors (Pillow)
      extract.py       product-page extraction (httpx + bs4)
      colors.py        hex -> color name, Lab/hue for sorting later
      ai.py            single home for future Claude API calls (stub, not wired in)
    templates/         Jinja + HTMX partials
    static/            style.css, htmx.min.js (vendored, pinned; no CDN, no build)
  migrations/          Alembic
  tests/               fixtures/*.html, test_extract.py, test_items.py
  data/                wardrobe.db, images/{orig,display,thumb}/   (git-ignored)
  backups/             wardrobe-YYYYMMDD-HHMMSS.tar.gz + .sha256      (git-ignored)
  wardrobe.sh, requirements.lock, .env (chmod 600, git-ignored), .env.example
  README.md, PLAN.md, NEEDS_ADMIN.md, PROJECT_NOTES.md
```
On the PC, `C:\pi-work\wardrobe` mirrors the repo. `pull-backups.sh` copies backups into
`C:\pi-work\wardrobe\backups\`.

## 5. Data model (SQLite, Alembic from day one)
- **category**(id, name unique, sort_order): seeded with your 9 categories and editable on a Categories page.
  A category can only be deleted when it has no items (otherwise reassign the items first).
- **item**(id, name, category_id, subcategory, color_hex, color_name, brand, size, seasons, notes,
  source_url, image_file, image_sha256, width, height, cutout_file NULL, created_at, updated_at)
  - `subcategory` is free text, with autocomplete from values already used in that category.
    (A separate table felt heavy for an MVP. It's easy to promote later.)
  - `seasons` is a fixed set (spring/summer/autumn/winter/all), stored as a short comma list.
  - The primary color is pre-filled from the image's dominant color, with a name from a ~40-entry palette. You can override it.
- **tag**(id, name unique) + **item_tag**(item_id, tag_id): search matches tag names.
- **item_color**(item_id, rank, hex, share, lab_l, lab_a, lab_b, hue): top 5 colors from a k-means
  quantize, filled **on every upload now** so that sorting by color later needs no backfill.
- **outfit**(id, name, notes, occasion, season, created_at, source: manual|ai|photo-import) +
  **outfit_item**(outfit_id, item_id, position): created in the first migration but not used by the UI.
- Image files are named by UUID. Three copies are kept: the **original** as uploaded (for rembg later),
  a **display** JPEG (max 1600 px, EXIF orientation applied, metadata stripped) and a **thumb** WebP (400 px).

## 6. Features (MVP)
- **Browse** (`/`): thumbnail grid, category chips, a search box (name/brand/tag, live via HTMX
  with a 300 ms debounce), and sort by date added or name. Clean desktop CSS (grid, system font, no framework).
- **Add, photo:** upload, then the form opens pre-filled with the dominant color.
- **Add, URL:** paste a product URL, and the server tries in this order:
  1. `og:image` / `og:image:secure_url` / `twitter:image`
  2. JSON-LD `Product` (also handles inside `@graph`, lists, and `ImageObject`) for the image, name and `brand.name`
  3. the largest `<img>` by width/height attributes or `srcset`, skipping logos, sprites and icons
  The title comes from og:title, JSON-LD name or `<title>`. The brand comes from JSON-LD, `product:brand` or `og:site_name`.
  You see a **preview** (image, name, brand) and confirm before anything is saved. The image is then
  downloaded and stored locally.
  If a store blocks the request (403/429, a bot-check page, or no image found), you get a clear message
  ("This store blocked the request — paste the image URL or upload the photo instead") and an image-URL
  field plus an upload field on the same form. The source URL is kept in either case.
  - **SSRF guard:** the server only fetches http/https URLs whose host resolves to a **public** IP. It
    rejects 192.168.x, 10.x, VPN subnets, loopback and link-local addresses, and re-checks the address
    after every redirect (max 5), so a pasted link can't make the Pi talk to your router or the hub.
    Timeouts are 10 s, with a normal desktop-browser User-Agent.
- **Edit**, and **delete** after a confirmation step. Delete also removes the image files. The item's row in
  outfit_item, once outfits exist, is removed too.
- **Categories page:** rename, reorder, add, and delete when empty.

## 7. Control script `./wardrobe.sh`
| cmd | does |
|---|---|
| `start` / `stop` | `systemctl --user start/stop wardrobe` (installs/refreshes the unit file on first `start`) |
| `status` | unit state, URL, RSS, item count, last backup |
| `logs` | `journalctl --user -u wardrobe -n 200 -f` |
| `backup` | consistent SQLite snapshot (Python `sqlite3` backup API, safe while running) + `data/images` → `backups/wardrobe-<date>.tar.gz` + `.sha256`; keeps the newest 7 |
| `update` | backup, then `git pull` (if there's a remote; otherwise skip), `pip install -r requirements.lock`, `alembic upgrade head`, then restart and check health |
| `remove` | stop + disable + delete the unit file only. Data is kept; README says how to delete the folder |

**Restore** (documented and tested in Stage 5): stop, untar into `data/`, check sha256, start.
**`pull-backups.sh`** (PC, Git Bash): same pattern as matrix-hub. It copies new archives, verifies sha256 and keeps the newest 14.

## 8. Extension points (designed now, not built)
- **Color sorting:** `item_color` gets filled now. Later this is just an `ORDER BY hue, lab_l` and a palette filter.
- **Outfits:** tables exist from migration 1.
- **AI** (`app/services/ai.py`): the one module allowed to call the Claude API, via httpx and the Messages
  API, not the SDK (the current `anthropic` SDK may not support Python 3.9; I'll check when we build it).
  `ANTHROPIC_API_KEY` is read from `.env` (chmod 600, git-ignored). The functions are stubbed for
  `suggest_outfits(items, context)` and `items_from_outfit_photo(image)`, which sends a downscaled image.
  No models run on the Pi.
- **Background removal on the Windows desktop:** a later `C:\pi-work\wardrobe\desktop\cutouts.py` would use
  rembg on the PC (x86-64, so the wheels install normally). It asks the Pi which items have no cutout
  (`GET /api/items?missing=cutout`), downloads their originals, writes PNG cutouts, and uploads them back
  (`PUT /api/items/{id}/cutout`). The Pi just stores the file in `item.cutout_file`.

## 9. Tests
- `tests/fixtures/`: saved product pages with the private parts trimmed. I'll write representative fixtures
  for: og:image only, JSON-LD Product (plain and `@graph`), img-only with srcset, and a bot-block page.
  If you want real pages from stores you use, save them with Ctrl+S and I'll add them.
- `test_extract.py`: parser order, relative-to-absolute URLs, brand/title fallbacks, SSRF rejection of
  private IPs. No network access in tests.
- `test_items.py`: FastAPI TestClient against a temp DB and temp image folder. It covers uploading a
  generated image, checking the thumbnail and colors, editing, deleting with confirmation (files removed),
  search and the category filter.

## 10. Stages (I stop after each one with a report: what changed, port/process, how to stop)
- **0 Audit**: done (PROJECT_NOTES.md).
- **1 Plan**: this file. ⏸ your approval + NEEDS_ADMIN A1.
- **2 Skeleton:** venv, pinned deps, app + DB + first migration (all tables, seeded categories),
  health page on :8484, `wardrobe.sh start/stop/status/logs`, user service, RSS/VSZ measurement.
- **3 Items:** upload, image pipeline + colors, browse/search/sort, edit/delete, categories page, item tests.
- **4 URL import:** extraction + SSRF guard + fallback flow + fixture tests.
- **5 Ops:** backup/restore (tested), update, `pull-backups.sh`, README.
- **6 Hand-over:** final note.

## Questions for you
1. Is **port 8484** OK?
2. Do you want a **daily backup timer** (systemd user timer, e.g. 03:30) on top of the manual `./wardrobe.sh backup`?
   matrix-hub has one.
3. Should I add **basic auth** (a password in `.env`), or keep it open on the LAN?
4. Should I stop after every stage, or run stages 2–5 straight through and report once?
