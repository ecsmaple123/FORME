from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from ..db import get_session
from ..services import library
from ..services.library import ItemData, UserError
from ..templating import templates
from .forms import item_form

router = APIRouter()


def _item_or_404(session: Session, item_id: int):
    item = library.get_item(session, item_id)
    if item is None:
        raise HTTPException(404, "Item not found")
    return item


def _photo_or_404(item, photo_id: int):
    photo = library.get_photo(item, photo_id)
    if photo is None:
        raise HTTPException(404, "Photo not found")
    return photo


def render_form(request: Request, session: Session, data: ItemData, *, item=None, staged=None,
                staged_kinds=None, errors=None, warnings=None, status_code: int = 200):
    return templates.TemplateResponse(request, "item_form.html", {
        "data": data, "item": item, "errors": errors or {}, "warnings": warnings or [],
        "staged": list(zip(staged, staged_kinds or [])) if staged else [],
        "categories": library.list_categories(session),
        "subcats": library.subcategory_suggestions(session),
    }, status_code=status_code)


def _detail(request: Request, item, photo=None, error: str = "", status_code: int = 200):
    return templates.TemplateResponse(request, "item_detail.html", {
        "item": item, "shown": photo or item.cover, "error": error,
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
def detail(request: Request, item_id: int, photo: Optional[int] = None,
           session: Session = Depends(get_session)):
    item = _item_or_404(session, item_id)
    shown = library.get_photo(item, photo) if photo else None
    return _detail(request, item, shown)


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


# ---------- photos ----------

@router.post("/items/{item_id}/photos")
def add_photos(request: Request, item_id: int, photo: List[UploadFile] = File([]),
               image_url: str = Form(""), kind: str = Form("real"),
               session: Session = Depends(get_session)):
    item = _item_or_404(session, item_id)
    files = [f for f in photo if f.filename]
    jobs = [lambda f=f: library.ingest_upload(f.file) for f in files]
    if image_url.strip():
        jobs.append(lambda: library.ingest_image_url(image_url.strip(),
                                                     referer=item.source_url or None))
    try:
        if not jobs:
            raise UserError("Choose a photo to upload or paste an image URL.")
        library.check_room(item, len(jobs))
        done, errors = library.run_many(jobs, "Photo")
    except UserError as exc:
        return _detail(request, item, error=str(exc), status_code=422)
    added = [library.add_photo(session, item, processed, kind) for processed in done]
    if errors:
        item = _item_or_404(session, item_id)
        shown = library.get_photo(item, added[-1].id) if added else None
        return _detail(request, item, shown, error=" ".join(errors), status_code=422)
    return RedirectResponse(f"/items/{item_id}?photo={added[-1].id}", status_code=303)


@router.post("/items/{item_id}/photos/{photo_id}/cover")
def make_cover(item_id: int, photo_id: int, session: Session = Depends(get_session)):
    item = _item_or_404(session, item_id)
    library.set_cover(session, item, _photo_or_404(item, photo_id))
    return RedirectResponse(f"/items/{item_id}?photo={photo_id}", status_code=303)


@router.post("/items/{item_id}/photos/{photo_id}/kind")
def change_kind(item_id: int, photo_id: int, kind: str = Form(...),
                session: Session = Depends(get_session)):
    item = _item_or_404(session, item_id)
    library.set_kind(session, _photo_or_404(item, photo_id), kind)
    return RedirectResponse(f"/items/{item_id}?photo={photo_id}", status_code=303)


@router.get("/items/{item_id}/photos/{photo_id}/delete", response_class=HTMLResponse)
def delete_photo_confirm(request: Request, item_id: int, photo_id: int,
                         session: Session = Depends(get_session)):
    item = _item_or_404(session, item_id)
    photo = _photo_or_404(item, photo_id)
    return templates.TemplateResponse(request, "confirm_delete_photo.html",
                                      {"item": item, "photo": photo})


@router.post("/items/{item_id}/photos/{photo_id}/delete")
def delete_photo(request: Request, item_id: int, photo_id: int,
                 session: Session = Depends(get_session)):
    item = _item_or_404(session, item_id)
    photo = _photo_or_404(item, photo_id)
    try:
        library.delete_photo(session, item, photo)
    except UserError as exc:
        return _detail(request, item, photo, error=str(exc), status_code=422)
    return RedirectResponse(f"/items/{item_id}", status_code=303)
