"""Adding items: upload photos, import from a product URL or the browser bookmark, with
image-URL / upload fallbacks. All paths end at the new-item form with the photos staged."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from ..bookmarklet import bookmarklet
from ..db import get_session
from ..services import colors, fabric, library
from ..services.library import ItemData, UserError
from ..templating import templates
from .forms import item_form
from .items import render_form

router = APIRouter()


def app_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _add_page(request: Request, *, error: str = "", url: str = "", name: str = "",
              brand: str = "", image_url: str = "", status_code: int = 200):
    return templates.TemplateResponse(request, "add.html", {
        "error": error, "url": url, "name": name, "brand": brand, "image_url": image_url,
        "bookmarklet": bookmarklet(app_url(request)),
    }, status_code=status_code)


def _preview(request: Request, *, url: str, title: str, brand: str, candidates: List[str],
             via: str):
    return templates.TemplateResponse(request, "import_preview.html", {
        "url": url, "title": title, "brand": brand, "candidates": candidates, "via": via,
    })


def _new_item_form(request: Request, session: Session, staged: list, kind: str, *,
                   name: str = "", brand: str = "", source_url: str = "",
                   warnings: Optional[List[str]] = None):
    name, found_fabric = fabric.split_name(name)  # "Cashmere Overcoat" -> "Overcoat" + Cashmere
    data = ItemData(name=name, fabric=found_fabric, brand=brand.strip(),
                    source_url=source_url.strip())
    if staged[0].primary_hex:
        data.color_hex = staged[0].primary_hex
        data.color_name = colors.nearest_color_name(staged[0].primary_hex)
    return render_form(request, session, data, staged=staged,
                       staged_kinds=[kind] * len(staged), warnings=warnings)


@router.get("/add", response_class=HTMLResponse)
def add_page(request: Request):
    return _add_page(request)


@router.post("/add/photo", response_class=HTMLResponse)
def add_photo(request: Request, photo: List[UploadFile] = File(...),
              photo_kind: str = Form("product"), source_url: str = Form(""),
              name: str = Form(""), brand: str = Form(""),
              session: Session = Depends(get_session)):
    files = [f for f in photo if f.filename]
    try:
        staged, errors = library.run_many(
            [lambda f=f: library.stage_upload(f.file) for f in files], "Photo")
    except UserError as exc:
        staged, errors = [], [str(exc)]
    if not staged:
        return _add_page(request, error=" ".join(errors) or "No file was uploaded.",
                         url=source_url, name=name, brand=brand, status_code=422)
    return _new_item_form(request, session, staged, library.clean_kind(photo_kind),
                          name=name, brand=brand, source_url=source_url, warnings=errors)


@router.post("/add/url", response_class=HTMLResponse)
def add_url(request: Request, url: str = Form(...)):
    url = url.strip()
    try:
        found = library.extract_from_page(url)
    except UserError as exc:
        return _add_page(request, error=str(exc), url=url, status_code=422)
    return _preview(request, url=url, title=found.title, brand=found.brand,
                    candidates=[found.image_url], via=found.image_source)


@router.get("/add/bookmark", response_class=HTMLResponse)
def add_from_bookmark(request: Request, url: str = "", title: str = "", brand: str = "",
                      img: List[str] = Query([])):
    """Target of the browser bookmark: it read the page in the user's browser and sent this."""
    url = url.strip() if library.clean_image_urls([url]) else ""  # same http(s) check
    candidates = library.clean_image_urls(img)
    if not candidates:
        return _add_page(request, url=url, name=title[:200], brand=brand[:100], status_code=422,
                         error="The bookmark found no product images on that page. "
                               "Upload a photo or paste the image URL instead.")
    return _preview(request, url=url, title=title[:200], brand=brand[:100],
                    candidates=candidates, via="bookmark")


@router.post("/add/image-url", response_class=HTMLResponse)
def add_image_url(request: Request, image_url: List[str] = Form(...),
                  source_url: str = Form(""), name: str = Form(""), brand: str = Form(""),
                  session: Session = Depends(get_session)):
    urls = [u.strip() for u in image_url if u.strip()]
    referer = source_url or None
    try:
        staged, errors = library.run_many(
            [lambda u=u: library.stage_from_image_url(u, referer=referer) for u in urls], "Image")
    except UserError as exc:
        staged, errors = [], [str(exc)]
    if not staged:
        return _add_page(request, error=" ".join(errors) or "Pick at least one image.",
                         url=source_url, name=name, brand=brand,
                         image_url=urls[0] if len(urls) == 1 else "", status_code=422)
    return _new_item_form(request, session, staged, "product", name=name, brand=brand,
                          source_url=source_url, warnings=errors)


@router.post("/items")
def create(request: Request, image_token: List[str] = Form([]),
           photo_kind: List[str] = Form([]), data: ItemData = Depends(item_form),
           session: Session = Depends(get_session)):
    try:
        staged = [library.load_staged(t) for t in image_token]
        if not staged:
            raise UserError("The uploaded photos have expired. Please add them again.")
    except UserError as exc:
        return _add_page(request, error=str(exc), status_code=422)
    kinds = [library.clean_kind(k) for k in photo_kind] + ["product"] * len(staged)
    errors = library.validate(data, session)
    if errors:
        return render_form(request, session, data, staged=staged,
                           staged_kinds=kinds[:len(staged)], errors=errors, status_code=422)
    item = library.create_item(session, data, list(zip(image_token, kinds)))
    return RedirectResponse(f"/items/{item.id}", status_code=303)
