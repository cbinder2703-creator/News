"""Titelfotos: pro Beitrag ein passendes, frei nutzbares Foto, von einer KI auf Eignung geprüft.

Quellen (nur Bilder, deren Lizenz kommerzielle Nutzung und Zuschneiden erlaubt):
- Pexels (API-Schlüssel PEXELS_API_KEY, Pexels-Lizenz: frei nutzbar, auch kommerziell): gute Stockfotos.
- Wikimedia Commons über Openverse (ohne Schlüssel), NUR Bilder mit CC0 oder Public-Domain-Kennzeichnung:
  oft echte Produktfotos. Die Lizenzangabe stammt von Wikimedia; wir nennen Urheber und Quelle trotzdem.
Ablauf: Kandidaten sammeln -> Claude schaut sich die Vorschaubilder an und wählt das passende (oder keines) ->
zuschneiden auf 1200x630, in data/photos/ speichern. So lädt die Seite beim Besuch nichts von Dritten (Datenschutz).
Ohne passendes Bild zeigt die Seite ein Symbol (siehe icons.py). Nicht gegen die Live-Dienste getestet.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import zlib
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image
from pydantic import BaseModel

from .icons import ICON_QUERIES, pick_icon
from .store import Store

log = logging.getLogger("newsbot.photos")

PEXELS_URL = "https://api.pexels.com/v1/search"
OPENVERSE_URL = "https://api.openverse.org/v1/images/"
SIZE = (1200, 630)
MAX_BYTES = 15 * 1024 * 1024
UA = {"User-Agent": "newsbot/1.0 (image fetcher; python-requests)"}
OPEN_LICENSES = {"cc0": "CC0", "pdm": "Public Domain"}


def _host_ok(url: str, hosts: set[str]) -> bool:
    u = urlparse(url or "")
    return u.scheme == "https" and (u.hostname or "") in hosts


def pexels_candidates(query: str, api_key: str, http) -> list[dict]:
    if not (query and api_key):
        return []
    res = http.get(PEXELS_URL, params={"query": query, "orientation": "landscape", "per_page": 15, "size": "large"},
                   headers={"Authorization": api_key}, timeout=20)
    if res.status_code != 200:
        log.warning("Pexels-Suche %r: HTTP %s", query, res.status_code)
        return []
    out = []
    for p in res.json().get("photos", []):
        src = p.get("src") or {}
        full, thumb = src.get("large2x") or src.get("large") or "", src.get("medium") or src.get("large") or ""
        if not (_host_ok(full, {"images.pexels.com"}) and _host_ok(thumb or full, {"images.pexels.com"})):
            continue
        out.append({"id": f"pexels:{p.get('id')}", "w": p.get("width", 0), "h": p.get("height", 0),
                    "full": full, "thumb": thumb or full, "query": query,
                    "credit": {"photographer": p.get("photographer", ""), "photographer_url": p.get("photographer_url", ""),
                               "page_url": p.get("url", ""), "source": "Pexels", "license": "Pexels-Lizenz"}})
    return out


def commons_candidates(query: str, http) -> list[dict]:
    """Wikimedia-Commons-Bilder mit CC0/Public Domain über die Openverse-Suche (kein Schlüssel nötig)."""
    if not query:
        return []
    res = http.get(OPENVERSE_URL, params={"q": query, "license": ",".join(OPEN_LICENSES), "source": "wikimedia",
                                          "mature": "false", "page_size": 12}, headers=UA, timeout=20)
    if res.status_code != 200:
        log.warning("Openverse-Suche %r: HTTP %s", query, res.status_code)
        return []
    out = []
    for r in res.json().get("results", []):
        lic = (r.get("license") or "").lower()
        if lic not in OPEN_LICENSES or not _host_ok(r.get("url", ""), {"upload.wikimedia.org"}):
            continue
        thumb = r.get("thumbnail") or ""
        if not _host_ok(thumb, {"api.openverse.org"}):
            continue
        out.append({"id": f"commons:{r.get('id')}", "w": r.get("width") or 0, "h": r.get("height") or 0,
                    "full": r["url"], "thumb": thumb, "query": query,
                    "credit": {"photographer": r.get("creator") or "unbekannt", "photographer_url": r.get("creator_url") or "",
                               "page_url": r.get("foreign_landing_url") or "", "source": "Wikimedia Commons",
                               "license": OPEN_LICENSES[lic]}})
    return out


def usable(c: dict, used: set[str]) -> bool:
    """Groß genug, quer (oder fast quadratisch) und noch nicht für einen anderen Beitrag benutzt."""
    w, h = c.get("w") or 0, c.get("h") or 1
    return c["id"] not in used and w >= SIZE[0] and w >= h * 0.9


def choose(cands: list[dict], seed: str) -> dict | None:
    """Ersatz ohne KI-Prüfung: nur Pexels-Fotos; der Start wechselt je Beitrag, damit nicht immer Platz 1 gewinnt."""
    pex = [c for c in cands if c["id"].startswith("pexels:")]
    return pex[zlib.crc32(seed.encode()) % len(pex)] if pex else None


class Pick(BaseModel):
    choice: int
    reason: str


PICK_PROMPT = """Du wählst das Titelbild für einen Beitrag auf einer deutschen Deal- und Technik-Seite.
Beitrag: {headline}
Thema/Produkt: {topic}
Unten sind {n} nummerierte Bildkandidaten. Wähle das Bild, das das Thema oder Produkt klar und ansprechend zeigt und als
Titelbild gut aussieht. Ungeeignet sind: Bilder zu einem anderen Thema, Screenshots, Diagramme, Logos als Hauptmotiv,
Bilder mit viel Text, unscharfe oder sehr dunkle Bilder, Bilder mit Personen im Mittelpunkt, Unpassendes oder Anstößiges.
Antworte mit choice = Nummer des besten Bildes oder 0, wenn keines wirklich passt."""


def ai_pick(cands: list[dict], headline: str, topic: str, client, model: str, http) -> dict | None:
    content, shown = [], []
    for c in cands:
        try:
            r = http.get(c["thumb"], headers=UA, timeout=20)
            if r.status_code != 200 or not r.content or len(r.content) > 4 * 1024 * 1024:
                continue
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            img.thumbnail((512, 512))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=80)
        except (requests.RequestException, OSError, ValueError):
            continue
        shown.append(c)
        content += [{"type": "text", "text": f"Bild {len(shown)}:"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.standard_b64encode(buf.getvalue()).decode()}}]
    if not shown:
        return None
    content.append({"type": "text", "text": PICK_PROMPT.format(headline=headline, topic=topic, n=len(shown))})
    try:
        resp = client.messages.parse(model=model, max_tokens=4000, output_format=Pick,
                                     messages=[{"role": "user", "content": content}])
    except Exception as exc:  # noqa: BLE001 - Bildprüfung darf den Lauf nie stoppen
        log.warning("Bildprüfung fehlgeschlagen: %s", exc)
        return None
    pick = resp.parsed_output
    if resp.stop_reason == "refusal" or pick is None or not 1 <= pick.choice <= len(shown):
        log.info("Kein passendes Bild für %r (%s)", headline, getattr(pick, "reason", resp.stop_reason))
        return None
    log.info("Bild %s gewählt für %r: %s", pick.choice, headline, pick.reason)
    return shown[pick.choice - 1]


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


def queries_for(rec: dict) -> tuple[str, str]:
    """(englische Stockfoto-Suche, Produktname). Stockfoto: die der KI, sonst passend zum Symbol des Beitrags."""
    a = rec["article"]
    stock = (a.get("image_query") or "").strip()
    if not stock:
        text = f"{a.get('headline', '')} {a.get('focus_keyword', '')} {a.get('category', '')}"
        stock = ICON_QUERIES[pick_icon(text, a.get("icon", ""))]
    shop = a.get("shopping") or []
    product = (shop[0].get("query") or "").strip() if shop else ""
    return stock, product


def query_for(rec: dict) -> str:
    return queries_for(rec)[0]


def find_photo(rec: dict, out_path: Path, used: set[str], pexels_key: str = "", client=None, model: str = "",
               http=None) -> dict | None:
    """Sucht Kandidaten, lässt die KI wählen, lädt und speichert. Gibt die Angaben für den Bildnachweis zurück."""
    http = http or requests
    stock, product = queries_for(rec)
    cands: list[dict] = []
    for name, fn in (("pexels", lambda: pexels_candidates(stock, pexels_key, http)),
                     ("commons", lambda: (commons_candidates(product, http) + commons_candidates(stock, http)) if client else [])):
        try:
            cands += [c for c in fn() if usable(c, used)][:5]
        except (requests.RequestException, ValueError) as exc:
            log.warning("Bildsuche %s fehlgeschlagen: %s", name, exc)
    cands = list({c["id"]: c for c in cands}.values())  # doppelte Treffer aus beiden Suchen entfernen
    if not cands:
        return None
    if client is not None:
        photo = ai_pick(cands, rec["article"].get("headline", ""), product or stock, client, model, http)
    else:
        photo = choose(cands, rec["id"])
    if photo is None:
        return None
    try:
        img = http.get(photo["full"], headers=UA, timeout=60)
        if img.status_code != 200 or not img.content or len(img.content) > MAX_BYTES:
            log.warning("Foto nicht ladbar (%s)", img.status_code)
            return None
        data = crop_to_size(img.content)
    except (requests.RequestException, ValueError, OSError) as exc:
        log.warning("Foto für %r fehlgeschlagen: %s", photo["query"], exc)
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return {"id": photo["id"], "query": photo["query"], **photo["credit"]}


def add_photo(store: Store, rec: dict, pexels_key: str = "", client=None, model: str = "", http=None) -> bool:
    """Holt für einen Beitrag ein Foto, falls er noch keins hat. True, wenn jetzt eines vorhanden ist."""
    if rec.get("photo") and store.photo_path(rec["id"]).exists():
        return True
    used = {str(r["photo"]["id"]) for r in store.all() if r.get("photo") and r["id"] != rec["id"]}
    meta = find_photo(rec, store.photo_path(rec["id"]), used, pexels_key, client, model, http)
    if meta is None:
        return False
    rec["photo"] = meta
    store.save(rec)
    log.info("Foto für %s: %s (%s, %s)", rec["id"], meta["query"], meta["source"], meta["license"])
    return True


def backfill(store: Store, pexels_key: str | None = None, client=None, model: str = "", http=None) -> int:
    """Holt Fotos für alle Entwürfe und Beiträge ohne Foto. Ohne Pexels-Schlüssel und ohne KI passiert nichts."""
    pexels_key = pexels_key if pexels_key is not None else os.environ.get("PEXELS_API_KEY", "")
    if client is None and os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        client = anthropic.Anthropic()
    if not (pexels_key or client):
        log.info("Weder PEXELS_API_KEY noch ANTHROPIC_API_KEY: keine Fotos (die Seite zeigt Symbole)")
        return 0
    done = 0
    for rec in store.all():
        if rec["status"] in ("draft", "live", "held") and not (rec.get("photo") and store.photo_path(rec["id"]).exists()):
            done += add_photo(store, rec, pexels_key, client, model, http)
    return done
