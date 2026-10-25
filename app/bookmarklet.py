"""Builds the "Add to FORME" bookmark (a javascript: URL) from app/bookmarklet.js.

The script runs in the user's own browser on a product page they already have open: it only
reads that page (image links, name, brand) and opens /add/bookmark on this app with them.
"""
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

SOURCE = Path(__file__).parent / "bookmarklet.js"


@lru_cache()
def bookmarklet(app_url: str) -> str:
    # The source avoids // comments and ends every statement with ";", so joining lines is safe.
    code = " ".join(line.strip() for line in SOURCE.read_text(encoding="utf-8").splitlines())
    code = code.replace("__APP__", app_url.rstrip("/"))
    return "javascript:" + quote(code, safe="")
