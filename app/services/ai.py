"""The only module that calls an AI model: the Gemini API (free tier), over httpx.

- The key is GEMINI_API_KEY in .env (git-ignored, chmod 600, not in backups); GEMINI_MODEL picks
  the model. No models ever run on the Pi: a request is a few KB of text plus small WebP photos.
- On the free tier Google may use what is sent to improve its products, and people may review it.
  So callers send only clothing details, the weather and cutout photos: never the user's name,
  location or fit pictures (see app/services/stylist.py).
- `generate_json` asks for JSON matching a schema and returns it parsed; errors come back as
  AIError with a message for the user.
"""
import base64
import json
from dataclasses import dataclass
from typing import List, Optional, Union

import httpx

from ..config import get_settings

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TIMEOUT = httpx.Timeout(90.0, connect=10.0)


class AIUnavailable(RuntimeError):
    """No API key set up."""


class AIError(RuntimeError):
    """The request failed; the message is shown to the user."""


@dataclass
class Image:
    mime: str
    data: bytes


def available() -> bool:
    return bool(get_settings().gemini_api_key)


def model() -> str:
    return get_settings().gemini_model


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False)


def _part(p: Union[str, Image]) -> dict:
    if isinstance(p, Image):
        return {"inlineData": {"mimeType": p.mime, "data": base64.b64encode(p.data).decode("ascii")}}
    return {"text": p}


def _error_message(resp: httpx.Response) -> str:
    try:
        return str(resp.json()["error"]["message"])[:300]
    except (ValueError, KeyError, TypeError):
        return resp.text[:300]


def generate_json(system: str, parts: List[Union[str, Image]], schema: dict,
                  temperature: float = 0.9) -> dict:
    key = get_settings().gemini_api_key
    if not key:
        raise AIUnavailable("Add GEMINI_API_KEY to .env to use the stylist.")
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [_part(p) for p in parts]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema,
                             "temperature": temperature},
    }
    try:
        with _client() as client:
            resp = client.post(URL.format(model=model()), json=body,
                               headers={"x-goog-api-key": key})
    except httpx.TimeoutException:
        raise AIError("The stylist took too long to answer. Try again in a minute.")
    except httpx.HTTPError:
        raise AIError("Couldn't reach the stylist (Gemini). Check the Pi's internet connection.")
    if resp.status_code == 429:
        raise AIError("The free Gemini limit is used up for now. Try again later; the daily "
                      "limit resets at midnight Pacific time.")
    if resp.status_code in (401, 403):
        raise AIError("Gemini refused the API key. Check GEMINI_API_KEY in .env.")
    if resp.status_code == 404:
        raise AIError(f"Gemini doesn't know the model “{model()}”. Check GEMINI_MODEL in .env.")
    if resp.status_code >= 500:
        raise AIError("Gemini is having trouble right now. Try again in a minute.")
    if resp.status_code != 200:
        raise AIError(f"Gemini rejected the request: {_error_message(resp)}")
    return _parse(resp)


def _parse(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
        candidate: Optional[dict] = (data.get("candidates") or [None])[0]
        if not candidate or not candidate.get("content"):
            reason = (candidate or {}).get("finishReason") or \
                (data.get("promptFeedback") or {}).get("blockReason") or "no answer"
            raise AIError(f"The stylist gave no answer ({reason}). Try rephrasing.")
        text = "".join(p.get("text", "") for p in candidate["content"].get("parts", []))
        return json.loads(text)
    except (ValueError, AttributeError, TypeError):
        raise AIError("The stylist's answer couldn't be read. Try again.")
