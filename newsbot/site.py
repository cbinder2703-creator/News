"""Statische Website (GitHub Pages / jeder Webspace) aus den gespeicherten Beiträgen bauen.

SEO-Bausteine: eigene SEO-Titel und Meta-Beschreibungen, sprechende URLs, Brotkrumen (auch als strukturierte Daten),
Themen- und Kaufberater-Übersichten, interne Verlinkung (News ↔ Kaufberater, verwandte Beiträge), Sitemap mit lastmod.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .affiliate import active_programs, build_shop_boxes, has_amazon
from .config import Config
from .media import make_cards, make_images, make_narrated_video, make_video
from .store import slugify

PKG = Path(__file__).parent
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
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


def build_site(cfg: Config, records: list[dict], out: Path, audio_dir: Path | None = None,
               guides: list[dict] | None = None) -> dict[str, Path]:
    """Schreibt die Seite nach `out`. Gibt {article_id: Video-Pfad} der vorhandenen Videos zurück."""
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "static").mkdir()
    shutil.copy(PKG / "static" / "style.css", out / "static" / "style.css")
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
    env.filters.update(de_date=de_date, de_day=de_day, rfc822=rfc822)
    env.globals.update(cfg=cfg, base=cfg.base_path, year=datetime.now().year, has_guides=bool(guides),
                       affiliate_on=bool(active_programs(cfg)), amazon_on=has_amazon(cfg))

    videos: dict[str, Path] = {}
    for n, rec in enumerate(records):
        media_dir = out / "media" / rec["id"]
        make_images(rec, cfg.brand_name, cfg.accent, media_dir)
        rec["has_video"] = False
        if n < cfg.videos_for_recent:
            target = media_dir / "video.mp4"
            audio = audio_dir / f"{rec['id']}.mp3" if audio_dir else None
            vid = None
            if audio and audio.exists():  # mit Sprecherstimme und Untertiteln
                vid = make_narrated_video(rec, cfg.brand_name, cfg.accent, cfg.host, audio, target)
            if vid is None:  # ohne Stimme: stummes Folienvideo
                vid = make_video(rec, cfg.brand_name, cfg.accent, cfg.host, target)
            if vid:
                videos[rec["id"]] = vid
                rec["has_video"] = True

    for rec in records:
        a = rec["article"]
        cat = categories[rec["cat_slug"]]
        related = [r for r in cat["records"] if r["id"] != rec["id"]][:3]
        guide = guide_by_slug.get(a.get("guide") or "")
        crumbs = [("Start", "/"), (cat["name"], f"/thema/{cat['slug']}/"), (a["headline"], f"/a/{rec['slug']}/")]
        page = out / "a" / rec["slug"]
        page.mkdir(parents=True)
        shop = build_shop_boxes(cfg, a.get("shopping", []))
        (page / "index.html").write_text(
            env.get_template("article.html").render(
                rec=rec, a=a, title=a.get("seo_title") or a["headline"], shop=shop, cat=cat, related=related,
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
    render("index.html", "index.html", records=records, guides=guides[:6], title=cfg.brand_name)
    if guides:
        render("guides.html", "kaufberater/index.html", guides=guides, title="Kaufberater",
               canonical="/kaufberater/", desc=f"Alle Kaufberater von {cfg.brand_name}: worauf du beim Kauf achten solltest.")
    render("topics.html", "thema/index.html", cats=cats, title="Alle Themen", canonical="/thema/")
    for cat in cats:
        crumbs = [("Start", "/"), (cat["name"], f"/thema/{cat['slug']}/")]
        render("category.html", f"thema/{cat['slug']}/index.html", cat=cat, title=f"{cat['name']}: aktuelle Beiträge",
               canonical=f"/thema/{cat['slug']}/", crumbs=crumbs, crumbs_ld=breadcrumb_ld(cfg, crumbs),
               desc=f"Aktuelle Beiträge und Einordnungen zum Thema {cat['name']} bei {cfg.brand_name}.")
    render("feed.xml", "feed.xml", records=records[:30])
    render("sitemap.xml", "sitemap.xml", records=records, guides=guides, cats=cats, pages=STATIC_PAGES)
    for slug, title in STATIC_PAGES:
        render(f"{slug}.html", f"{slug}/index.html", title=title, canonical=f"/{slug}/")
    _write(out / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {cfg.site_url}/sitemap.xml\n")
    return videos


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
