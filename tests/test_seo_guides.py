import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from newsbot import pipeline
from newsbot.config import load_config
from newsbot.editor import Editor, commerce_rule
from newsbot.guides import Guide, StubGuideWriter
from newsbot.ingest import SourceItem
from newsbot.store import Store
from newsbot.writer import FAQ, StubWriter, Writer

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg():
    c = load_config(ROOT / "config.yaml")
    c.site_url = "https://news.example"
    c.review = False
    c.videos_for_recent = 0  # hier geht es nicht um Videos
    c.guide_topics = [{"slug": "saugroboter", "title": "Saugroboter", "keyword": "Saugroboter kaufen", "category": "Smart Home"},
                      {"slug": "powerbank", "title": "Powerbank", "keyword": "Powerbank kaufen"}]
    return c


def item(title, link, hours=1):
    return SourceItem(title, f"Teaser {title}", link, "heise", NOW - timedelta(hours=hours))


def ld_blocks(html: str) -> list[dict]:
    return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def test_config_loads_guides_and_commerce():
    c = load_config(ROOT / "config.yaml")
    assert c.commerce is True and c.guides_enabled is True and len(c.guide_topics) >= 10
    assert all(t["slug"] and t["title"] for t in c.guide_topics)


def test_seo_fields_are_length_limited():
    a = StubWriter().write([item("x", "u")]).model_copy(update={
        "seo_title": "s" * 200, "meta_description": "m" * 400, "faq": [FAQ(question="q", answer="a")] * 9})
    n = a.normalized()
    assert len(n.seo_title) <= 65 and len(n.meta_description) <= 160 and len(n.faq) == 4


def test_unknown_guide_slug_is_dropped_and_slug_uses_keyword(cfg, tmp_path):
    store = Store(tmp_path)
    (ok,) = pipeline.generate(cfg, store, StubWriter("saugroboter"), items=[item("Saugroboter mit Lücke", "a")], now=NOW)
    (bad,) = pipeline.generate(cfg, store, StubWriter("gibts-nicht"), items=[item("Anderes Thema hier", "b")], now=NOW)
    assert ok["article"]["guide"] == "saugroboter" and bad["article"]["guide"] == ""
    assert ok["slug"].startswith("saugroboter-mit-luecke-")


def test_prompts_contain_guides_and_commerce_rule(cfg, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-nicht-echt")
    assert "saugroboter: Saugroboter" in Writer(cfg).system
    assert "Kaufbezug hat Vorrang" in Editor(cfg).system and "Saugroboter" in Editor(cfg).system
    cfg.commerce = False
    assert commerce_rule(cfg) == "" and "Kaufbezug" not in Editor(cfg).system


def test_guides_are_drafts_until_approved_and_new_version_keeps_old_online(cfg, tmp_path):
    store = Store(tmp_path / "d")
    cfg.guides_per_run = 1
    cfg.review = True  # Freigabe-Ablauf; im Modus auto gehen Kaufberater direkt online (eigener Test)
    (g,) = pipeline.generate_guides(cfg, store, StubGuideWriter())
    assert g["id"] == "kb-saugroboter" and g["article"] is None and g["draft"]
    assert "kb-saugroboter" in pipeline.drafts_markdown(store, cfg)
    out = pipeline.build(cfg, store, tmp_path / "public")
    assert not (out / "kaufberater" / "saugroboter").exists()  # Entwurf ist nicht öffentlich

    assert [r["id"] for r in pipeline.approve(cfg, store, "kb-saugroboter")] == ["kb-saugroboter"]
    assert store.guide("saugroboter")["article"] and not store.guide("saugroboter")["draft"]
    (second,) = pipeline.generate_guides(cfg, store, StubGuideWriter())  # nächster fehlender
    assert second["slug"] == "powerbank"
    assert pipeline.generate_guides(cfg, store, StubGuideWriter()) == []  # alles vorhanden

    class NewVersion(StubGuideWriter):
        def write(self, topic):
            return super().write(topic).model_copy(update={"headline": "Neue Fassung"})

    pipeline.generate_guides(cfg, store, NewVersion(), only="saugroboter")
    g = store.guide("saugroboter")
    assert g["draft"]["headline"] == "Neue Fassung" and g["article"]["headline"] != "Neue Fassung"
    with pytest.raises(ValueError):
        pipeline.generate_guides(cfg, store, StubGuideWriter(), only="unbekannt")


def test_site_has_seo_structure_and_internal_links(cfg, tmp_path):
    store = Store(tmp_path / "d")
    cfg.guides_per_run = 2
    pipeline.generate_guides(cfg, store, StubGuideWriter())
    pipeline.approve(cfg, store, "alle")
    pipeline.generate(cfg, store, StubWriter("saugroboter"), items=[item("Saugroboter mit Lücke", "a"),
                                                                  item("Zweite Meldung", "b", 2)], now=NOW)
    out = pipeline.build(cfg, store, tmp_path / "public")
    rec = store.live()[0]
    page = (out / "a" / rec["slug"] / "index.html").read_text(encoding="utf-8")
    a = rec["article"]
    assert f"<title>{a['seo_title']} – " in page
    assert f'name="description" content="{a["meta_description"]}"' in page
    assert "/kaufberater/saugroboter/" in page and "Häufige Fragen" in page
    types = {b["@type"] for b in ld_blocks(page)}
    assert {"NewsArticle", "BreadcrumbList"} <= types
    news = next(b for b in ld_blocks(page) if b["@type"] == "NewsArticle")
    assert news["dateModified"] and news["keywords"] == a["focus_keyword"]
    related = (out / "a" / store.live()[1]["slug"] / "index.html").read_text(encoding="utf-8")
    assert f"/a/{rec['slug']}/" in related  # verwandte Beiträge derselben Kategorie

    guide = (out / "kaufberater" / "saugroboter" / "index.html").read_text(encoding="utf-8")
    assert "Darauf solltest du achten" in guide and f"/a/{rec['slug']}/" in guide  # Kaufberater listet die News
    assert "So triffst du die richtige Wahl" in guide and "Wir testen keine Produkte" not in guide
    assert {"Article", "BreadcrumbList"} <= {b["@type"] for b in ld_blocks(guide)}
    assert (out / "media" / "kb-saugroboter" / "card.jpg").exists()

    sitemap = (out / "sitemap.xml").read_text(encoding="utf-8")
    for path in ("/kaufberater/saugroboter/", "/kaufberater/", f"/a/{rec['slug']}/", "/so-arbeiten-wir/"):
        assert f"https://news.example{path}</loc>" in sitemap
    # Thema mit nur einem Beitrag: erreichbar, aber nicht im Index und nicht in der Sitemap (dünne Seite)
    assert "/thema/demo/</loc>" not in sitemap
    assert 'content="noindex, follow"' in (out / "thema" / "demo" / "index.html").read_text(encoding="utf-8")
    assert (out / "kaufberater" / "index.html").exists()
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "/kaufberater/powerbank/" in home and '"@type": "WebSite"' in home


def test_guide_normalization_limits():
    g = StubGuideWriter().write({"slug": "x", "title": "X"}).model_copy(update={"seo_title": "t" * 99, "mistakes": ["m"] * 9})
    n = Guide.normalized(g)
    assert len(n.seo_title) <= 65 and len(n.mistakes) == 5


def test_guides_go_live_directly_in_auto_mode(cfg, tmp_path):
    store = Store(tmp_path / "d")
    cfg.guides_per_run = 1
    (g,) = pipeline.generate_guides(cfg, store, StubGuideWriter())
    assert g["article"] and g["draft"] is None
