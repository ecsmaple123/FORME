# wardrobe

A small wardrobe tracker for the home Pi: photos of your clothes, categories, colors, search.
FastAPI + SQLite + Jinja/HTMX, running as a systemd **user** service. No Docker, no build step.

- **URL:** http://192.168.0.129:8484. It's reachable on the LAN and over the VPN, and has no login.
- **Pi folder:** `/home/claude/projects/wardrobe` (git repo). **PC mirror:** `C:\pi-work\wardrobe`.
- Background, decisions and status log: `PROJECT_NOTES.md`. Original plan: `PLAN.md`.

## Using it
- **Add item → From a product link:** paste a store URL. The server looks for the main image
  (og:image, then JSON-LD Product, then the largest `<img>`), plus the name and brand, and shows a preview.
  If the store blocks it, use **Paste an image URL** (right-click the picture → *Copy image address*)
  or **Upload a photo**. Images are always downloaded and stored on the Pi.
- **Upload a photo:** JPEG up to 40 MP; PNG/GIF up to 8.5 MP; WebP up to 6 MP; 20 MB max file size.
  For iPhone HEIC, export as JPEG first.
- The primary color is pre-filled from the photo (white backgrounds are ignored). Click a swatch or
  use the picker to change it.
- **Browse:** category chips, search (name, brand, tag) and sort.
- **Categories:** rename, reorder, add, and delete when empty.

## Control (on the Pi, in the project folder)
| command | what it does |
|---|---|
| `./wardrobe.sh start` | install/refresh the user unit, start, wait for the health check |
| `./wardrobe.sh stop` / `restart` | stop / restart the service |
| `./wardrobe.sh status` | state, memory, item count, last backup, data size |
| `./wardrobe.sh logs` (add `-f` to follow) | last 200 log lines (`journalctl --user -u wardrobe`) |
| `./wardrobe.sh backup` | dated archive in `backups/`, keeps the newest 7 |
| `./wardrobe.sh restore FILE` | restore an archive (see below) |
| `./wardrobe.sh update` | backup → `git pull` (if there's a remote) → pip install → migrate → restart |
| `./wardrobe.sh rebuild-images` | regenerate display images and thumbnails from the originals |
| `./wardrobe.sh test` | run the test suite |
| `./wardrobe.sh remove` | stop + disable + delete the unit file (data and code stay) |

The service starts at boot (lingering is on for `claude`) and restarts if it crashes.

## Backups
`./wardrobe.sh backup` writes `backups/wardrobe-YYYYMMDD-HHMMSS.tar.gz` plus a `.sha256` file. Each archive holds:
- `wardrobe.db`: a consistent SQLite snapshot (safe while the app runs)
- `images/orig/`: the original photos (display images and thumbnails are rebuilt on restore)
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
(The Pillow wheel needs `libopenjp2-7`; see NEEDS_ADMIN.md.)

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
./wardrobe.sh remove                  # service gone; nothing listens on 8484
rm -rf /home/claude/projects/wardrobe # also deletes data and backups (pull backups first!)
```

## Development
- Tests: `./wardrobe.sh test`. They cover URL extraction against `tests/fixtures/*.html` with no network,
  the SSRF guard, add/edit/delete/search, the image pipeline, and backup/restore.
- To add a real store page as a fixture: save it in the browser (Ctrl+S, HTML only) into `tests/fixtures/`,
  then add a case to `tests/test_extract.py`.
- Schema changes: edit `app/models.py`, then add a migration in `migrations/versions/` (Alembic).
  `python -m app migrate` runs at every service start.
