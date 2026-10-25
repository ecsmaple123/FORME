"""Outfits (saved boards) and the Studio, where they're put together."""
import json
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from ..db import get_session
from ..services import library, outfits
from ..services.library import UserError
from ..templating import media_url, templates

router = APIRouter()


def _outfit_or_404(session: Session, outfit_id: int):
    outfit = outfits.get_outfit(session, outfit_id)
    if outfit is None:
        raise HTTPException(404, "Outfit not found")
    return outfit


def _studio(request: Request, session: Session, *, outfit=None, board=None, name: str = "",
            notes: str = "", error: str = "", status_code: int = 200):
    items = library.search_items(session)
    studio_data = {  # read by static/studio.js
        "items": {i.id: {"name": i.name, "src": media_url(i)} for i in items},
        "board": board if board is not None else outfits.board_json(outfit),
        "outfit": outfit.id if outfit else None,
        "max": outfits.MAX_ITEMS,
    }
    return templates.TemplateResponse(request, "studio.html", {
        "outfit": outfit, "error": error,
        "name": name or (outfit.name if outfit else ""),
        "notes": notes or (outfit.notes if outfit else ""),
        "placeholder": outfits.default_name(session),
        "categories": library.list_categories(session), "items": items,
        "studio": studio_data,
    }, status_code=status_code)


@router.get("/outfits", response_class=HTMLResponse)
def outfit_list(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "outfits.html", {
        "outfits": outfits.list_outfits(session),
    })


@router.get("/outfits/{outfit_id}", response_class=HTMLResponse)
def outfit_detail(request: Request, outfit_id: int, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "outfit_detail.html", {
        "outfit": _outfit_or_404(session, outfit_id),
    })


@router.get("/studio", response_class=HTMLResponse)
def studio(request: Request, outfit: Optional[int] = None, suggestion: Optional[int] = None,
           session: Session = Depends(get_session)):
    """The board starts empty (or with the browser's unsaved draft), with an outfit to edit, or
    with a stylist suggestion laid out (saved as a new outfit)."""
    if suggestion:
        from .stylist import suggestion_or_404, view
        v = view(session, suggestion_or_404(session, suggestion))
        return _studio(request, session, board=v.board, name=v.s.title, notes=v.s.reason)
    return _studio(request, session, outfit=_outfit_or_404(session, outfit) if outfit else None)


@router.post("/outfits")
def save(request: Request, layout: str = Form("[]"), name: str = Form(""), notes: str = Form(""),
         outfit_id: str = Form(""), as_new: str = Form(""),
         session: Session = Depends(get_session)):
    """Save the Studio board: a new outfit, or the outfit being edited (unless "Save as new")."""
    outfit = None
    if outfit_id.isdigit() and not as_new:
        outfit = _outfit_or_404(session, int(outfit_id))
    try:
        saved = outfits.save_outfit(session, outfit, name, notes, outfits.parse_layout(layout))
    except UserError as exc:
        try:
            board = json.loads(layout)
        except ValueError:
            board = []
        edited = _outfit_or_404(session, int(outfit_id)) if outfit_id.isdigit() else None
        return _studio(request, session, outfit=edited, board=board if isinstance(board, list) else [],
                       name=name, notes=notes, error=str(exc), status_code=422)
    return RedirectResponse(f"/outfits/{saved.id}?saved=1", status_code=303)


@router.get("/outfits/{outfit_id}/delete", response_class=HTMLResponse)
def delete_confirm(request: Request, outfit_id: int, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "confirm_delete_outfit.html", {
        "outfit": _outfit_or_404(session, outfit_id),
    })


@router.post("/outfits/{outfit_id}/delete")
def delete(outfit_id: int, session: Session = Depends(get_session)):
    outfits.delete_outfit(session, _outfit_or_404(session, outfit_id))
    return RedirectResponse("/outfits?deleted=1", status_code=303)
