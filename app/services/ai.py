"""The only module allowed to call the Claude API. Not wired into the MVP yet.

Design notes for later:
- The key is read from .env (ANTHROPIC_API_KEY); .env is git-ignored and chmod 600.
- Calls go over httpx to the Messages API (the anthropic SDK may not support Python 3.9).
- Images sent for "import an outfit from a photo" should be the 1600 px display copy, not the original.
- No models ever run on the Pi.
"""
from typing import List

from ..config import get_settings


class AIUnavailable(RuntimeError):
    pass


def _api_key() -> str:
    key = get_settings().anthropic_api_key
    if not key:
        raise AIUnavailable("Set ANTHROPIC_API_KEY in .env to use AI features.")
    return key


def suggest_outfits(item_ids: List[int], context: str = "") -> list:
    """Future: return outfit proposals (lists of item ids + a short reason)."""
    _api_key()
    raise NotImplementedError


def items_from_outfit_photo(display_image_path: str) -> list:
    """Future: describe the garments in a photo so the user can add them as items."""
    _api_key()
    raise NotImplementedError
