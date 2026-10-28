"""Logging in from outside the home network, and the password and public address in Settings.
How it's checked is in services/auth.py; the gate is LoginRequired in main.py."""
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..services import auth
from ..templating import templates

router = APIRouter()


def safe_next(target: str) -> str:
    """Only paths on this site (never another site via //host or a backslash)."""
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


def _https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def _set_cookie(request: Request, response) -> None:
    response.set_cookie(auth.COOKIE, auth.make_cookie(), max_age=auth.MAX_AGE, httponly=True,
                        samesite="lax", secure=_https(request))


def _login_page(request: Request, *, next_url: str, error: str = "", status_code: int = 200):
    return templates.TemplateResponse(request, "login.html", {
        "next_url": next_url, "error": error, "ready": auth.has_password(),
    }, status_code=status_code)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    next_url = safe_next(next)
    if request.state.home or auth.signed_in(request.cookies.get(auth.COOKIE)):
        return RedirectResponse(next_url, status_code=303)
    return _login_page(request, next_url=next_url)


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, password: str = Form(""), next: str = Form("/")):
    next_url = safe_next(next)
    address = auth.client_address(request.client.host if request.client else "", request.headers)
    if not auth.has_password():
        return _login_page(request, next_url=next_url, status_code=403)
    if auth.too_many_tries(address):
        return _login_page(request, next_url=next_url, status_code=429,
                           error="Too many wrong passwords. Wait 15 minutes and try again.")
    if not auth.check_password(password):
        auth.record_failure(address)
        return _login_page(request, next_url=next_url, error="That password isn't right.",
                           status_code=401)
    auth.clear_failures(address)
    response = RedirectResponse(next_url, status_code=303)
    _set_cookie(request, response)
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE)
    return response


@router.post("/settings/password")
def save_password(request: Request, password: str = Form(""), confirm: str = Form("")):
    """Set or change the password. Only at home: the gate keeps guests out of Settings."""
    from .settings import render_settings_page  # settings imports nothing from here

    try:
        auth.set_password(password, confirm)
    except auth.AuthError as exc:
        return render_settings_page(request, access_error=str(exc))
    return RedirectResponse("/settings?access=1#access", status_code=303)


@router.post("/settings/password/remove")
def remove_password():
    """Turn outside access off (only at home, like every change in Settings)."""
    auth.remove_password()
    return RedirectResponse("/settings?access=1#access", status_code=303)
