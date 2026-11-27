"""Statische Website (GitHub Pages / jeder Webspace) aus den gespeicherten Beiträgen bauen.

SEO-Bausteine: eigene SEO-Titel und Meta-Beschreibungen, sprechende URLs, Brotkrumen (auch als strukturierte Daten),
Themen- und Kaufberater-Übersichten, interne Verlinkung (News ↔ Kaufberater, verwandte Beiträge), Sitemap mit lastmod.
"""
from __future__ import annotations

import hashlib
import shutil

from PIL import Image
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from .affiliate import active_programs, build_shop_boxes, has_amazon
from .config import Config
from .icons import thumb
from .media import make_cards, make_images, make_narrated_video, make_video
from .store import slugify

PKG = Path(__file__).parent
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
# Rubrik-Seiten: feste, gut verlinkte Übersichten (Navigation und Unterlinks bei Google).
RUBRIK_PAGES = (
    ("deals", "Deals", ("Deal-Check",), "Deals: aktuelle Technik-Angebote im Check",
     "Aktuelle Technik-Deals im Check: was du für den Preis bekommst und für wen sich das Angebot lohnt."),
    ("neuheiten", "Neuheiten", ("Neuheiten-Check",), "Neuheiten: neue Geräte kurz erklärt",
     "Neue Smartphones, Gadgets und Geräte: was neu ist, was es kann und für wen es spannend wird."),
    ("ratgeber", "Ratgeber", ("Ratgeber", "Lohnt sich das?"), "Ratgeber: so findest du das passende Gerät",
     "Ratgeber und Kaufhilfen: worauf es ankommt, damit du das Gerät findest, das zu dir passt."),
    ("kurz-erklaert", "Kurz erklärt", ("Kurz erklärt",), "Kurz erklärt: Technik-News verständlich",
     "Technik-News in einfachen Worten: was passiert ist und was du davon hast."),
)

RUBRIK_OF = {slug: rubs for slug, _, rubs, _, _ in RUBRIK_PAGES}
MIN_TOPIC_POSTS = 3

STATIC_DESC = {
    "ueber-uns": "Über {brand}: wer hinter der Seite steht, wie die Beiträge entstehen und wie wir uns finanzieren.",
    "so-arbeiten-wir": "So arbeitet {brand}: wie Deals und Beiträge entstehen, wie wir Preise angeben und Fehler korrigieren.",
    "impressum": "Impressum von {brand}: Anbieter, Kontakt und Angaben nach § 5 DDG.",
    "datenschutz": "Datenschutzerklärung von {brand}: welche Daten beim Besuch der Seite verarbeitet werden und welche Rechte du hast.",
}


def list_ld(cfg, records, path: str, name: str, guides=None) -> dict:
    """CollectionPage mit Liste der Beiträge: hilft Google, Übersichtsseiten zu verstehen."""
    items = [(f"{cfg.site_url}/a/{r['slug']}/", r["article"]["headline"]) for r in records[:30]]
    items += [(f"{cfg.site_url}/kaufberater/{g['slug']}/", g["article"]["headline"]) for g in (guides or [])[:30]]
    return {"@context": "https://schema.org", "@type": "CollectionPage", "name": name, "url": cfg.site_url + path,
            "inLanguage": "de-DE",
            "mainEntity": {"@type": "ItemList", "itemListElement": [
                {"@type": "ListItem", "position": n, "url": u, "name": t} for n, (u, t) in enumerate(items, 1)]}}

STATIC_PAGES = (("ueber-uns", "Über uns"), ("so-arbeiten-wir", "So arbeiten wir"),
                ("impressum", "Impressum"), ("datenschutz", "Datenschutz"))


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def de_date(value: str) -> str:
    d = _dt(value)
    return f"{d.day}. {MONTHS[d.month - 1]} {d.year}, {d:%H:%M} Uhr"


def de_day(value: str) -> str:
    d = _dt(value)
    return f"{d.day}. {MONTHS[d.month - 1]} {d.year}"


def rfc822(value: str) -> str:
    return _dt(value).strftime("%a, %d %b %Y %H:%M:%S +0000")


def breadcrumb_ld(cfg: Config, crumbs: list[tuple[str, str]]) -> dict:
    """crumbs: [(Name, Pfad ab Website-Wurzel, z. B. "/thema/ki/")]."""
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": n, "name": name, "item": cfg.site_url + path}
                                for n, (name, path) in enumerate(crumbs, 1)]}


def article_text(a: dict) -> str:
    """Text, aus dem sich ein passendes Symbol ableiten lässt (Überschrift, Suchwort, Rubrik, Produktideen)."""
    ideas = " ".join(f"{i.get('label', '')} {i.get('query', '')}" for i in a.get("shopping", []))
    return f"{a.get('headline', '')} {a.get('focus_keyword', '')} {a.get('category', '')} {ideas}"


def image_html(rec: dict, base: str, hero: bool = False, eager: bool = False, sizes: str = "") -> Markup:
    """Titelbild eines Beitrags: das Foto, sonst ein Symbol auf Farbverlauf. Immer im Format 1200:630."""
    a = rec["article"]
    if rec.get("has_photo"):
        cls = ' class="media hero"' if hero else ' class="media"'
        loading = ' fetchpriority="high"' if hero else f' loading="{"eager" if eager else "lazy"}"'
        sizes = sizes or ("(max-width:1032px) calc(100vw - 32px), 1000px" if hero
                          else "(max-width:600px) calc(100vw - 32px), (max-width:900px) 46vw, 380px")
        src = f"{base}/media/{rec['id']}/{rec.get('photo_file') or 'photo'}"
        return Markup(f'<img{cls} src="{src}.jpg" srcset="{src}-640.jpg 640w, {src}.jpg 1200w" '
                      f'sizes="{sizes}" alt="{escape(a.get("image_alt", ""))}" width="1200" height="630"{loading}>')
    return thumb(article_text(a), a.get("rubrik") or a.get("category", ""), a.get("icon", ""),
                 "thumb hero" if hero else "thumb")


def guide_image_html(g: dict) -> Markup:
    return thumb(f"{g['topic'].get('title', '')} {g['topic'].get('keyword', '')} {g['topic'].get('category', '')}",
                 "Kaufberater", "", "thumb")


def build_site(cfg: Config, records: list[dict], out: Path, audio_dir: Path | None = None,
               guides: list[dict] | None = None, photos_dir: Path | None = None) -> dict[str, Path]:
    """Schreibt die Seite nach `out`. Gibt {article_id: Video-Pfad} der vorhandenen Videos zurück."""
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "static").mkdir()
    for name in ("style.css", "logo.svg", "logo-512.png", "favicon.svg", "favicon-32.png", "favicon-48.png", "favicon-192.png", "contact.js", "theme.js", "site.js"):
        shutil.copy(PKG / "static" / name, out / "static" / name)
    for name in ("favicon.ico", "apple-touch-icon.png"):  # Browser suchen diese Dateien an der Wurzel
        shutil.copy(PKG / "static" / name, out / name)
    shutil.copytree(PKG / "static" / "fonts", out / "static" / "fonts")
    if cfg.admin_api_url:  # Admin-Seite nur, wenn ein Freigabe-Dienst eingetragen ist
        shutil.copy(PKG / "static" / "admin.js", out / "static" / "admin.js")
    (out / ".nojekyll").write_text("")

    guides = [g for g in (guides or []) if g.get("article")]  # nur freigegebene Fassungen
    guide_by_slug = {g["slug"]: g for g in guides}
    categories: dict[str, dict] = {}
    for rec in records:
        name = rec["article"]["category"]
        cat = categories.setdefault(slugify(name, 40), {"name": name, "slug": slugify(name, 40), "records": []})
        cat["records"].append(rec)
        rec["cat_slug"] = cat["slug"]

    env = Environment(loader=FileSystemLoader(PKG / "templates"), autoescape=select_autoescape(default=True))
    build_now = datetime.now(timezone.utc)
    env.filters.update(age_days=lambda v: max(0, (build_now - _dt(v)).days),
                       de_date=de_date, de_day=de_day, rfc822=rfc822, tagslug=lambda t: slugify(t or "", 30))
    css_version = hashlib.sha1(b"".join((PKG / "static" / n).read_bytes() for n in ("style.css", "admin.js", "contact.js", "theme.js", "site.js"))).hexdigest()[:10]
    env.globals.update(image_for=lambda rec, hero=False, eager=False, sizes="": image_html(rec, cfg.base_path, hero, eager, sizes),
                       guide_image=guide_image_html, cfg=cfg, base=cfg.base_path, asset_v=css_version, year=datetime.now().year, has_guides=bool(guides),
                       affiliate_on=bool(active_programs(cfg)), amazon_on=has_amazon(cfg))

    rubrik_pages = []
    for slug, name, rubs, title, intro in RUBRIK_PAGES:
        recs = [r for r in records if (r["article"].get("rubrik") or "") in rubs]
        if recs:
            rubrik_pages.append({"slug": slug, "name": name, "title": title, "intro": intro, "records": recs})
    env.globals["rubrik_nav"] = rubrik_pages

    videos: dict[str, Path] = {}
    for n, rec in enumerate(records):
        media_dir = out / "media" / rec["id"]
        make_images(rec, cfg.brand_name, cfg.accent, media_dir, cfg.show_sources)
        photo = photos_dir / f"{rec['id']}.jpg" if photos_dir else None
        rec["has_photo"] = bool(photo and photo.exists() and rec.get("photo"))
        if rec["has_photo"]:
            name = rec["photo_file"] = rec["slug"]  # sprechender Dateiname hilft der Bildersuche
            shutil.copy(photo, media_dir / f"{name}.jpg")
            img = Image.open(photo).convert("RGB")
            small = img.copy()
            small.thumbnail((640, 640))
            small.save(media_dir / f"{name}-640.jpg", "JPEG", quality=80, optimize=True, progressive=True)
            w, h = img.size  # Google empfiehlt Titelbilder zusätzlich in 1:1 und 4:3
            for suffix, cw in (("1x1", h), ("4x3", h * 4 // 3)):
                left = max(0, (w - cw) // 2)
                img.crop((left, 0, left + min(cw, w), h)).save(media_dir / f"{name}-{suffix}.jpg", "JPEG", quality=82,
                                                                optimize=True, progressive=True)
        rec["has_video"] = False
        if n < cfg.videos_for_recent:
            target = media_dir / "video.mp4"
            audio = audio_dir / f"{rec['id']}.mp3" if audio_dir else None
            vid = None
            if audio and audio.exists():  # mit Sprecherstimme und Untertiteln
                vid = make_narrated_video(rec, cfg.brand_name, cfg.accent, cfg.host, audio, target, show_sources=cfg.show_sources)
            if vid is None:  # ohne Stimme: stummes Folienvideo
                vid = make_video(rec, cfg.brand_name, cfg.accent, cfg.host, target, show_sources=cfg.show_sources)
            if vid:
                videos[rec["id"]] = vid
                rec["has_video"] = True

    for rec in records:
        a = rec["article"]
        cat = categories[rec["cat_slug"]]
        related = [r for r in cat["records"] if r["id"] != rec["id"]][:3]
        related_ids = {r["id"] for r in related} | {rec["id"]}
        latest = [r for r in records if r["id"] not in related_ids][:4]
        rub_page = next((rp for rp in rubrik_pages if (a.get("rubrik") or "") in RUBRIK_OF[rp["slug"]]), None)
        guide = guide_by_slug.get(a.get("guide") or "")
        crumbs = [("Start", "/"), (cat["name"], f"/thema/{cat['slug']}/"), (a["headline"], f"/a/{rec['slug']}/")]
        page = out / "a" / rec["slug"]
        page.mkdir(parents=True)
        shop = build_shop_boxes(cfg, a.get("shopping", []))
        (page / "index.html").write_text(
            env.get_template("article.html").render(
                rec=rec, a=a, title=a.get("seo_title") or a["headline"], shop=shop, cat=cat, related=related,
                latest=latest, rub_page=rub_page,
                guide=guide, crumbs=crumbs, crumbs_ld=breadcrumb_ld(cfg, crumbs)),
            encoding="utf-8")

    for g in guides:
        a = g["article"]
        make_cards(a["headline"], "Kaufberater", "Kaufberater  ·  KI-unterstützt", cfg.brand_name, cfg.accent,
                   g["topic"].get("category") or g["slug"], out / "media" / g["id"])
        news = [r for r in records if r["article"].get("guide") == g["slug"]][:6]
        crumbs = [("Start", "/"), ("Kaufberater", "/kaufberater/"), (g["topic"]["title"], f"/kaufberater/{g['slug']}/")]
        _write(out / "kaufberater" / g["slug"] / "index.html", env.get_template("guide.html").render(
            g=g, a=a, title=a.get("seo_title") or a["headline"], news=news, crumbs=crumbs,
            crumbs_ld=breadcrumb_ld(cfg, crumbs), shop=build_shop_boxes(cfg, a.get("shopping", []))))

    render = lambda tpl, path, **kw: _write(out / path, env.get_template(tpl).render(**kw))  # noqa: E731
    cats = sorted(categories.values(), key=lambda c: -len(c["records"]))
    for c in cats:  # Themen mit sehr wenigen Beiträgen sind für Google dünn: erreichbar, aber nicht im Index
        c["indexable"] = len(c["records"]) >= MIN_TOPIC_POSTS
    render("index.html", "index.html", records=records, guides=guides[:6], cats=cats[:8], title=cfg.brand_name)
    if guides:
        render("guides.html", "kaufberater/index.html", guides=guides, title="Kaufberater: worauf du beim Kauf achten solltest",
               canonical="/kaufberater/", list_ld=list_ld(cfg, [], "/kaufberater/", "Kaufberater", guides),
               desc=f"Kaufberater von {cfg.brand_name}: So findest du die passende Powerbank, den richtigen Saugroboter, Fernseher und mehr. Verständlich erklärt.")
    render("topics.html", "thema/index.html", cats=cats, title="Alle Themen", canonical="/thema/",
           desc=f"Alle Themen bei {cfg.brand_name}: Technik-Deals, Neuheiten und Kaufberatung, sortiert nach Bereichen.")
    for cat in cats:
        crumbs = [("Start", "/"), (cat["name"], f"/thema/{cat['slug']}/")]
        render("category.html", f"thema/{cat['slug']}/index.html", cat=cat, title=f"{cat['name']}: aktuelle Beiträge",
               robots=None if cat["indexable"] else "noindex, follow", list_ld=list_ld(cfg, cat["records"], f"/thema/{cat['slug']}/", cat["name"]),
               canonical=f"/thema/{cat['slug']}/", crumbs=crumbs, crumbs_ld=breadcrumb_ld(cfg, crumbs),
               desc=f"Aktuelle Beiträge und Einordnungen zum Thema {cat['name']} bei {cfg.brand_name}.")
    for rp in rubrik_pages:
        crumbs = [("Start", "/"), (rp["name"], f"/{rp['slug']}/")]
        render("rubrik.html", f"{rp['slug']}/index.html", rp=rp, title=rp["title"], canonical=f"/{rp['slug']}/",
               list_ld=list_ld(cfg, rp["records"], f"/{rp['slug']}/", rp["title"]),
               desc=rp["intro"], crumbs=crumbs, crumbs_ld=breadcrumb_ld(cfg, crumbs))
    render("feed.xml", "feed.xml", records=records[:30])
    render("sitemap.xml", "sitemap.xml", records=records, guides=guides, cats=cats, pages=STATIC_PAGES,
           rubriken=rubrik_pages)
    for slug, title in STATIC_PAGES:
        render(f"{slug}.html", f"{slug}/index.html", title=title, canonical=f"/{slug}/",
               desc=STATIC_DESC.get(slug, "").format(brand=cfg.brand_name))
    render("404.html", "404.html", title="Seite nicht gefunden", records=records[:6])
    if cfg.indexnow_key:
        _write(out / f"{cfg.indexnow_key}.txt", cfg.indexnow_key)
    if cfg.admin_api_url:
        render("admin.html", "admin/index.html", api_url=cfg.admin_api_url)  # nicht verlinkt, nicht in der Sitemap, noindex
    _write(out / "robots.txt", f"User-agent: *\nAllow: /\nDisallow: /admin/\n\nSitemap: {cfg.site_url}/sitemap.xml\n")
    return videos


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
