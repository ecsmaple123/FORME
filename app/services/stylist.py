"""The AI stylist: outfits from the user's own closet for the weather and an occasion.

Its memory is the database: every suggestion it made, the user's like/dislike and note on it, the
notes the user told it directly (Stylist page), the outfits the user saved themselves, and the
"My style" text from Settings. All of that goes into
each request, so the model needs no state of its own.

What is sent to Gemini (free tier: Google may use it): the closet's item details, the weather, the
occasion text, the memory above, and (if switched on in Settings) the cutout photos of item photos.
Never the user's name, location, or fit pictures.
"""
import logging
import threading
from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from ..config import get_settings
from ..models import Item, Outfit, StylistNote, Suggestion, VERDICTS
from . import ai, images, prefs
from .ai import AIError, AIUnavailable  # noqa: F401  (re-exported for the routes)

log = logging.getLogger("wardrobe.stylist")

STYLIST_COUNT = 3   # outfits per request on the Stylist page
MAX_PHOTOS = 60     # beyond this many items the stylist gets text only
MEMORY = 30         # most recent likes and dislikes each
SAVED_OUTFITS = 20
MAX_NOTES = 50      # notes the user told the stylist directly

SYSTEM = """You are the personal stylist inside FORME, a wardrobe app. You dress one person using \
only the clothes in their closet, which is listed below by id.

Rules:
- Use only item ids from the closet list. Never invent items.
- Every outfit must be complete and wearable: usually a top, a bottom and shoes, plus outerwear or \
a layer when the weather calls for it. Never combine items that can't be worn together, such as \
two pairs of shoes or two pairs of trousers.
- Dress for the weather (temperature, rain, wind) and the occasion.
- Learn their taste: follow their own style description and what they told you directly (newer \
notes win over older ones), lean towards outfits and items they liked, avoid what they disliked, \
and respect their notes. Outfits they saved themselves are ones \
they like.
- If the closet lacks something an outfit needs, give the best outfit possible and say in the \
reason what would complete it.
- When asked for several outfits, make them clearly different from each other.
- title: 2 to 5 words. reason: one or two short sentences (at most 40 words) on why it works: \
colours, fabrics, weather, occasion. Talk to them directly ("you"); warm, never gushing."""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "outfits": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "item_ids": {"type": "ARRAY", "items": {"type": "INTEGER"}},
                    "reason": {"type": "STRING"},
                },
                "required": ["title", "item_ids", "reason"],
            },
        },
    },
    "required": ["outfits"],
}

_daily_lock = threading.Lock()  # one daily pick per day, even if two pages load at once


def available() -> bool:
    return ai.available()


def weather_line(wx) -> str:
    if wx is None:
        return ""
    unit = "°F" if wx.units == "f" else "°C"
    parts = [f"{round(wx.temp)}{unit} (feels like {round(wx.feels_like)}{unit})", wx.label.lower(),
             f"high {round(wx.high)}{unit}, low {round(wx.low)}{unit}"]
    if wx.rain_chance is not None:
        parts.append(f"{wx.rain_chance}% chance of rain")
    parts.append(f"wind {round(wx.wind)} {wx.wind_unit}")
    return ", ".join(parts)


def _closet(session: Session) -> List[Item]:
    stmt = (select(Item).options(selectinload(Item.photos), selectinload(Item.category),
                                 selectinload(Item.tags))
            .order_by(Item.category_id, Item.id))
    return list(session.exec(stmt).all())


def _describe(item: Item) -> str:
    bits = [f"#{item.id} {item.name}",
            item.category.name + (f" / {item.subcategory}" if item.subcategory else "")]
    if item.color_name or item.color_hex:
        bits.append(f"colour {item.color_name or item.color_hex}")
    for label, value in (("fabric", item.fabric), ("brand", item.brand)):
        if value:
            bits.append(f"{label} {value}")
    if item.season_list:
        bits.append("seasons " + ", ".join(item.season_list))
    if item.tags:
        bits.append("tags " + ", ".join(t.name for t in item.tags))
    if item.notes:
        bits.append("notes: " + " ".join(item.notes.split())[:150])
    return " | ".join(bits)


def _photo(item: Item) -> Optional[ai.Image]:
    """The cover's cutout thumbnail (400 px WebP), never a fit picture or a photo with background."""
    cover = item.cover
    if cover is None or cover.kind == "fit" or not cover.cutout_shown:
        return None
    path = images.cutout_paths(get_settings().images_dir, cover.cutout_shown)["thumb"]
    try:
        return ai.Image("image/webp", path.read_bytes())
    except OSError:
        return None


def _names(ids: List[int], by_id: Dict[int, Item]) -> str:
    return ", ".join(f"{by_id[i].name} (#{i})" for i in ids if i in by_id)


def _memory(session: Session, by_id: Dict[int, Item]) -> List[str]:
    lines = []
    told = notes(session)
    if told:
        lines.append("What they told you directly (newest first; follow these):\n"
                     + "\n".join(f'- "{n.text}"' for n in told))
    for verdict, heading in (("like", "Outfits they LIKED"), ("dislike", "Outfits they DISLIKED")):
        rows = session.exec(select(Suggestion).where(Suggestion.verdict == verdict)
                            .order_by(Suggestion.created_at.desc()).limit(MEMORY)).all()
        entries = []
        for s in rows:
            items = _names(s.ids, by_id)
            if items:
                note = f' — their note: "{s.note}"' if s.note else ""
                entries.append(f"- {s.title}: {items}{note}")
        if entries:
            lines.append(heading + ":\n" + "\n".join(entries))
    saved = session.exec(select(Outfit).where(Outfit.source == "manual")
                         .options(selectinload(Outfit.links))
                         .order_by(Outfit.updated_at.desc()).limit(SAVED_OUTFITS)).all()
    entries = [f"- {o.name}: {_names([link.item_id for link in o.links], by_id)}" for o in saved]
    entries = [e for e in entries if not e.endswith(": ")]
    if entries:
        lines.append("Outfits they put together and saved themselves:\n" + "\n".join(entries))
    return lines


def _ask(session: Session, *, task: str, weather: str, count: int,
         extra: Optional[List[str]] = None) -> List[dict]:
    items = _closet(session)
    if not items:
        raise AIError("Add some clothes to your closet first.")
    by_id = {i.id: i for i in items}
    p = prefs.get()
    head = [task, f"Weather today: {weather}." if weather else "Weather: unknown."]
    head.append(f"Their own description of their style: {p.style}" if p.style
                else "They haven't described their style yet.")
    head += _memory(session, by_id) + (extra or [])
    head.append(f"Their closet ({len(items)} items):\n" + "\n".join(_describe(i) for i in items))
    parts: List = ["\n\n".join(head)]
    if p.send_photos and len(items) <= MAX_PHOTOS:
        for item in items:
            photo = _photo(item)
            if photo:
                parts += [f"Photo of item #{item.id}:", photo]
    parts.append(f"Give exactly {count} outfit{'s' if count > 1 else ''}.")

    data = ai.generate_json(SYSTEM, parts, SCHEMA)
    proposed = data.get("outfits") if isinstance(data, dict) else None
    found = []
    for o in (proposed if isinstance(proposed, list) else [])[:count]:
        if not isinstance(o, dict):
            continue
        ids: List[int] = []
        for raw in o.get("item_ids") or []:
            try:
                i = int(raw)
            except (TypeError, ValueError):
                continue
            if i in by_id and i not in ids:
                ids.append(i)
        if ids:
            found.append({"title": " ".join(str(o.get("title") or "Outfit").split())[:120],
                          "reason": " ".join(str(o.get("reason") or "").split())[:600],
                          "ids": ids})
    if not found:
        raise AIError("The stylist's answer didn't use any of your clothes. Try again.")
    return found


def _store(session: Session, found: List[dict], **fields) -> List[Suggestion]:
    rows = [Suggestion(title=f["title"], reason=f["reason"],
                       item_ids=",".join(map(str, f["ids"])), **fields) for f in found]
    for row in rows:
        session.add(row)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def suggest(session: Session, request: str, wx=None) -> List[Suggestion]:
    """Outfits for an occasion (the Stylist page). Raises AIUnavailable / AIError."""
    request = " ".join((request or "").split())[:300]
    weather = weather_line(wx)
    task = (f"They ask: {request}" if request
            else "They want outfit ideas for today, for no particular occasion.")
    found = _ask(session, task=task, weather=weather, count=STYLIST_COUNT)
    return _store(session, found, source="stylist", request=request, weather=weather[:200])


def daily(session: Session, day: date, wx=None, again: bool = False) -> Suggestion:
    """Today's outfit for the home page: made once a day (or again on request), then kept."""
    key = day.isoformat()
    with _daily_lock:
        current = session.exec(select(Suggestion).where(
            Suggestion.source == "daily", Suggestion.day == key, Suggestion.replaced == False)  # noqa: E712
            .order_by(Suggestion.id.desc())).first()
        if current and not again:
            return current
        recent = session.exec(select(Suggestion).where(Suggestion.source == "daily")
                              .order_by(Suggestion.id.desc()).limit(5)).all()
        avoid = [f"- {s.title}: items {s.item_ids}" for s in recent]
        extra = ["Recent picks of the day (don't repeat these):\n" + "\n".join(avoid)] if avoid else []
        weather = weather_line(wx)
        found = _ask(session, task="Pick their outfit for today: an everyday outfit.",
                     weather=weather, count=1, extra=extra)
        if current:
            current.replaced = True
            session.add(current)
        return _store(session, found, source="daily", day=key, weather=weather[:200])[0]


def items_of(session: Session, suggestion: Suggestion) -> List[Item]:
    ids = suggestion.ids
    if not ids:
        return []
    rows = session.exec(select(Item).where(Item.id.in_(ids))
                        .options(selectinload(Item.photos), selectinload(Item.category))).all()
    by_id = {i.id: i for i in rows}
    return [by_id[i] for i in ids if i in by_id]


def set_verdict(session: Session, suggestion: Suggestion, verdict: str, note: str = "") -> None:
    suggestion.verdict = verdict if verdict in VERDICTS else ""
    suggestion.note = " ".join((note or "").split())[:300] if suggestion.verdict else ""
    session.add(suggestion)
    session.commit()


def forget(session: Session) -> int:
    """Clear every like, dislike and note (the suggestions themselves stay)."""
    rows = session.exec(select(Suggestion).where(Suggestion.verdict != "")).all()
    for s in rows:
        s.verdict, s.note = "", ""
        session.add(s)
    session.commit()
    return len(rows)


def notes(session: Session) -> List[StylistNote]:
    return list(session.exec(select(StylistNote).order_by(StylistNote.id.desc())
                             .limit(MAX_NOTES)).all())


def add_note(session: Session, text: str) -> Optional[StylistNote]:
    """Store a note (whitespace tidied, at most 300 characters); None if it was empty."""
    text = " ".join((text or "").split())[:300]
    if not text:
        return None
    note = StylistNote(text=text)
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def counts(session: Session) -> Dict[str, int]:
    rows = session.exec(select(Suggestion.verdict).where(Suggestion.verdict != "")).all()
    return {v: sum(1 for r in rows if r == v) for v in VERDICTS}


def recent(session: Session, limit: int = 12) -> List[Suggestion]:
    return list(session.exec(select(Suggestion).where(Suggestion.source == "stylist")
                             .order_by(Suggestion.id.desc()).limit(limit)).all())
