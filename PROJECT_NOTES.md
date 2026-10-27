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

- **2026-10-25: Closet, categories in Settings, fabric** (user: "Move categories to ... the settings page,
  ... create a new category during adding ... Change Browse to Closet, sort items by category ... choose the
  ordering from settings ... Remove brand from the preview cards. Add fabric ... auto update fabric from
  existing names then remove it from the names ... Add fabric to the card"). Commit 1f5d98f, 79 tests.
  Migration 0005 ran live after backup `backups/wardrobe-20261025-024455.tar.gz`; 7 of 10 names changed
  (e.g. "Cashmere Corduroy Peacoat" → Peacoat + Cashmere Corduroy; downgrade puts them back). Tested first in a
  separate checkout (`~/projects/wardrobe-next`, removed) with a preview on a copy of the real data.
  Brand stays on the item page, form and search; only the cards dropped it.

- **2026-10-25: Item photos vs fit pictures; only cutouts kept** (user: "The area below the photo in an
  item is too busy. Remove the background options. When uploading, automatically remove background ...
  We don't need to store the image with background. For multiple photo option, the only other category
  should be fit pictures ... if it's a fit picture, keep the background otherwise remove it automatically").
  Removed the type dropdown and the "Show with background"/"Remove background" switch from the item page;
  the bar under the photo now only appears with several photos (Cover badge, Make cover, Delete photo),
  for a fit picture (badge), or while/if background removal is pending/failed. Types are now Item photo
  and Fit picture. Migration 0006: real → fit (state skip), detail/other → product, drops `show_cutout`.
  The worker deletes the photo with its background once the cutout exists. Backups now include
  `images/cutout/` (otherwise a restore would lose every item photo). 82 tests. Ran live after backup
  `backups/wardrobe-20261025-133520.tar.gz` (the last one with the 10 originals); the live photos were all
  item photos with done cutouts, so their originals are now deleted. First backup with cutouts:
  `wardrobe-20261025-133537`. Tested first in `~/projects/wardrobe-next` on a copy of the real data.
- **2026-10-25: Take photo with the phone camera** (user: "use my phones camera to take the picture and
  automatically upload it"). `_camera.html` macro: a label-wrapped `<input type=file capture=environment
  accept=jpeg/png/webp>` that disables the form's other file fields (an empty file part gets a 422 from
  Starlette) and submits on change. On the Add page (first panel, "Take or upload photos") and in the
  item page's "+ Add photos". No HTTPS needed (getUserMedia would need it; a file input doesn't). iOS
  converts HEIC to JPEG because the accept list has no HEIC. 83 tests. Live after backup
  `wardrobe-20261025-135238`. Not yet tried on the user's phone.
- **2026-10-25: Color swatches removed** (user: "Remove the color swatch boxes, only keep the color field
  and one color either auto detected or user edited"). No swatches on the item page or the form; the form
  has one Color field (picker + hex + name). The auto color now follows the cover's cutout (`_recolor`,
  see Photos) until the user edits it. Existing items were left as they are (most names were already
  edited by the user, and the rest differ from the cutout color by a few RGB steps). 84 tests. Live after
  backup `wardrobe-20261025-143057`.
- **2026-10-25: Outfits page + Studio** (user: "an outfit page where I can browse saved outfits, it should
  be a single card with the clothing items selected ... a studio page where i can drag and drop outfits to
  come up with ideas, then save it to the outfit page"). Details in "Outfits and Studio". Migration 0007
  ran live after backup `wardrobe-20261025-150719`. 90 tests. No outfits saved on the live app yet.
  Possible next steps: "In outfits" on an item's page, AI outfit suggestions (`source = ai`).
- **2026-10-25: Tabs** (user: "make the tabs more aesthetic maybe with icons, then centre them"). Home,
  Closet, Outfits, Studio as icon tabs in a segmented pill centred in the header (grid 1fr auto 1fr),
  current page highlighted (`aria-current`; Closet also on /items/*); Settings + "+ Add" on the right. At
  ≤640 px the tabs become a fixed bottom tab bar (icon over label). Gotcha: the header's
  `backdrop-filter` makes it the containing block for `position: fixed` children, so it's switched off
  on phones. Checked with CDP screenshots (phone/tablet/desktop, light/dark). 91 tests. Live after backup
  `wardrobe-20261025-151513`.
- **2026-10-25: AI stylist (Gemini free tier)** (user: "I think we can go with gemini free, because I want
  it to be my stylist as well and remember picks I like and dislike"). Details in "Stylist (AI)". Stylist
  tab (5th tab; Studio's icon is now "layers"), AI Today's picks, likes/dislikes with notes, My style +
  photo switch + forget in Settings. 101 tests; checked in headless Edge (likes/notes swap in place,
  phone/desktop, light/dark) on a preview with seeded suggestions and a dummy key. Migration 0008 ran live
  after backup `wardrobe-20261025-164218`. Key added to the Pi's `.env` the same day (chmod 600,
  git-ignored). `gemini-3.8-flash` hung (0 bytes after 45 s) for this key, so the default became
  `gemini-3.5-flash` (~3 s); `gemini-3.5-flash-lite` (~1 s) is the fallback.
- **2026-10-25: Tell your stylist** (user: "somewhere on the stylist page for me to give direct feedback
  to the ai for it to remember"). A box under the ask form on /stylist: type, Remember, "Saved." The notes are never
  listed (user: "don't show me the notes, just save them cause it is just clutter"), so there's no
  delete in the UI; a newer note overrides an older one. Table `stylist_note`
  (migration 0009); the newest 50 go into every prompt, newest first, and the rules say newer notes win.
  "Forget my likes and dislikes" leaves them alone. 103 tests. Live after backup `wardrobe-20261025-175927`.
- **2026-10-25: 👎 removes the card** (user: "when i thumbs down a outfit it should be removed from the
  list. with option feedback"). On /stylist a dislike swaps the card for `_dismissed.html` ("Removed:
  title", Undo, optional "What didn't work?" note); `stylist.recent` skips disliked suggestions, which
  stay in the memory. Home's daily pick is unchanged (👎 there keeps the card with its note box). 104 tests.
- **2026-10-25: Outside access** (user: "I want anyone outside of my home internet be able to access it
  as long as they have a password"; chose a random trycloudflare address for now and one shared
  password). Login gate `LoginRequired` (main.py) + `services/auth.py` + `routes/auth.py`: home =
  WARDROBE_HOME_NET (192.168.0.0/24) and not via the tunnel (Cf-* headers) and not the Pi itself; else
  every path but /login, /static, /healthz needs the cookie `forme_auth` (30 days, HMAC over expiry +
  password hash, HttpOnly, SameSite=Lax, Secure over https). PBKDF2-SHA256 hash and the signing secret
  live in the `setting` table (`auth_password`, `auth_secret`), so they're in backups. Wrong
  passwords: 5 per address / 20 overall per 15 min (in memory). No password = outside refused.
  Settings > Outside access (set/change; remove only at home; log out away from home; shows the
  public address). CLI `./wardrobe.sh password [set|remove]`. VPN visitors log in too.
  Tunnel: `./wardrobe.sh tunnel on|off|status`, unit `wardrobe-tunnel.service` (opt-in, not in
  install_unit), cloudflared 2026.10.3 armhf in `tunnel/` (git-ignored, sha256-checked), `--protocol
  http2` (TCP only, outgoing), metrics 127.0.0.1:8487 (`/quicktunnel` gives the hostname). 115 tests.

- **2026-10-26: Capitalise each word** (user: "when I am typing on mobile, is it possible to captalize every
  word automatically? Like for brand and fabric"; "make sure it works for the color that gets autofilled
  too"). `autocapitalize="words"` on item name, brand, fabric, subcategory, colour, new category,
  Settings category names, Studio outfit name and import-preview name/brand (a keyboard hint: phones
  only, can still be overridden with Shift). Placed after `value=` because tests match
  `name=… value=…`. Auto colour names now come out title-cased (`nearest_color_name` → "Light Grey");
  `_recolor` compares names case-insensitively so old lowercase auto names still follow the cover.
  The 3 live lowercase names (charcoal, black, khaki) were title-cased after backup
  `wardrobe-20261026-130609`. 115 tests. Commits 46f1291, 775de66.

- **2026-10-26: Hex box updates the swatch** (user: "when i change the hex value in the field, the color
  preview doesnt update"). `oninput` on `#color_hex`: a full 6-digit code (# optional, any case) sets
  the picker and clears the colour name (re-detected on save), like the picker does; same colour keeps a
  typed name. Server adds a missing # (`validate`). Checked in headless Edge. 116 tests.

- **2026-10-26: Better cutouts and colours** (user: "sometimes an image doesnt get cut properly ... a few
  chinos still have some backgroud left on them ... Manual user cropping or something else? Also,
  sometimes the photo doesnt show the actual color of the items due to shadows/lighting"; then "can we
  do all of this?"; for colour chose "Both" (white balance tap + pick from photo)). Findings: the model
  keeps the floor between trouser legs; backdrop cleanup only ran for even backdrops. 19 of 20 items had
  a hand-picked colour (my first claim that the app's maths caused #754a00 etc. was wrong: those were
  the user's picks; the photos themselves have a warm cast).
  - Colour detection: clusters that are one fabric in light and shadow are merged; the colour is the
    median of the mid-tones (`images._merge_shades`, `_true_color`). New names Dark Navy/Olive/Brown/
    Green. `python -m app recolor` re-detects every item (typed colours stay; changed 1 item live).
  - Originals kept: item photos keep a display-size working copy (orig = display JPEG) + a mask
    (`images/mask/<stem>.png`); the cutout is display + mask + white balance (`compose_cutout`).
    Migration 0010 (`white_balance`, `touched_up`). Backups include `images/mask/`.
  - Touch up (`/items/{id}/photos/{pid}/touchup`, `touchup.js`): Erase area (tap; flood fill that
    follows gradual changes, then clears specks it nearly surrounds), Eraser, Restore, Lighting (tap
    white/grey: per-channel gains 0.5-2), Move, zoom, undo; Save posts the mask PNG + gains.
    Older photos are promoted from their cutout on first open (restore can only bring back what the
    cutout still has). Hand-edited photos are skipped by `cutouts redo`.
  - Pick from photo: button under Color on the item form; tap the form photo (9x9 average).
  - Floor patches (`cutout.floor_patches`): on photos without an even backdrop, large kept areas in
    the edge colours (not the item's) are removed. Guards: item colours must be well apart from the
    floor (else nothing), patches >= 0.4% of the photo, <= 35% of the item. Tried on the user's
    chinos rebuilt on their own floor texture: navy-on-white-bag cleaned, khaki fine, olive-on-grey-
    brown left alone (at a 50% limit it shredded the olive trousers, so the guards matter).
  - Checked in headless Edge on a preview (phone size): one tap removed the patches on the khaki and
    olive chinos, most of the navy one; lighting + save work. 131 tests.

- **2026-10-27: Studio tray as a board** (user: "i would like the studio page to not have names below  the items, kinda like a board with just everything on it"). The closet tray in /studio shows only the  cutouts on one shared tile surface (no names, no boxes; name kept as title/aria-label). Items on the  board get a soft highlight + accent dot. Phones: a wrapping 4-across grid (max 55vh, scrolls) instead  of the sideways strip. CSS + template only, no restart needed (bfb35db). 131 tests.  Backup before: wardrobe-20261027-161741.
## Where things stand (2026-10-25, end of session)
- Everything is live and committed. Code pushed up to FORME 80d6561; this notes update is on the Pi
  only (push with the next change). No open bugs.
- Running: `wardrobe.service` (TCP 192.168.0.129:8484), `wardrobe-cutout.service`,
  `wardrobe-backup.timer`, `wardrobe-tunnel.service` (outgoing only; 127.0.0.1:8487 metrics).
- Gemini key in `.env`; outside-access password set; tunnel on.
- Ideas the user may come back to: a domain for a fixed public address (Cloudflare named tunnel);
  what 👎 should do on Home's daily pick; per-person logins (they chose one shared password).

## Key facts
- **Outside access:** `./wardrobe.sh tunnel status` prints the current https://…trycloudflare.com
  address (changes on every tunnel restart). cloudflared metrics on 127.0.0.1:8487 (loopback only).
- **URL:** `http://192.168.0.129:8484`. TCP 8484, bound to 192.168.0.129 only. No firewall changes.
- **Backups:** daily via `wardrobe-backup.timer` (04:45) → `wardrobe-backup.service` → `python -m app backup`.
- **Process:** systemd user unit `~/.config/systemd/user/wardrobe.service` (generated from
  `deploy/wardrobe.service` by `wardrobe.sh`). It runs `.venv/bin/python -m app serve` (uvicorn, 1 worker),
  with `ExecStartPre` running migrations. Restart=on-failure every 10 s, forever.
- **Stop:** `./wardrobe.sh tunnel off` closes outside access only. `./wardrobe.sh stop` (the timer keeps backing up; `systemctl --user disable --now wardrobe-backup.timer` to pause it). **Remove:** `./wardrobe.sh remove` (service + timer units), then
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
- Table `item_photo` (position 0 = cover, kind ∈ product|fit since 0006, image_file/ext/sha256/
  width/height, cutout_file). The image columns were removed from `item` in migration 0002.
- Item colors (`item_color`) always come from the cover. "Make cover" and deleting the cover
  recalculate them from the thumbnail. They aren't shown (kept for color sorting later); the UI shows
  only the item's one color (`color_hex` + `color_name`). `_recolor` moves that to the new main color
  while it's still the auto-detected one (hex == old `item_color` rank 0 and name == its
  `nearest_color_name`) or empty; a color the user edited stays.
- Limits: 12 photos per item, 6 per request, 20 MB per file, 60 MB per request (spooled to disk).
- Migrations run on their own SQLite connection with foreign keys **off** (`migrations/env.py`), because
  batch table rebuilds would otherwise cascade-delete child rows. A `PRAGMA foreign_key_check` runs after.

## Background removal (cutouts)
- **What:** each item photo (kind `product`) gets a transparent WebP cutout cropped to the subject
  (`data/images/cutout/<cutout_file>.webp` + `.thumb.webp`, new name on each redo). Since 2026-10-26
  the worker keeps the mask (`images/mask/<stem>.png`) and shrinks the original to the display copy
  (orig = display JPEG, `image_ext` jpg) instead of deleting it; photos cut out before that have only
  their cutout until touched up. `media_url` serves the cutout for every size, "orig" included. Fit pictures (kind `fit`) are never cut out (state `skip`). Item colors come from
  the cover's cutout.
- **States** (`item_photo.cutout_status`): pending → done | none (no subject between 2% and 95% of the
  frame) | failed (exception, logged); skip = fit picture. "Try again" / `./wardrobe.sh cutouts retry`
  re-queue; `cutouts redo` re-queues photos whose original exists and that weren't touched up by
  hand; `rebuild-images` makes a missing cutout again from its mask (or re-queues it without one).
- **Backups include `images/cutout/`** since 0006 (it's the only copy of an item photo now). Older
  backups have only `images/orig/`; restoring one re-queues their cutouts.
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
- Routes are in `app/routes/{items,add,categories,settings,home}.py` (categories has no page of its own; Settings renders it). The domain logic is in `app/services/library.py`.
- Image downloads ask CDNs for JPEG first (cheap to decode), and the store preview image is loaded
  directly from the store in your browser for the confirmation step only. It's saved on the Pi when
  you continue.
- Photo types are only *Item photo* (`product`) and *Fit picture* (`fit`), chosen when adding; there's
  no way to change a photo's type afterwards (an item photo's background is gone by then). Uploads and
  imports default to *Item photo*; "+ Add photos" on an item defaults to *Fit picture*.
- No `/api/...` endpoints for rembg yet (that's for later; the design is in PLAN.md §8).

## Versions (Python 3.9.2; full list in requirements.lock)
fastapi 0.128.8 · starlette 0.49.3 · pydantic 2.13.5 / pydantic-core 2.46.5 · sqlmodel 0.0.34 ·
SQLAlchemy 2.0.52 · alembic 1.16.5 · uvicorn 0.39.0 · python-multipart 0.0.20 · pillow 11.2.1 ·
httpx 0.28.1 · beautifulsoup4 4.15.0 · jinja2 3.1.6 · pytest 8.4.2 · htmx 2.0.4 (vendored,
sha256 e209dda5…fb447). These are the last releases for 3.9; newer ones need an OS upgrade (Bookworm).

## Backups
- Daily automatically at ~04:45 (`wardrobe-backup.timer`); `./wardrobe.sh status` shows the next run.
- `./wardrobe.sh backup` → `backups/wardrobe-YYYYMMDD-HHMMSS.tar.gz` + `.sha256`, keeps 7.
  Contents: DB snapshot (SQLite backup API, includes settings, the password hash and stylist
  memory), `images/orig/` (fit pictures and photos not cut out yet), `images/cutout/` (the only copy
  of item photos since 2026-10-25), `manifest.json`. Gzip level 1. Display images and thumbnails
  are rebuilt on restore. Not included: `.env` (Gemini key) and `tunnel/` (re-downloaded).
- Size: small (cutouts are WebP); a few MB for the current ~12 items.
- Off-Pi: `bash C:\pi-work\wardrobe\pull-backups.sh` (manual), keeps 14 on the PC.
- Restore: `./wardrobe.sh restore FILE` (README). The old data is kept as `data.before-restore-*`.

## Security notes
- **Public since 2026-10-25** through the Cloudflare quick tunnel, behind one shared password (see the
  status log entry "Outside access"). At home (192.168.0.0/24, not via the tunnel) there's no login;
  VPN and tunnel visitors log in. The password was given in chat once; the user was told to change it.
  Wrong-password limits are in memory (reset on restart). Responses carry `X-Robots-Tag: noindex`.
- With the site public, these matter more: the free Gemini quota (only reachable after login) and
  the SSRF guard below (only after login).
- SSRF guard (`app/services/fetch.py`): http/https only; every resolved address must be public; every
  redirect hop is re-checked; max 5 redirects; 10 s timeout; 3 MB HTML / 20 MB image caps.
  Remaining gap: DNS could change between the check and the connect (DNS rebinding). Acceptable
  because only logged-in users can make the Pi fetch anything.
- Uploads are capped at 20 MB by a middleware before parsing; Pillow's decompression-bomb guard is
  an error, not a warning.
- Templates are auto-escaped; the source URL must be http(s), so there are no `javascript:` links.

## Home, weather, settings
- `/` = home (`app/routes/home.py`); the item list is `/closet` (`/browse` and `/categories` 301-redirect). `/weather` and `/picks?shuffle=1`
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

## Closet, categories, fabric
- Closet groups with `library.group_by_category` in `Category.sort_order` order; `move_category` swaps
  neighbours and renumbers 10, 20, …; new categories go last. With a category chip selected there is no grouping.
- Item form: category value `new` + `new_category` text → `find_or_add_category` (case-insensitive reuse,
  flushed only, so a form with other errors creates nothing).
- `app/services/fabric.py`: word list (garment-ish words like oxford/knit/mesh deliberately left out),
  `split_name` never empties a name. Used by migration 0005 and the add flow's name prefill.

## Outfits and Studio
- `app/services/outfits.py` (parse/validate the board JSON, save in place, list/get/delete) and
  `app/routes/outfits.py` (`/outfits`, `/outfits/{id}`, `/studio[?outfit=id]`, `POST /outfits`,
  delete with confirmation). Migration 0007 added `outfit_item.x/y/w` and `outfit.updated_at`.
- Board = 3:4 frame; per item x/y = top-left and w = width as fractions of the board, height from the
  photo; `position` = stacking order. `_board.html` renders it with percentages, so cards (thumbs) and
  the outfit page (display images) look the same at any size. Limits: 20 items, w 0.05–1.5,
  x/y −1–1.5 (clamped server-side).
- Saving replaces links **in place** by item_id: re-adding a removed (outfit_id, item_id) in the same
  flush would INSERT before DELETE and hit the primary key.
- `static/studio.js` (no build step): pointer events (mouse/touch/pen) for move + resize, tap to add,
  HTML5 drag-and-drop from the tray (mouse only), arrow keys/Delete on the focused board, unsaved
  new-outfit board in localStorage `forme-studio-draft`. Data comes in `<script type=application/json>`
  via `|tojson` (escapes `<`). Checked by driving headless Edge over CDP (touch taps, touch drag,
  handle resize, Back, save → redirect + draft cleared); the script is PC-only, not in the repo.
- Nav: see "Tabs" in the status log (Studio is a tab everywhere since then).

## Stylist (AI)
- Provider: Google Gemini API, free tier (user's choice 2026-10-25, after hearing that a Pi can't run a
  useful model and that Claude Pro doesn't include API use). `app/services/ai.py` is the only module
  that calls it: httpx POST to `v1beta/models/{GEMINI_MODEL}:generateContent` with header
  `x-goog-api-key`, JSON output via `responseMimeType` + `responseSchema` (uppercase types). Key
  `GEMINI_API_KEY` in `.env` (chmod 600, git-ignored, not in backups); model default
  `gemini-3.5-flash` (config.DEFAULT_GEMINI_MODEL; `gemini-3.5-flash-lite` is the lighter option).
  Errors → `AIError` with a user message (429 = free limit; RPD resets at midnight Pacific).
- `app/services/stylist.py`: prompt = SYSTEM rules + task + weather line + "My style" + memory (the
  user's direct notes from `stylist_note`, newest 50; last 30 liked and 30 disliked suggestions with notes, 20 latest *manual* outfits) + closet lines
  (`#id name | category / sub | colour | fabric | brand | seasons | tags | notes`) + cutout thumbs of
  item photos (≤60 items; `stylist_photos` pref). Never sent: name, location/coordinates, fit
  pictures, photos with background. Answers are validated: unknown/duplicate ids dropped, empty outfits
  dropped. Table `suggestion` (migration 0008) is the memory: source stylist|daily, day, replaced,
  request, weather, title, reason, item_ids, verdict ''|like|dislike, note, outfit_id (SET NULL).
- Home: without a key the picks are random and inline as before; with a key `/picks` is loaded after
  the page and calls `stylist.daily` (one per day under a lock; **Ask again** = `POST /picks/again`
  marks the old one replaced; on failure the current one stays, or random picks with the reason).
- Routes `app/routes/stylist.py`: `/stylist` (GET/POST, htmx adds cards; errors swap into
  `#stylist-error` out of band), `POST /suggestions/{id}/verdict` (where=stylist|picks; clicking the
  chosen button again clears it), `POST /suggestions/{id}/save` (auto layout, outfit source "ai",
  which is *not* fed back as the user's own taste), `/studio?suggestion=id`, `POST /settings/stylist`,
  `POST /stylist/forget`, `POST /stylist/notes` (htmx swaps the
  `#notes` form, template `_stylist_notes.html`). `outfits.auto_board` lays items out in two columns.
- Tests use a fake Gemini (MockTransport on `ai._client`); conftest blanks GEMINI_API_KEY so no test
  can reach the real API even if `.env` has a key.

## Extension points (not built)
- **Color sorting:** `item_color` (rank, hex, share, Lab, hue) is filled on every upload.

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
