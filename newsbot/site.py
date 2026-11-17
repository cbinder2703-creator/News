"""Statische Website (GitHub Pages / jeder Webspace) aus den gespeicherten Beiträgen bauen."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Config
from .media import make_images, make_narrated_video, make_video

PKG = Path(__file__).parent
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def de_date(value: str) -> str:
    d = _dt(value)
    return f"{d.day}. {MONTHS[d.month - 1]} {d.year}, {d:%H:%M} Uhr"


def rfc822(value: str) -> str:
    return _dt(value).strftime("%a, %d %b %Y %H:%M:%S +0000")


def build_site(cfg: Config, records: list[dict], out: Path, audio_dir: Path | None = None) -> dict[str, Path]:
    """Schreibt die Seite nach `out`. Gibt {article_id: Video-Pfad} der vorhandenen Videos zurück."""
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "static").mkdir()
    shutil.copy(PKG / "static" / "style.css", out / "static" / "style.css")
    (out / ".nojekyll").write_text("")

    env = Environment(loader=FileSystemLoader(PKG / "templates"), autoescape=select_autoescape(default=True))
    env.filters.update(de_date=de_date, rfc822=rfc822)
    env.globals.update(cfg=cfg, base=cfg.base_path, year=datetime.now().year)

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
        page = out / "a" / rec["slug"]
        page.mkdir(parents=True)
        (page / "index.html").write_text(
            env.get_template("article.html").render(rec=rec, a=rec["article"], title=rec["article"]["headline"]),
            encoding="utf-8",
        )

    render = lambda tpl, path, **kw: _write(out / path, env.get_template(tpl).render(**kw))  # noqa: E731
    render("index.html", "index.html", records=records, title=cfg.brand_name)
    render("feed.xml", "feed.xml", records=records[:30])
    render("sitemap.xml", "sitemap.xml", records=records)
    for slug, title in (("ueber-uns", "Über uns"), ("impressum", "Impressum"), ("datenschutz", "Datenschutz")):
        render(f"{slug}.html", f"{slug}/index.html", title=title)
    _write(out / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {cfg.site_url}/sitemap.xml\n")
    return videos


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
