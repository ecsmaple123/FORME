"""Category add / rename / reorder / delete. The list itself lives on the Settings page."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..db import get_session
from ..models import Category
from ..services import library
from ..services.library import UserError
from .settings import render_settings

router = APIRouter(prefix="/categories")
BACK = "/settings#categories"


def _category_or_404(session: Session, category_id: int) -> Category:
    category = session.get(Category, category_id)
    if category is None:
        raise HTTPException(404, "Category not found")
    return category


@router.get("")
def categories():
    """The old Categories page (bookmarks, history)."""
    return RedirectResponse(BACK, status_code=301)


@router.post("")
def add(request: Request, name: str = Form(""), session: Session = Depends(get_session)):
    try:
        library.save_category(session, name)
    except UserError as exc:
        return render_settings(request, session, error=str(exc), status_code=422)
    return RedirectResponse(BACK, status_code=303)


@router.post("/{category_id}")
def update(request: Request, category_id: int, name: str = Form(""),
           session: Session = Depends(get_session)):
    category = _category_or_404(session, category_id)
    try:
        library.save_category(session, name, category)
    except UserError as exc:
        session.rollback()
        return render_settings(request, session, error=str(exc), status_code=422)
    return RedirectResponse(BACK, status_code=303)


@router.post("/{category_id}/move")
def move(category_id: int, direction: str = Form(...), session: Session = Depends(get_session)):
    category = _category_or_404(session, category_id)
    library.move_category(session, category, -1 if direction == "up" else 1)
    return RedirectResponse(BACK, status_code=303)


@router.post("/{category_id}/delete")
def delete(request: Request, category_id: int, session: Session = Depends(get_session)):
    category = _category_or_404(session, category_id)
    try:
        library.delete_category(session, category)
    except UserError as exc:
        return render_settings(request, session, error=str(exc), status_code=422)
    return RedirectResponse(BACK, status_code=303)
