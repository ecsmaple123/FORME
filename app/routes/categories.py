from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from ..db import get_session
from ..models import Category
from ..services import library
from ..services.library import UserError
from ..templating import templates

router = APIRouter(prefix="/categories")


def _page(request: Request, session: Session, error: str = "", status_code: int = 200):
    return templates.TemplateResponse(request, "categories.html", {
        "categories": library.list_categories(session),
        "counts": library.category_counts(session),
        "error": error,
    }, status_code=status_code)


def _category_or_404(session: Session, category_id: int) -> Category:
    category = session.get(Category, category_id)
    if category is None:
        raise HTTPException(404, "Category not found")
    return category


@router.get("", response_class=HTMLResponse)
def categories(request: Request, session: Session = Depends(get_session)):
    return _page(request, session)


@router.post("")
def add(request: Request, name: str = Form(""), sort_order: int = Form(1000),
        session: Session = Depends(get_session)):
    try:
        library.save_category(session, name, sort_order)
    except UserError as exc:
        return _page(request, session, str(exc), 422)
    return RedirectResponse("/categories", status_code=303)


@router.post("/{category_id}")
def update(request: Request, category_id: int, name: str = Form(""), sort_order: int = Form(0),
           session: Session = Depends(get_session)):
    category = _category_or_404(session, category_id)
    try:
        library.save_category(session, name, sort_order, category)
    except UserError as exc:
        session.rollback()
        return _page(request, session, str(exc), 422)
    return RedirectResponse("/categories", status_code=303)


@router.post("/{category_id}/delete")
def delete(request: Request, category_id: int, session: Session = Depends(get_session)):
    category = _category_or_404(session, category_id)
    try:
        library.delete_category(session, category)
    except UserError as exc:
        return _page(request, session, str(exc), 422)
    return RedirectResponse("/categories", status_code=303)
