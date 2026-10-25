# wardrobe: project notes

Pi: `/home/claude/projects/wardrobe` (git repo). PC mirror: `C:\pi-work\wardrobe`.
Plan and reasoning: PLAN.md. Admin commands: NEEDS_ADMIN.md.

## Status log
- **2026-10-24: Stage 0 (audit) done.** Read-only; results below.
- **2026-10-24: Stage 1 (plan) written.** PLAN.md + NEEDS_ADMIN.md (A1: `libopenjp2-7`).
  Waiting for approval, A1, and answers to PLAN.md's questions. Nothing is installed or running yet.

## Key facts (planned)
- URL: `http://192.168.0.129:8484` (TCP 8484, bound to 192.168.0.129 only).
- Process: `wardrobe.service` (systemd **user** unit of `claude`), uvicorn with 1 worker, venv `.venv`.
- No Docker. Nothing shared with matrix-hub.

## Stage 0 audit (2026-10-24, read-only)
- **Python:** 3.9.2 (`/usr/bin/python3`), armhf userland on an aarch64 kernel (`sysconfig` platform
  says linux-aarch64, but dpkg arch and wheels are armhf/armv7l).
- **venv:** `python3-venv` 3.9.2-3 is installed, and `venv` + `ensurepip` import fine.
- **pip:** 20.3.4 (system). Will be upgraded inside the venv only.
- **piwheels:** set up in `/etc/pip.conf` (`extra-index-url=https://www.piwheels.org/simple`).
- **Disk:** 59 GB root, 42 GB free (27% used).
- **RAM:** 7.6 GiB total, ~6.3 GiB available; swap 99 MiB. The memory cgroup is off (per your brief).
- **Lingering:** on for `claude`. Existing user units: `docker.service`, `matrixhub-backup.{service,timer}`.
- **Tools:** git, curl present; `tmux` and `sqlite3` CLI missing (optional, not needed).
- **Pillow libraries:** liblcms2-2, libwebpdemux2, libwebpmux3, libjpeg62-turbo, libtiff5 are present;
  **libopenjp2-7 is missing**, see NEEDS_ADMIN A1.
- **Wheels (piwheels, cp39 armv7l):** pydantic-core 2.46.5, pillow 11.2.1, sqlalchemy 2.0.52 and
  markupsafe 3.0.2 all exist. Many current PyPI releases need Python ≥3.10, so versions are pinned
  (see PLAN.md §1).
- **Listening ports** (`ss -tlnu`):
  - TCP: 22 (ssh), 80, 5335 + 8953 (127.0.0.1, DNS resolver), 8443 (192.168.0.129, matrix-hub),
    8581, 51761, 54096 (owners not visible to `claude`).
  - UDP: 5335 (127.0.0.1), 5353 (mDNS), 36952, 38397, **<vpn-port>, <vpn-port> (VPN; never bind)**.
  - Chosen for wardrobe: **TCP 8484**, free.
