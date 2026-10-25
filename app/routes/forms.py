from typing import List

from fastapi import Form

from ..services.library import ItemData, parse_tags


def item_form(
    name: str = Form(""),
    category_id: str = Form(""),
    subcategory: str = Form(""),
    color_hex: str = Form(""),
    color_name: str = Form(""),
    brand: str = Form(""),
    size: str = Form(""),
    seasons: List[str] = Form([]),
    tags: str = Form(""),
    notes: str = Form(""),
    source_url: str = Form(""),
) -> ItemData:
    return ItemData(
        name=name, category_id=int(category_id) if category_id.isdigit() else None,
        subcategory=subcategory, color_hex=color_hex, color_name=color_name, brand=brand,
        size=size, seasons=seasons, tags=parse_tags(tags), notes=notes, source_url=source_url,
    )
