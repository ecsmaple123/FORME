"""Command line: python -m app {serve|migrate|backup|restore FILE|rebuild-images|cleanup|
cutout-worker|cutout-batch|cutouts [retry|redo]}"""
import logging
import sys
import threading


def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else "serve"
    if cmd == "serve":
        # 32-bit userland: the default 8 MB thread stacks eat address space quickly.
        threading.stack_size(1024 * 1024)
        import uvicorn

        from .config import get_settings

        s = get_settings()
        uvicorn.run("app.main:app", host=s.host, port=s.port, workers=1, access_log=False,
                    proxy_headers=False, server_header=False, log_level="info")
        return 0
    if cmd == "migrate":
        from .db import migrate

        migrate()
        return 0
    if cmd in ("backup", "restore", "rebuild-images"):
        from . import ops

        if cmd == "backup":
            print(ops.backup())
        elif cmd == "restore":
            if len(argv) < 3:
                print("usage: python -m app restore BACKUP.tar.gz", file=sys.stderr)
                return 2
            ops.restore(argv[2])
        else:
            print(f"rebuilt {ops.rebuild_images()} item(s)")
        return 0
    if cmd == "cleanup":
        from .services.library import cleanup_staging

        print(f"removed {cleanup_staging()} staged upload(s)")
        return 0
    if cmd in ("cutout-worker", "cutout-batch"):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        from . import worker

        return worker.watch() if cmd == "cutout-worker" else worker.run_batch()
    if cmd == "cutouts":
        from . import ops

        action = argv[2] if len(argv) > 2 else ""
        if action not in ("", "retry", "redo"):
            print("usage: python -m app cutouts [retry|redo]", file=sys.stderr)
            return 2
        if action:
            print(f"queued {ops.requeue_cutouts(everything=action == 'redo')} photo(s)")
        print(ops.cutout_summary())
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
