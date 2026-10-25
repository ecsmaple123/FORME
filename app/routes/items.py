from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from ..db import get_session
from ..services import library
from ..services.library import ItemData
from ..templating import templates
from .forms import item_form

router = APIRouter()


def _item_or_404(session: Session, item_id: int):
    item = library.get_item(session, item_id)
    if item is None:
        raise HTTPException(404, "Item not found")
    return item


def render_form(request: Request, session: Session, data: ItemData, *, item=None, staged=None,
                errors=None, status_code: int = 200):
    return templates.TemplateResponse(request, "item_form.html", {
        "data": data, "item": item, "staged": staged, "errors": errors or {},
        "categories": library.list_categories(session),
        "subcats": library.subcategory_suggestions(session),
    }, status_code=status_code)


@router.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = "", category: str = "", sort: str = "new",
          session: Session = Depends(get_session)):
    category_id = int(category) if category.isdigit() else None
    sort = sort if sort in library.SORTS else "new"
    items = library.search_items(session, q, category_id, sort)
    ctx = {"items": items, "q": q, "category_id": category_id, "sort": sort}
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_grid.html", ctx)
    ctx.update(categories=library.list_categories(session),
               counts=library.category_counts(session))
    return templates.TemplateResponse(request, "index.html", ctx)


@router.get("/items/{item_id}", response_class=HTMLResponse)
def detail(request: Request, item_id: int, session: Session = Depends(get_session)):
    item = _item_or_404(session, item_id)
    return templates.TemplateResponse(request, "item_detail.html", {"item": item})


@router.get("/items/{item_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, item_id: int, session: Session = Depends(get_session)):
    item = _item_or_404(session, item_id)
    return render_form(request, session, ItemData.from_item(item), item=item)


@router.post("/items/{item_id}/edit")
def edit_save(request: Request, item_id: int, data: ItemData = Depends(item_form),
              session: Session = Depends(get_session)):
    item = _item_or_404(session, item_id)
    errors = library.validate(data, session)
    if errors:
        return render_form(request, session, data, item=item, errors=errors, status_code=422)
    library.update_item(session, item, data)
    return RedirectResponse(f"/items/{item.id}", status_code=303)


@router.get("/items/{item_id}/delete", response_class=HTMLResponse)
def delete_confirm(request: Request, item_id: int, session: Session = Depends(get_session)):
    item = _item_or_404(session, item_id)
    return templates.TemplateResponse(request, "confirm_delete.html", {"item": item})


@router.post("/items/{item_id}/delete")
def delete(item_id: int, session: Session = Depends(get_session)):
    item = _item_or_404(session, item_id)
    library.delete_item(session, item)
    return RedirectResponse("/?deleted=1", status_code=303)
