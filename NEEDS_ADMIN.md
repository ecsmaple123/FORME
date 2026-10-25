# Commands that need you (sudo)

Claude has run none of these. Review each one, then run it as `pi`.
The project does **not** need the docker group.

## Done (A2)

**A2. Libraries for background removal**: installed by you on 2026-10-25.
```sh
sudo apt-get install --no-install-recommends libopenblas0 libatlas3-base libavcodec58 libavformat58 libswscale5
```
- **Why:** the cutout worker uses numpy and OpenCV from piwheels (`numpy-1.26.4`,
  `opencv_python_headless-4.11.0.86`, both `cp39 linux_armv7l`). Their wheels link against these system
  libraries: OpenBLAS for numpy, ATLAS (`libcblas.so.3`) and the FFmpeg libraries for OpenCV. Without
  them `import cv2` fails, and photos stay at "Removing background…".
- **What it is:** 66 standard Bullseye/Raspbian packages (~69 MB download), libraries only. A simulated
  install (`apt-get -s`) showed 0 removed, 0 upgraded. No services, no config, no network changes.
- **Check:** `dpkg -l libopenblas0 libatlas3-base libavcodec58 | grep ^ii` should list all three. Then
  tell Claude (or run `./wardrobe.sh restart`); the worker processes the waiting photos.
- Claude tested the exact same packages without installing them (unpacked into the project folder),
  so it's known to work: ~11 s per photo, peak 348 MB RSS, in a separate idle-priority process.

## Done

**A1. Install `libopenjp2-7`** (OpenJPEG runtime library): installed by you on 2026-10-24 (2.4.0-3+deb11u3).
```sh
sudo apt-get install --no-install-recommends libopenjp2-7
```
- **Why:** the piwheels Pillow wheel for armhf (`pillow-11.2.1-cp39-cp39-linux_armv7l`) links against
  `libopenjp2.so.7`. Without it, `from PIL import Image` fails with an ImportError. The wheel's other
  libraries (liblcms2-2, libwebpdemux2, libwebpmux3, libjpeg62-turbo, libtiff5) are already installed.
- **What it is:** one small shared library (~200 KB) from the Bullseye repo. It has no services, no config,
  no network changes, and nothing restarts.
- **Check:** `dpkg -l libopenjp2-7` should show `ii`.

## Not needed
- `python3-venv`, `pip` and piwheels (`/etc/pip.conf`) are already set up.
- Lingering for `claude` is already on (`Linger=yes`), so the user service survives logout and reboot.

## Optional (nice to have, not required)
```sh
sudo apt-get install --no-install-recommends sqlite3 tmux
```
- `sqlite3`: a CLI for poking at the database by hand. The app and backups don't need it, because they use Python's sqlite3 module.
- `tmux`: only useful for ad-hoc debugging. The app runs as a systemd user service.
