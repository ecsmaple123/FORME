from typing import List

from fastapi import Form

from ..services.library import ItemData, parse_tags


def item_form(
    name: str = Form(""),
    category_id: str = Form(""),
    subcategory: str = Form(""),
    color_hex: str = Form(""),
    color_name: str = Form(""),
    new_category: str = Form(""),
    fabric: str = Form(""),
    brand: str = Form(""),
    size: str = Form(""),
    seasons: List[str] = Form([]),
    tags: str = Form(""),
    notes: str = Form(""),
    source_url: str = Form(""),
) -> ItemData:
    return ItemData(
        name=name, category_id=int(category_id) if category_id.isdigit() else None,
        subcategory=subcategory, color_hex=color_hex, color_name=color_name, fabric=fabric,
        brand=brand, size=size, seasons=seasons, tags=parse_tags(tags), notes=notes,
        source_url=source_url,
        # "new" is the "+ New category…" choice; the typed name only counts with it selected
        new_category=new_category if category_id == "new" else "",
    )
