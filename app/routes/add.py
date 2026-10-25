"""Adding items: upload a photo, or import from a product URL (with image-URL / upload fallback)."""
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from ..db import get_session
from ..services import colors, library
from ..services.library import ItemData, UserError
from ..templating import templates
from .forms import item_form
from .items import render_form

router = APIRouter()


def _add_page(request: Request, *, error: str = "", url: str = "", name: str = "",
              brand: str = "", image_url: str = "", status_code: int = 200):
    return templates.TemplateResponse(request, "add.html", {
        "error": error, "url": url, "name": name, "brand": brand, "image_url": image_url,
    }, status_code=status_code)


def _new_item_form(request: Request, session: Session, staged, *, name: str = "",
                   brand: str = "", source_url: str = ""):
    data = ItemData(name=name.strip(), brand=brand.strip(), source_url=source_url.strip())
    if staged.primary_hex:
        data.color_hex = staged.primary_hex
        data.color_name = colors.nearest_color_name(staged.primary_hex)
    return render_form(request, session, data, staged=staged)


@router.get("/add", response_class=HTMLResponse)
def add_page(request: Request):
    return _add_page(request)


@router.post("/add/photo", response_class=HTMLResponse)
def add_photo(request: Request, photo: UploadFile = File(...), source_url: str = Form(""),
              name: str = Form(""), brand: str = Form(""),
              session: Session = Depends(get_session)):
    try:
        staged = library.stage_upload(photo.file)
    except UserError as exc:
        return _add_page(request, error=str(exc), url=source_url, name=name, brand=brand,
                         status_code=422)
    return _new_item_form(request, session, staged, name=name, brand=brand,
                          source_url=source_url)


@router.post("/add/url", response_class=HTMLResponse)
def add_url(request: Request, url: str = Form(...)):
    url = url.strip()
    try:
        found = library.extract_from_page(url)
    except UserError as exc:
        return _add_page(request, error=str(exc), url=url, status_code=422)
    return templates.TemplateResponse(request, "import_preview.html", {"found": found, "url": url})


@router.post("/add/image-url", response_class=HTMLResponse)
def add_image_url(request: Request, image_url: str = Form(...), source_url: str = Form(""),
                  name: str = Form(""), brand: str = Form(""),
                  session: Session = Depends(get_session)):
    try:
        staged = library.stage_from_image_url(image_url.strip(), referer=source_url or None)
    except UserError as exc:
        return _add_page(request, error=str(exc), url=source_url, name=name, brand=brand,
                         image_url=image_url, status_code=422)
    return _new_item_form(request, session, staged, name=name, brand=brand,
                          source_url=source_url)


@router.post("/items")
def create(request: Request, image_token: str = Form(""), data: ItemData = Depends(item_form),
           session: Session = Depends(get_session)):
    try:
        staged = library.load_staged(image_token)
    except UserError as exc:
        return _add_page(request, error=str(exc), status_code=422)
    errors = library.validate(data, session)
    if errors:
        return render_form(request, session, data, staged=staged, errors=errors, status_code=422)
    item = library.create_item(session, data, image_token)
    return RedirectResponse(f"/items/{item.id}", status_code=303)
