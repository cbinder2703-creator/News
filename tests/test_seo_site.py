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
