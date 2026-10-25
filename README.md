# FORME

A self-hosted wardrobe tracker for a Raspberry Pi. Photograph or import your clothes, give each item
several photos, and browse by category, color, season and tag. Add items from a store page with a
link or a one-click bookmark.
FastAPI + SQLite + Jinja/HTMX, running as a systemd **user** service. No Docker, no build step.
(The folder, service and commands are still called `wardrobe`.)

- **URL:** http://192.168.0.129:8484. It's reachable on the LAN and over the VPN, and has no login.
- **Pi folder:** `/home/claude/projects/wardrobe` (git repo). **PC mirror:** `C:\pi-work\wardrobe`.
- Background, decisions and status log: `PROJECT_NOTES.md`. Original plan: `PLAN.md`.

## Using it
- **"Add to FORME" bookmark** (best for stores that block links, e.g. Loro Piana): on *Add item*,
  drag the **+ Add to FORME** button to your bookmarks bar (Ctrl+Shift+B shows the bar). On a product
  page, click the bookmark. It runs in your own browser on the page you have open, collects the product
  images, name and brand, and opens the app so you can tick which photos to keep. It sends nothing
  anywhere except to this app. If the store's image server refuses the Pi, upload the photo instead.
- **Add item → From a product link:** paste a store URL. The server looks for the main image
  (og:image, then JSON-LD Product, then the largest `<img>`), plus the name and brand, and shows a preview.
  If the store blocks it, use **Paste an image URL** (right-click the picture → *Copy image address*)
  or **Upload a photo**. Images are always downloaded and stored on the Pi.
- **Several photos per item** (up to 12), each either an *Item photo* or a *Fit picture* (chosen when
  you add it). The first one is the **cover** (grid thumbnail, and the item's colors come from it). On an
  item's page: click a thumbnail to view it, **+ Add photos** (upload or image URL), **Make cover**, or
  **Delete photo…** (with a confirmation; the last photo can't be deleted). Up to 6 photos can be added at once.
- **Background removal:** every item photo's background is removed automatically: the item is cut out on
  a transparent background and cropped to it. It happens about 15 s after you add the photo; the item
  page shows *Removing background…* and updates itself. Only the cutout is kept; the photo with its
  background is deleted. **Fit pictures keep their background** and are never cut out. If no clear item is
  found (e.g. a fabric close-up), the photo stays as uploaded and **Try again** is offered. Item colors
  are taken from the cutout, so the backdrop doesn't count.
- **Take photo** (Add page, and "+ Add photos" on an item): on a phone it opens the camera and the photo
  uploads as soon as you take it; on a computer it's a file picker. Works over plain http on the LAN.
- **Upload photos:** JPEG up to 40 MP; PNG/GIF up to 8.5 MP; WebP up to 6 MP; 20 MB max file size.
  For iPhone HEIC, export as JPEG first. Up to 60 MB per upload in total.
- **Color:** one color per item, detected from the cover photo (from its cutout once the background is
  removed) and kept up to date until you change it with the picker, the hex code or the name.
- **Studio** (`/studio`; on a phone via *Outfits → + New in Studio*): tap items in the closet tray
  (or drag them in on a computer) to put them on a board, drag to arrange, resize with the round handle
  or −/+, *Front*/*Back* to layer, then save with a name and notes. An unsaved new board is kept in
  your browser until you save or clear it.
- **Outfits** (`/outfits`): every saved outfit as one card showing its items as arranged in the Studio.
  An outfit's page lists its items, with *Edit in Studio* (save changes or *Save as new*) and *Delete…*.
  Deleting an item takes it off any outfit.
- **Stylist** (AI, Google Gemini free tier; optional): on the Stylist tab say what you're dressing for
  and get 3 outfits from your closet for today's weather. 👍 / 👎 each one (and say why), **Save as
  outfit** or **Edit in Studio**. With the stylist set up, *Today's picks* on Home is its outfit of the
  day (made once a day; **Ask again** for another). It remembers your likes, dislikes and notes, the
  outfits you saved yourself, and *My style* in Settings; Settings can also make it forget.
  Setup: get a key at https://aistudio.google.com/apikey, put `GEMINI_API_KEY=…` in `.env`, then
  `./wardrobe.sh restart`. Gemini gets your clothes' details, the weather, your requests and feedback
  and (switchable) the cutout photos; never your name, location or fit pictures. On the free tier
  Google may use this to improve its products.
- **Home:** a greeting, today's weather (once a location is set) with a what-to-wear hint, four
  featured picks (random for now, the same all day; **Shuffle** for new ones) and recently added items.
- **Settings** (gear icon): categories, your name for the greeting, **Appearance** (System / Light / Dark),
  °C or °F, and the weather location (search a town, click the right one). Weather comes from
  Open-Meteo (free, no account); only the location's coordinates are sent.
- **Closet** (`/closet`, was Browse): items grouped by category in your order, with category chips,
  search (name, fabric, brand, tag) and a sort that applies within each category. Cards show the name
  and fabric.
- **Categories** (in Settings): rename, move up/down (this is the closet order), add, and delete when
  empty. While adding or editing an item, pick **+ New category…** in the Category list to create one.
- **Fabric:** its own field (with suggestions). When an item comes from a store link or the bookmark,
  fabric words are taken out of the name ("Cashmere Overcoat" → name *Overcoat*, fabric *Cashmere*).

## Control (on the Pi, in the project folder)
| command | what it does |
|---|---|
| `./wardrobe.sh start` | install/refresh the user units (and download the cutout model), start, wait for the health check |
| `./wardrobe.sh stop` / `restart` | stop / restart the app and the cutout worker |
| `./wardrobe.sh status` | state, memory, item count, cutouts per state, last backup, data size |
| `./wardrobe.sh logs` (add `-f` to follow) | last 200 log lines (`journalctl --user -u wardrobe`) |
| `./wardrobe.sh cutout-logs` (add `-f`) | the background-removal worker's log |
| `./wardrobe.sh cutouts` / `cutouts retry` / `cutouts redo` | cutout counts / redo failed ones / also redo those whose original is still there |
| `./wardrobe.sh backup` | dated archive in `backups/`, keeps the newest 7 |
| `./wardrobe.sh restore FILE` | restore an archive (see below) |
| `./wardrobe.sh update` | backup → `git pull` (if there's a remote) → pip install → migrate → restart |
| `./wardrobe.sh rebuild-images` | regenerate display images and thumbnails from the kept originals |
| `./wardrobe.sh test` | run the test suite |
| `./wardrobe.sh remove` | stop + disable + delete the service and backup-timer units (data and code stay) |

`start`/`restart` also install and enable the cutout worker (`wardrobe-cutout.service`) and the daily backup timer. The service starts at boot (lingering is on for `claude`) and restarts if it crashes.

## Backups
A backup runs **every day at about 04:45** (`wardrobe-backup.timer`, 30 min after matrix-hub's).
`./wardrobe.sh status` shows the next run. `./wardrobe.sh backup` makes one now. Each run writes `backups/wardrobe-YYYYMMDD-HHMMSS.tar.gz` plus a `.sha256` file. Each archive holds:
- `wardrobe.db`: a consistent SQLite snapshot (safe while the app runs)
- `images/cutout/`: the cutouts (for item photos this is the only copy: the original isn't kept)
- `images/orig/`: the photos kept as uploaded (fit pictures, and any photo whose background isn't
  removed yet); display images and thumbnails are rebuilt from them on restore
- `manifest.json`: item count, schema revision and git commit

The newest 7 are kept. To copy them to the PC, run this in Git Bash:
```sh
bash /c/pi-work/wardrobe/pull-backups.sh      # verifies checksums, keeps the newest 14 (KEEP=n to change)
```

### Restore
```sh
./wardrobe.sh restore backups/wardrobe-20261024-213616.tar.gz
```
This stops the service, verifies the checksum, moves the current `data/` to
`data.before-restore-<time>/`, unpacks the archive, runs migrations, rebuilds the display images and
thumbnails, and starts the service again. Delete the `data.before-restore-*` folder once you're happy.
To restore an archive from the PC, `scp` the archive **and** its `.sha256` into `backups/` first.

**On a fresh Pi:** clone or copy the repo, then run
`python3 -m venv .venv && .venv/bin/pip install -r requirements.lock` and `./wardrobe.sh restore …`.
(The Pillow wheel needs `libopenjp2-7`, and background removal needs the libraries in A2; see NEEDS_ADMIN.md.)

## Change the port or address
Create `.env` (copy `.env.example`; keep it `chmod 600`):
```
WARDROBE_PORT=8485
```
Then run `./wardrobe.sh restart`. Never use 8443 (matrix-hub) or the VPN UDP ports (<vpn-port>, <vpn-port>);
check `ss -tlnu` first. Keep `WARDROBE_HOST` set to the LAN address. Don't use 0.0.0.0.

## Update
Commit any changes on the Pi (`git commit`), or pull them from a remote, then run `./wardrobe.sh update`.
Dependencies are pinned in `requirements.lock`. These are the last releases that support the Pi's Python 3.9,
from armhf wheels on piwheels. Don't raise a pin without checking for a `cp39 … armv7l` wheel on piwheels.

## Stop / remove completely
```sh
./wardrobe.sh remove                  # services gone; nothing listens on 8484
rm -rf /home/claude/projects/wardrobe # also deletes data and backups (pull backups first!)
```

## Development
- Tests: `./wardrobe.sh test`. They cover URL extraction against `tests/fixtures/*.html` with no network,
  the SSRF guard, add/edit/delete/search, the image pipeline, and backup/restore.
- To add a real store page as a fixture: save it in the browser (Ctrl+S, HTML only) into `tests/fixtures/`,
  then add a case to `tests/test_extract.py`.
- Schema changes: edit `app/models.py`, then add a migration in `migrations/versions/` (Alembic).
  `python -m app migrate` runs at every service start.
