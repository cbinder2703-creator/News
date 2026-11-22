"""Titelfotos: pro Beitrag ein passendes Stockfoto von Pexels (kostenloser API-Schlüssel, kommerzielle Nutzung erlaubt).

Ablauf: Die KI liefert beim Schreiben eine englische Suchanfrage (`image_query`). Hier wird das beste noch nicht benutzte Foto
gesucht, auf 1200x630 zugeschnitten und in data/photos/ gespeichert. So kommt beim Besuch der Seite nichts von Dritten
(Datenschutz), und das Foto bleibt auch bestehen, falls es bei Pexels entfernt wird. Der Fotograf wird unter dem Bild genannt.
Ohne Schlüssel oder ohne Treffer zeigt die Seite stattdessen ein Symbol (siehe icons.py). Nicht gegen den Live-Dienst getestet.
Die Nutzungsbedingungen von Pexels bitte selbst prüfen: https://www.pexels.com/api/ und https://www.pexels.com/license/
"""
from __future__ import annotations

import io
import logging
import os
import zlib
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

from .icons import ICON_QUERIES, pick_icon
from .store import Store

log = logging.getLogger("newsbot.photos")

SEARCH_URL = "https://api.pexels.com/v1/search"
SIZE = (1200, 630)
MAX_BYTES = 15 * 1024 * 1024
ALLOWED_HOSTS = {"images.pexels.com"}


def choose(photos: list[dict], seed: str, used: set[int]) -> dict | None:
    """Wählt ein Foto: breit genug, noch nicht benutzt. Der Start wechselt je Beitrag, damit nicht immer Platz 1 gewinnt."""
    usable = [p for p in photos if p.get("width", 0) >= SIZE[0] and p.get("width", 0) >= p.get("height", 1)]
    if not usable:
        return None
    start = zlib.crc32(seed.encode()) % len(usable)
    for k in range(len(usable)):
        p = usable[(start + k) % len(usable)]
        if p.get("id") not in used:
            return p
    return None


def crop_to_size(data: bytes) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    target = SIZE[0] / SIZE[1]
    if w / h > target:  # zu breit: Seiten abschneiden
        nw = int(h * target)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:  # zu hoch: etwas oberhalb der Mitte schneiden (Motive sitzen meist im oberen Drittel)
        nh = int(w / target)
        top = max(0, int((h - nh) * 0.35))
        img = img.crop((0, top, w, top + nh))
    img = img.resize(SIZE, Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True, progressive=True)
    return out.getvalue()


def find_photo(query: str, seed: str, api_key: str, out_path: Path, used: set[int],
               http=None) -> dict | None:
    """Sucht, lädt und speichert ein Foto. Gibt die Angaben für den Bildnachweis zurück oder None (dann Symbol)."""
    http = http or requests
    query = (query or "").strip()
    if not (query and api_key):
        return None
    try:
        res = http.get(SEARCH_URL, params={"query": query, "orientation": "landscape", "per_page": 15, "size": "large"},
                       headers={"Authorization": api_key}, timeout=20)
        if res.status_code != 200:
            log.warning("Pexels-Suche %r: HTTP %s", query, res.status_code)
            return None
        photo = choose(res.json().get("photos", []), seed, used)
        if photo is None:
            log.info("Kein passendes Foto für %r", query)
            return None
        src = (photo.get("src") or {}).get("large2x") or (photo.get("src") or {}).get("large") or ""
        if urlparse(src).scheme != "https" or urlparse(src).hostname not in ALLOWED_HOSTS:
            log.warning("Unerwartete Bildadresse, übersprungen: %r", src)
            return None
        img = http.get(src, timeout=40, stream=False)
        if img.status_code != 200 or len(img.content) > MAX_BYTES:
            log.warning("Foto nicht ladbar (%s, %s Bytes)", img.status_code, len(img.content))
            return None
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(crop_to_size(img.content))
    except (requests.RequestException, ValueError, OSError) as exc:
        log.warning("Foto für %r fehlgeschlagen: %s", query, exc)
        return None
    return {"id": photo["id"], "query": query, "photographer": photo.get("photographer", ""),
            "photographer_url": photo.get("photographer_url", ""), "page_url": photo.get("url", "")}


def query_for(rec: dict) -> str:
    """Suchanfrage: die der KI, sonst eine zum Symbol des Beitrags passende."""
    a = rec["article"]
    if (a.get("image_query") or "").strip():
        return a["image_query"].strip()
    text = f"{a.get('headline', '')} {a.get('focus_keyword', '')} {a.get('category', '')}"
    return ICON_QUERIES[pick_icon(text, a.get("icon", ""))]


def add_photo(store: Store, rec: dict, api_key: str, http=None) -> bool:
    """Holt für einen Beitrag ein Foto, falls er noch keins hat. True, wenn jetzt eines vorhanden ist."""
    if rec.get("photo") and store.photo_path(rec["id"]).exists():
        return True
    used = {r["photo"]["id"] for r in store.all() if r.get("photo") and r["id"] != rec["id"]}
    meta = find_photo(query_for(rec), rec["id"], api_key, store.photo_path(rec["id"]), used, http)
    if meta is None:
        return False
    rec["photo"] = meta
    store.save(rec)
    log.info("Foto für %s: %s (%s)", rec["id"], meta["query"], meta["photographer"])
    return True


def backfill(store: Store, api_key: str | None = None, http=None) -> int:
    """Holt Fotos für alle Entwürfe und Beiträge ohne Foto. Ohne Schlüssel passiert nichts."""
    api_key = api_key if api_key is not None else os.environ.get("PEXELS_API_KEY", "")
    if not api_key:
        log.info("PEXELS_API_KEY nicht gesetzt: keine Fotos (die Seite zeigt Symbole)")
        return 0
    done = 0
    for rec in store.all():
        if rec["status"] in ("draft", "live", "held") and not (rec.get("photo") and store.photo_path(rec["id"]).exists()):
            done += add_photo(store, rec, api_key, http)
    return done
