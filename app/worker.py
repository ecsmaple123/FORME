"""Background removal worker (systemd user unit wardrobe-cutout.service).

`python -m app cutout-worker` is a tiny watcher: every few seconds it asks SQLite (stdlib only, a
few MB of RAM) whether any photo is waiting. If so it runs `python -m app cutout-batch`, a separate
process that loads numpy, OpenCV and the model (~285 MB), cuts out every waiting photo one at a
time, and exits so the memory is given back.

A cutout is made from the photo's display image (already rotated, at most 1500 px); the mask is
kept next to it and the original is shrunk to that display copy, so the cutout can be touched up
later (app.services.library.save_touchup). Fit pictures are never queued.
Photos deleted or changed while being processed are skipped and their new files removed.
"""
import logging
import sqlite3
import subprocess
import sys
import time
from typing import Callable, Optional

from PIL import Image
from sqlmodel import Session, select

from .config import get_settings
from .db import get_engine
from .models import Item, ItemPhoto
from .services import images

log = logging.getLogger("wardrobe.cutout")

POLL_SECONDS = 5
BACKOFF_SECONDS = 600  # after a batch that couldn't start (e.g. OpenCV libraries missing)
EXIT_UNAVAILABLE = 3


def has_pending(db_path) -> bool:
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
        try:
            return con.execute(
                "SELECT 1 FROM item_photo WHERE cutout_status = 'pending' LIMIT 1").fetchone() is not None
        finally:
            con.close()
    except sqlite3.Error:
        return False  # e.g. not migrated yet; try again on the next poll


def watch() -> int:
    """The long-running watcher (cutout-worker)."""
    db_path = get_settings().db_path
    log.info("watching %s for photos to cut out", db_path)
    while True:
        if has_pending(db_path):
            rc = subprocess.run([sys.executable, "-m", "app", "cutout-batch"]).returncode
            if rc != 0:
                log.warning("cutout batch exited with %s; retrying in %s s", rc, BACKOFF_SECONDS)
                time.sleep(BACKOFF_SECONDS)
                continue
        time.sleep(POLL_SECONDS)


def _pending_ids(session: Session) -> list:
    return list(session.exec(select(ItemPhoto.id).where(ItemPhoto.cutout_status == "pending")
                             .order_by(ItemPhoto.id)).all())


def process_photo(photo_id: int, segment: Callable) -> Optional[str]:
    """Cut out one photo and store the result. Returns the new status (None if the photo is gone)."""
    from .services.library import _recolor

    images_dir = get_settings().images_dir
    with Session(get_engine()) as session:
        photo = session.get(ItemPhoto, photo_id)
        if photo is None or photo.cutout_status != "pending":
            return None
        stem, ext, white_balance = photo.image_file, photo.image_ext, photo.white_balance

    new_name, status = None, "failed"
    try:
        with Image.open(images.paths(images_dir, stem)["display"]) as im:
            rgb = im.convert("RGB")
        alpha = segment(rgb)
        images.save_mask(images_dir, stem, alpha)
        new_name = images.save_cutout(images_dir, images.apply_white_balance(rgb, white_balance), alpha)
        status = "done" if new_name else "none"
    except Exception:  # one bad photo must not stop the queue
        log.exception("cutout failed for photo %s", photo_id)

    with Session(get_engine()) as session:
        photo = session.get(ItemPhoto, photo_id)
        if photo is None or photo.image_file != stem or photo.cutout_status != "pending":
            images.delete_files(images_dir, "", "", cutout=new_name)  # deleted/changed meanwhile
            return None
        old = photo.cutout_file
        photo.cutout_file = new_name
        photo.cutout_status = status
        if status == "done":
            photo.image_ext = images.keep_working_copy(images_dir, stem, ext)
        session.add(photo)
        session.flush()
        if photo.position == 0:
            _recolor(session, session.get(Item, photo.item_id))  # colors from the garment only
        session.commit()
    if old and old != new_name:
        images.delete_files(images_dir, "", "", cutout=old)
    return status


def run_batch(segmenter_factory: Optional[Callable] = None) -> int:
    """Process every waiting photo (cutout-batch). Returns the exit code."""
    with Session(get_engine()) as session:
        ids = _pending_ids(session)
    if not ids:
        return 0
    try:
        if segmenter_factory is None:
            from .services.cutout import Segmenter as segmenter_factory
        segment = segmenter_factory()
    except (ImportError, OSError) as exc:  # libraries or model missing: nothing can be done yet
        log.error("background removal unavailable: %s", exc)
        return EXIT_UNAVAILABLE
    done, tried = 0, set()
    while ids:
        for photo_id in ids:
            tried.add(photo_id)
            t0 = time.monotonic()
            status = process_photo(photo_id, segment)
            if status:
                done += 1
                log.info("photo %s: %s in %.1f s", photo_id, status, time.monotonic() - t0)
        with Session(get_engine()) as session:  # photos added while this batch ran
            ids = [i for i in _pending_ids(session) if i not in tried]
    log.info("batch finished: %s photo(s)", done)
    return 0
