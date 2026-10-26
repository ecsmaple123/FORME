"""Backup, restore and image rebuild (run via ./wardrobe.sh, not from the web app).

A backup is backups/wardrobe-YYYYMMDD-HHMMSS.tar.gz (+ .sha256) holding:
  wardrobe.db     consistent snapshot via SQLite's backup API (safe while the app runs)
  images/orig/    the photos: fit pictures as uploaded; item photos at display size once cut
                  out (photos cut out before 2026-10-26 have none until touched up).
                  Display + thumbnails are rebuilt on restore.
  images/cutout/  the cutouts (for older photos the only copy).
  images/mask/    what is the item in each item photo (edited by touch-ups).
  manifest.json   item count, schema revision, git commit
"""
import json
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List

from .config import PROJECT_DIR, get_settings
from .services.images import (compose_cutout, cutout_paths, mask_path, render_derivatives,
                              sha256_file)


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(PROJECT_DIR), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def list_backups() -> List[Path]:
    return sorted(get_settings().backup_dir.glob("wardrobe-*.tar.gz"))


def backup() -> Path:
    s = get_settings()
    s.ensure_dirs()
    name = f"wardrobe-{datetime.now():%Y%m%d-%H%M%S}.tar.gz"
    final = s.backup_dir / name
    partial = s.backup_dir / (name + ".partial")
    work = Path(tempfile.mkdtemp(dir=s.tmp_dir))
    try:
        snap = work / "wardrobe.db"
        src, dst = sqlite3.connect(str(s.db_path)), sqlite3.connect(str(snap))
        try:
            src.backup(dst)
            items = dst.execute("SELECT count(*) FROM item").fetchone()[0]
            revision = dst.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        finally:
            dst.close()
            src.close()
        manifest = work / "manifest.json"
        manifest.write_text(json.dumps({
            "created": datetime.now().isoformat(timespec="seconds"), "items": items,
            "schema_revision": revision, "app_commit": _git_commit(),
        }, indent=2))
        # JPEG/WebP don't compress further; level 1 keeps the Pi's CPU time low.
        with tarfile.open(partial, "w:gz", compresslevel=1) as tar:
            tar.add(manifest, arcname="manifest.json")
            tar.add(snap, arcname="wardrobe.db")
            tar.add(s.images_dir / "orig", arcname="images/orig")
            tar.add(s.images_dir / "cutout", arcname="images/cutout")
            tar.add(s.images_dir / "mask", arcname="images/mask")
        digest = sha256_file(partial)
        partial.rename(final)
        (s.backup_dir / (name + ".sha256")).write_text(f"{digest}  {name}\n")
    finally:
        shutil.rmtree(work, ignore_errors=True)
        partial.unlink(missing_ok=True)
    for old in list_backups()[:-s.backup_keep]:
        old.unlink(missing_ok=True)
        old.with_name(old.name + ".sha256").unlink(missing_ok=True)
    return final


def _safe_members(tar: tarfile.TarFile) -> List[tarfile.TarInfo]:
    members = []
    for m in tar.getmembers():
        parts = Path(m.name).parts
        ok_name = m.name in ("wardrobe.db", "manifest.json") or (
            parts[:2] in (("images", "orig"), ("images", "cutout"), ("images", "mask")) and ".." not in parts and not m.name.startswith("/"))
        if not ok_name or not (m.isfile() or m.isdir()):
            raise ValueError(f"Unexpected entry in backup: {m.name!r}")
        members.append(m)
    return members


def restore(archive: str) -> Path:
    """Replace data/ with the backup. The old data/ is kept as data.before-restore-<stamp>/.

    The service must be stopped first (./wardrobe.sh restore does that).
    """
    from .db import migrate, reset_engine

    s = get_settings()
    path = Path(archive).resolve()
    sums = path.with_name(path.name + ".sha256")
    if not sums.is_file():
        raise SystemExit(f"Missing {sums.name}; refusing to restore an unverified archive.")
    expected = sums.read_text().split()[0]
    if sha256_file(path) != expected:
        raise SystemExit("Checksum mismatch: the archive is damaged.")
    with tarfile.open(path, "r:gz") as tar:
        members = _safe_members(tar)
        if not any(m.name == "wardrobe.db" for m in members):
            raise SystemExit("The archive has no wardrobe.db.")
        incoming = s.data_dir.with_name(s.data_dir.name + ".restoring")
        shutil.rmtree(incoming, ignore_errors=True)
        incoming.mkdir(parents=True)
        tar.extractall(incoming, members=members)

    reset_engine()
    kept = None
    if s.data_dir.exists():
        kept = s.data_dir.with_name(f"{s.data_dir.name}.before-restore-{datetime.now():%Y%m%d-%H%M%S}")
        s.data_dir.rename(kept)
    incoming.rename(s.data_dir)
    (s.data_dir / "manifest.json").unlink(missing_ok=True)
    migrate()
    count = rebuild_images()
    print(f"Restored {path.name}: {count} item(s).")
    if kept:
        print(f"Previous data kept in {kept} (delete it once you're happy).")
    return s.data_dir


def rebuild_images() -> int:
    """Regenerate display + thumbnail files from the originals that are kept.

    A cutout whose files are missing (e.g. a backup from before cutouts were backed up) is made
    again from its mask, or queued for the cutout worker if there's only the original.
    """
    s = get_settings()
    s.ensure_dirs()
    con = sqlite3.connect(str(s.db_path))
    try:
        rows = con.execute("SELECT id, image_file, image_ext, cutout_status, cutout_file, "
                           "white_balance, touched_up FROM item_photo").fetchall()
        missing, recompose = [], []
        for pid, stem, ext, status, cutout, white_balance, touched_up in rows:
            has_cutout = bool(cutout) and cutout_paths(s.images_dir, cutout)["display"].is_file()
            if status == "done" and not has_cutout and _has_original(stem, ext):
                if mask_path(s.images_dir, stem).is_file():
                    recompose.append((pid, stem, white_balance, bool(touched_up)))
                else:
                    missing.append(pid)
        con.executemany("UPDATE item_photo SET cutout_status = 'pending' WHERE id = ?",
                        [(pid,) for pid in missing])
        con.commit()
    finally:
        con.close()
    if missing:
        print(f"queued {len(missing)} photo(s) for background removal")
    done = 0
    for pid, stem, ext, status, cutout, _wb, _t in rows:
        if _has_original(stem, ext):
            render_derivatives(s.images_dir, stem, ext)
            done += 1
        elif not (status == "done" and cutout
                  and cutout_paths(s.images_dir, cutout)["display"].is_file()):
            print(f"warning: photo {pid} has neither its original nor a cutout")
    if recompose:
        con = sqlite3.connect(str(s.db_path))
        try:
            for pid, stem, white_balance, by_hand in recompose:
                name = compose_cutout(s.images_dir, stem, white_balance, by_hand=by_hand)
                con.execute("UPDATE item_photo SET cutout_file = ?, cutout_status = ? WHERE id = ?",
                            (name, "done" if name else "none", pid))
            con.commit()
        finally:
            con.close()
        print(f"made {len(recompose)} cutout(s) again from their masks")
    return done


def _has_original(stem: str, ext: str) -> bool:
    return (get_settings().images_dir / "orig" / f"{stem}.{ext}").is_file()


def requeue_cutouts(everything: bool = False) -> int:
    """Queue photos for background removal: failed/none ones, or every one that can be redone.

    Fit pictures are never cut out, a photo can only be redone while its original is there
    (older photos have only their cutout), and photos touched up by hand are left alone.
    """
    con = sqlite3.connect(str(get_settings().db_path), timeout=10)
    try:
        states = ("failed", "none", "done") if everything else ("failed", "none")
        rows = con.execute("SELECT id, image_file, image_ext FROM item_photo WHERE kind != 'fit' AND NOT touched_up "
                           f"AND cutout_status IN ({', '.join('?' * len(states))})", states).fetchall()
        ids = [(pid,) for pid, stem, ext in rows if _has_original(stem, ext)]
        con.executemany("UPDATE item_photo SET cutout_status = 'pending' WHERE id = ?", ids)
        con.commit()
    finally:
        con.close()
    return len(ids)


def cutout_summary() -> str:
    con = sqlite3.connect(str(get_settings().db_path), timeout=10)
    try:
        rows = con.execute("SELECT cutout_status, count(*) FROM item_photo "
                           "GROUP BY cutout_status ORDER BY cutout_status").fetchall()
    finally:
        con.close()
    return "cutouts: " + (", ".join(f"{n} {status}" for status, n in rows) or "no photos")
