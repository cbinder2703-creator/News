"""Direkte Amazon-Produktlinks: die Produktnummern (ASIN) aus den Quellen holen und den Produktideen zuordnen.

Deal-Seiten und Technikmagazine verlinken Angebote meist direkt auf die Amazon-Produktseite (amazon.de/dp/<ASIN>).
Wir lesen diese Links aus dem Feed-Text oder der Quellseite, ordnen sie den Produktideen eines Beitrags zu (über
gemeinsame Wörter in Linktext und Produkt-URL) und bauen daraus beim Seitenbau eigene Links mit unserer Partner-ID.
Keine KI im Spiel: Eine ASIN, die nicht in einer Quelle steht, wird nie verwendet. Ohne Treffer bleibt der Suchlink.
"""
from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from urllib.parse import unquote, urlparse

import requests

from .store import Store

log = logging.getLogger("newsbot.products")

UA = {"User-Agent": "Mozilla/5.0 (compatible; newsbot/1.0; +link-check)"}
ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d|exec/obidos/ASIN|o/ASIN)/([A-Z0-9]{10})(?=[/?&#\"']|$)")
AMAZON_HOST = re.compile(r"(^|\.)amazon\.de$")
SHORT_HOSTS = {"amzn.to", "amzn.eu", "a.co"}
STOP = {"und", "mit", "für", "der", "die", "das", "von", "bei", "zum", "zur", "the", "and", "for", "with", "inkl",
        "amazon", "angebot", "deal", "euro", "nur", "jetzt", "statt", "black", "friday", "week"}


class _Links(HTMLParser):
    """Sammelt (href, Linktext, Text davor) für alle Links."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str, str]] = []
        self._href, self._text, self._ctx, self._buf = None, [], "", ""

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._text, self._ctx = dict(attrs).get("href") or "", [], self._buf[-160:]
        elif tag == "img" and self._href is not None:  # Bild-Links: der Alt-Text beschreibt meist das Produkt
            self._text.append(" " + (dict(attrs).get("alt") or "") + " ")
        elif tag in ("p", "div", "li", "h2", "h3", "section", "aside", "article"):
            self._buf += " | "  # Absatzgrenze: Kontext soll nicht über Blöcke hinweg zählen

    def handle_data(self, data):
        self._buf = (self._buf + data)[-400:]
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            ctx = self._ctx.rsplit("|", 1)[-1]
            self.links.append((self._href, " ".join("".join(self._text).split()), " ".join(ctx.split())))
            self._href = None


def asin_from_url(url: str) -> str | None:
    u = urlparse(url or "")
    if u.scheme not in ("http", "https") or not AMAZON_HOST.search(u.hostname or ""):
        return None
    m = ASIN_RE.search(unquote(u.path) + "/")
    return m.group(1) if m else None


def resolve_short(url: str, http) -> str:
    """amzn.to & Co. auf die Ziel-URL auflösen (nur Weiterleitungen lesen, nichts herunterladen)."""
    try:
        r = http.head(url, allow_redirects=True, timeout=10, headers=UA)
        return getattr(r, "url", "") or url
    except requests.RequestException:
        return url


def extract_links(html: str, http=None) -> list[dict]:
    """[{asin, text, slug}] aus HTML. slug = Wörter aus dem Produktpfad der Amazon-URL (z. B. "Fanttik-S2-Pro")."""
    p = _Links()
    try:
        p.feed(html or "")
    except Exception:  # noqa: BLE001 - kaputtes HTML ist kein Grund abzubrechen
        pass
    out, seen = [], set()
    for href, text, ctx in p.links:
        host = urlparse(href).hostname or ""
        if host in SHORT_HOSTS and http is not None:
            href = resolve_short(href, http)
        asin = asin_from_url(href)
        if not asin or asin in seen:
            continue
        seen.add(asin)
        path = unquote(urlparse(href).path)
        slug = path.split("/dp/")[0].split("/gp/")[0].strip("/").replace("-", " ") if "/dp/" in path or "/gp/" in path else ""
        out.append({"asin": asin, "text": text, "slug": slug, "context": ctx})
    return out


def fetch_page(url: str, http) -> str:
    try:
        r = http.get(url, timeout=15, headers=UA)
        if r.status_code == 200 and len(r.content) < 5 * 1024 * 1024:
            return r.text
        log.info("Quellseite nicht lesbar (%s): %s", r.status_code, url)
    except requests.RequestException as exc:
        log.info("Quellseite nicht lesbar: %s (%s)", url, type(exc).__name__)
    return ""


def links_for_sources(urls: list[str], htmls: list[str] = (), http=None) -> list[dict]:
    """Amazon-Produktlinks aus Feed-HTML und, falls dort keine stehen, aus den Quellseiten selbst."""
    http = http or requests
    links: list[dict] = []
    for h in htmls:
        links += extract_links(h, http)
    if not links:
        for url in urls:
            links += extract_links(fetch_page(url, http), http)
    seen, out = set(), []
    for l in links:
        if l["asin"] not in seen:
            seen.add(l["asin"])
            out.append(l)
    return out


def _tokens(text: str) -> set[str]:
    """Wörter ab 3 Zeichen sowie Zahlen und Modellkürzel mit Ziffer (z. B. "s2", "g6", "7")."""
    return {t for t in re.findall(r"[a-z0-9äöüß]+", (text or "").lower())
            if t not in STOP and (len(t) >= 3 or any(c.isdigit() for c in t))}


UNIT = re.compile(r"^\d+(w|kw|mah|wh|v|a|gb|tb|mb|hz|khz|mm|cm|m|l|ml|kg|g|er|x|k|p|fps|pa|zoll)$")


def _models(text: str) -> set[str]:
    """Modellkürzel ("s2", "g6", "c200", "a1695", "7"), ohne Preise, Jahreszahlen, Mengen und Einheiten ("165w", "25000")."""
    text = re.sub(r"\d+[.,]\d+|\b(19|20)\d{2}\b", " ", (text or "").lower())
    out = set()
    for t in re.findall(r"[a-z0-9]+", text):
        if not any(c.isdigit() for c in t) or UNIT.match(t):
            continue
        if t.isdigit() and len(t) > 2:  # reine Zahlen nur kurz (Generation "3", "7"), sonst Mengenangabe
            continue
        if re.fullmatch(r"[a-z]{1,4}\d{1,5}[a-z]{0,3}", t) or t.isdigit():
            out.add(t)
    return out


def _conflict(mine: set[str], theirs: set[str]) -> bool:
    """Widersprechen sich die Modellangaben? Kürzel ("s2") nur mit Kürzeln, Zahlen ("7") nur mit Zahlen vergleichen."""
    for kind in (str.isdigit, lambda t: not t.isdigit()):
        a, b = {t for t in mine if kind(t)}, {t for t in theirs if kind(t)}
        if a and b and not a & b:
            return True
    return False


def attach_asins(article: dict, links: list[dict]) -> int:
    """Ordnet jeder Produktidee die passendste ASIN zu (jede ASIN höchstens einmal). Gibt die Zahl der Zuordnungen zurück.
    Passend heißt: mindestens zwei gemeinsame Wörter (oder ein Wort, wenn die Idee nur aus einem besteht)."""
    ideas = article.get("shopping") or []
    used = {i.get("asin") for i in ideas if i.get("asin")}
    done = 0
    # Hauptprodukt: Die erste Produktidee ist das Produkt der Meldung, der erste Amazon-Link der Quelle meist auch.
    # Amazon-Titel weichen oft ab ("Fanttik Elektroschrauber ..." statt "Fanttik S2 Pro"); dann reicht die Marke.
    if ideas and links and not ideas[0].get("asin") and links[0]["asin"] not in used:
        first, l0 = ideas[0], links[0]
        words = re.findall(r"[a-z0-9äöüß]+", (first.get("query") or first.get("label") or "").lower())
        brand = words[0] if words and len(words[0]) >= 3 and words[0] not in STOP else ""
        theirs = _models(f"{l0['text']} {l0['slug']}") or _models(l0.get('context', ''))
        mine = _models(f"{first.get('query', '')} {first.get('label', '')}")
        if brand and brand in _tokens(f"{l0['text']} {l0['slug']} {l0.get('context', '')}") \
                and not _conflict(mine, theirs):
            first["asin"] = l0["asin"]
            used.add(l0["asin"])
            done += 1
    for idea in ideas:
        if idea.get("asin"):
            continue
        want = _tokens(f"{idea.get('query', '')} {idea.get('label', '')}")
        if not want:
            continue
        models = _models(f"{idea.get('query', '')} {idea.get('label', '')}")
        best, best_score = None, 0
        for l in links:
            if l["asin"] in used:
                continue
            have = _tokens(f"{l['text']} {l['slug']} {l.get('context', '')}")
            theirs = _models(f"{l['text']} {l['slug']}") or _models(l.get('context', ''))
            if _conflict(models, theirs):  # andere Modellnummer: "Fenix 7" ist nicht "Fenix 8"
                continue
            score = len({t for t in want & have if not t.isdigit()})  # reine Zahlen zählen nicht als Treffer
            if score > best_score:
                best, best_score = l, score
        if best and best_score >= min(2, len(want)):
            idea["asin"] = best["asin"]
            used.add(best["asin"])
            done += 1
    return done


def backfill(store: Store, http=None) -> int:
    """Für Beiträge mit Produktideen ohne ASIN die Quellseiten lesen und ASINs zuordnen."""
    total = 0
    for rec in store.all():
        a = rec.get("article") or {}
        ideas = a.get("shopping") or []
        if rec["status"] not in ("draft", "live", "held") or not ideas or all(i.get("asin") for i in ideas):
            continue
        if rec.get("asin_checked"):
            continue
        urls = [s.get("url") for s in (rec.get("sources") or [rec.get("source") or {}]) if s.get("url")]
        n = attach_asins(a, links_for_sources(urls, http=http))
        rec["asin_checked"] = True  # Quellen nur einmal lesen
        store.save(rec)
        total += n
        if n:
            log.info("%s: %s direkte Amazon-Links", rec["id"], n)
    return total
