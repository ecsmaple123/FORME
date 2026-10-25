"""The password for visits from outside the home network (through the Cloudflare tunnel).

- At home (an address in WARDROBE_HOME_NET, not through the tunnel) no login is needed, as before.
- From anywhere else every page, photo and action needs the one shared password. Until a password
  is set in Settings, outside visits are refused.
- The tunnel (cloudflared on the Pi) connects from the Pi itself and adds Cf-* headers, so its
  requests never count as home, even though they come from a local address.
- The password is stored as a PBKDF2-SHA256 hash in the `setting` table. Being logged in is a
  signed cookie (30 days) whose signature also covers the hash: a new password logs everyone out.
- Wrong passwords: at most 5 per address and 20 in all per 15 minutes, then a wait.
"""
import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
from typing import Dict, List, Optional, Tuple

import httpx
from sqlmodel import Session

from ..config import get_settings
from ..db import get_engine
from ..models import Setting

COOKIE = "forme_auth"
MAX_AGE = 30 * 24 * 3600
MIN_LENGTH = 8
ITERATIONS = 150_000  # about 0.3 s on the Pi; slows down guessing
TUNNEL_HEADERS = ("cf-connecting-ip", "cf-ray", "cdn-loop")
WINDOW, PER_ADDRESS, OVERALL = 15 * 60, 5, 20

_lock = threading.Lock()
_cache: Dict[str, object] = {}  # {"engine": ..., "hash": str, "secret": str}, like prefs
_failures: Dict[str, List[float]] = {}


class AuthError(ValueError):
    """Shown to the user."""


def is_home(client_host: str, headers) -> bool:
    if any(h in headers for h in TUNNEL_HEADERS):
        return False
    try:
        ip = ipaddress.ip_address(client_host)
    except ValueError:
        return False
    s = get_settings()
    if ip.is_loopback or str(ip) == s.host:  # the Pi itself: that's where the tunnel connects from
        return False
    try:
        return ip in ipaddress.ip_network(s.home_net, strict=False)
    except ValueError:
        return False


def on_the_pi(client_host: str, headers) -> bool:
    """A request made on the Pi itself (e.g. wardrobe.sh), not one passed on by the tunnel."""
    return not any(h in headers for h in TUNNEL_HEADERS) and client_host in (
        "127.0.0.1", "::1", get_settings().host)


def client_address(client_host: str, headers) -> str:
    """Who to count wrong passwords against: the visitor's address as Cloudflare saw it."""
    return headers.get("cf-connecting-ip") or client_host or "?"


def _load() -> Tuple[str, str]:
    engine = get_engine()
    with _lock:
        if _cache.get("engine") is not engine:
            with Session(engine) as session:
                hashed = session.get(Setting, "auth_password")
                secret = session.get(Setting, "auth_secret")
                if secret is None:
                    secret = Setting(key="auth_secret", value=secrets.token_hex(32))
                    session.add(secret)
                    session.commit()
                    session.refresh(secret)
                _cache.update(engine=engine, hash=hashed.value if hashed else "", secret=secret.value)
        return _cache["hash"], _cache["secret"]


def _store(value: Optional[str]) -> None:
    with Session(get_engine()) as session:
        row = session.get(Setting, "auth_password")
        if value is None:
            if row is not None:
                session.delete(row)
        else:
            row = row or Setting(key="auth_password")
            row.value = value
            session.add(row)
        session.commit()
    with _lock:
        _cache.clear()


def has_password() -> bool:
    return bool(_load()[0])


def _hash(password: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def check_password(password: str) -> bool:
    stored = _load()[0]
    try:
        _, iterations, salt, _ = stored.split("$")
        return hmac.compare_digest(_hash(password, bytes.fromhex(salt), int(iterations)), stored)
    except ValueError:
        return False


def set_password(password: str, confirm: str) -> None:
    if len(password) < MIN_LENGTH:
        raise AuthError(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > 200:
        raise AuthError("That password is too long.")
    if password != confirm:
        raise AuthError("The two passwords don't match.")
    _store(_hash(password, secrets.token_bytes(16)))


def remove_password() -> None:
    _store(None)


def _sign(expires: int, hashed: str, secret: str) -> str:
    return hmac.new(secret.encode(), f"{expires}.{hashed}".encode(), hashlib.sha256).hexdigest()


def make_cookie() -> str:
    hashed, secret = _load()
    expires = int(time.time()) + MAX_AGE
    return f"{expires}.{_sign(expires, hashed, secret)}"


def signed_in(cookie: Optional[str]) -> bool:
    hashed, secret = _load()
    if not cookie or not hashed:
        return False
    expires, _, sig = cookie.partition(".")
    if not expires.isdigit() or int(expires) < time.time():
        return False
    return hmac.compare_digest(sig, _sign(int(expires), hashed, secret))


def _recent(key: str, now: float) -> List[float]:
    times = [t for t in _failures.get(key, []) if now - t < WINDOW]
    if times:
        _failures[key] = times
    else:
        _failures.pop(key, None)
    return times


def too_many_tries(address: str) -> bool:
    now = time.time()
    with _lock:
        return len(_recent(address, now)) >= PER_ADDRESS or len(_recent("*", now)) >= OVERALL


def record_failure(address: str) -> None:
    now = time.time()
    with _lock:
        for key in (address, "*"):
            _failures[key] = _recent(key, now) + [now]


def clear_failures(address: str) -> None:
    with _lock:
        _failures.pop(address, None)


def public_address() -> str:
    """The tunnel's https address (it changes when the tunnel restarts), or "" if it isn't running."""
    try:
        r = httpx.get(f"http://{get_settings().tunnel_metrics}/quicktunnel", timeout=1.0)
        host = r.json().get("hostname") or ""
    except (httpx.HTTPError, ValueError, AttributeError):
        return ""
    return f"https://{host}" if host else ""
