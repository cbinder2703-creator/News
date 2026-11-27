import json
import re
from datetime import datetime, timezone
from pathlib import Path

from newsbot import pipeline
from newsbot.config import load_config
from newsbot.ingest import SourceItem
from newsbot.store import Store
from newsbot.writer import StubWriter

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def test_homepage_tells_google_name_logo_and_description_and_links_rubrik_pages(tmp_path):
    cfg = load_config(ROOT / "config.yaml")
    cfg.site_url = "https://news.example"
    store = Store(tmp_path / "d")
    items = [SourceItem("Neue Powerbank im Angebot", "Teaser", "https://x.example/1", "Q", NOW)]
    pipeline.generate(cfg, store, StubWriter(), items=items, now=NOW)
    rec = store.all()[0]
    rec["article"]["rubrik"] = "Deal-Check"
    store.save(rec)
    out = pipeline.build(cfg, store, tmp_path / "pub")
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "<title>DealPuls – " in home and cfg.brand_description in home
    data = [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', home, re.S)][0]
    types = {d["@type"]: d for d in data}
    assert types["WebSite"]["name"] == "DealPuls" and types["Organization"]["logo"].endswith("/static/logo-512.png")
    assert (out / "static" / "logo-512.png").exists() and (out / "static" / "favicon-48.png").exists()
    assert 'href="/deals/"' in home  # Rubrik in der Navigation
    deals = (out / "deals" / "index.html").read_text(encoding="utf-8")
    assert "<h1>Deals</h1>" in deals and "BreadcrumbList" in deals
    assert "/deals/</loc>" in (out / "sitemap.xml").read_text(encoding="utf-8")
    assert not (out / "neuheiten").exists()  # leere Rubriken bekommen keine Seite


def test_old_deals_get_a_notice_and_articles_link_to_newer_posts(tmp_path):
    cfg = load_config(ROOT / "config.yaml")
    cfg.site_url = "https://news.example"
    store = Store(tmp_path / "d")
    titles = ["Powerbank im Angebot", "Neuer Saugroboter günstig", "Kopfhörer zum Bestpreis", "Monitor stark reduziert",
              "Tablet mit Stift billiger", "Smartwatch mit langem Akku"]
    items = [SourceItem(t, "Teaser", f"https://x.example/{i}", "Q", NOW) for i, t in enumerate(titles)]
    cfg.articles_per_run = 6
    pipeline.generate(cfg, store, StubWriter(), items=items, now=NOW)
    recs = store.all()
    for n, r in enumerate(recs):
        r["article"]["rubrik"] = "Deal-Check"
        r["created_at"] = "2020-01-01T10:00:00+00:00" if n == 0 else "2099-01-01T10:00:00+00:00"
        store.save(r)
    out = pipeline.build(cfg, store, tmp_path / "pub")
    old = (out / "a" / recs[0]["slug"] / "index.html").read_text(encoding="utf-8")
    new = (out / "a" / recs[1]["slug"] / "index.html").read_text(encoding="utf-8")
    assert 'class="stale"' in old and 'class="stale"' not in new
    assert 'class="more-posts"' in old and 'href="/deals/">Alle Deals' in old
