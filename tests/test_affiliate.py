from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from newsbot import pipeline
from newsbot.affiliate import active_programs, build_shop_boxes, clean_query, link_for
from newsbot.config import load_config
from newsbot.ingest import SourceItem
from newsbot.store import Store
from newsbot.writer import ShopIdea, StubWriter

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
AMAZON = {"name": "Amazon", "kind": "amazon", "enabled": True, "domain": "www.amazon.de", "tag": "meinblog-21"}
OTTO = {"name": "OTTO", "kind": "template", "enabled": True,
        "search_url": "https://www.otto.de/suche/{query}/",
        "link_template": "https://www.awin1.com/cread.php?awinmid=1234&awinaffid=99&ued={url}"}


@pytest.fixture
def cfg():
    c = load_config(ROOT / "config.yaml")
    c.site_url = "https://news.example"
    c.review = False
    return c


def items():
    return [SourceItem("Neuer Router vorgestellt", "Teaser", "https://x.example/1", "heise", NOW - timedelta(hours=1))]


def test_live_config_uses_the_dealpuls_amazon_tag(cfg):
    progs = active_programs(cfg)
    assert cfg.affiliate_enabled is True and [p["tag"] for p in progs] == ["dealpuls-21"]
    (box,) = build_shop_boxes(cfg, [{"label": "Router", "query": "WLAN Router"}])
    assert box["links"][0]["url"] == "https://www.amazon.de/s?k=WLAN+Router&tag=dealpuls-21"


def test_unfinished_programs_stay_off(cfg):
    cfg.affiliate_enabled = True
    cfg.affiliate_programs = [dict(AMAZON, tag=""), dict(AMAZON, tag="DEINE_ID-21"), dict(OTTO, enabled=False),
                              dict(OTTO, link_template="https://awin1.com/?awinmid=DEINE_OTTO_MERCHANT_ID&ued={url}"),
                              dict(OTTO, link_template="http://insecure.example/?u={url}")]
    assert active_programs(cfg) == []


def test_amazon_search_link_carries_tag_and_encoded_query():
    url = link_for(AMAZON, "WLAN Router & Mesh")
    parsed = urlparse(url)
    assert parsed.netloc == "www.amazon.de" and parsed.path == "/s"
    assert parse_qs(parsed.query) == {"k": ["WLAN Router & Mesh"], "tag": ["meinblog-21"]}


def test_template_link_wraps_encoded_search_url():
    url = link_for(OTTO, "WLAN Router")
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://www.awin1.com/cread.php?") and q["awinmid"] == ["1234"]
    # parse_qs hat "ued" einmal entschlüsselt: übrig bleibt die Ziel-URL mit korrekt kodiertem Suchbegriff
    assert q["ued"][0] == "https://www.otto.de/suche/WLAN%20Router/"
    assert "ued=https%3A%2F%2Fwww.otto.de%2Fsuche%2FWLAN%2520Router%2F" in url  # genau einmal kodiert für Awin


def test_queries_are_sanitized_deduped_and_limited(cfg):
    cfg.affiliate_enabled, cfg.affiliate_programs, cfg.affiliate_max = True, [AMAZON, OTTO], 2
    ideas = [{"label": "A", "query": "WLAN Router"}, {"label": "dup", "query": "wlan router"},
             {"label": "bad", "query": "https://evil.example/x"}, {"label": "B", "query": "Sicherheitsschlüssel"},
             {"label": "C", "query": "Powerbank"}]
    boxes = build_shop_boxes(cfg, ideas)
    assert [b["query"] for b in boxes] == ["WLAN Router", "Sicherheitsschlüssel"]
    assert all(len(b["links"]) == 2 for b in boxes)
    assert clean_query("a " * 40) is None and clean_query("  ") is None and clean_query("<b>x</b>") is None


def test_article_page_has_labelled_box_only_when_active(cfg, tmp_path):
    cfg.affiliate_enabled, cfg.affiliate_programs = True, [AMAZON, OTTO]
    store = Store(tmp_path / "d")
    (rec,) = pipeline.generate(cfg, store, StubWriter(), items=items(), now=NOW)
    out = pipeline.build(cfg, store, tmp_path / "pub")
    html = (out / "a" / rec["slug"] / "index.html").read_text(encoding="utf-8")
    assert "Hier bekommst du es" in html and "Affiliate-Link (Werbung)" in html and '<sup class="aff">*</sup>' in html
    assert 'rel="sponsored nofollow noopener"' in html and "tag=meinblog-21" in html
    assert "Als Amazon-Partner verdiene ich an qualifizierten Verkäufen." in html      # Pflichthinweis
    assert "Affiliate-Links" in (out / "datenschutz" / "index.html").read_text(encoding="utf-8")
    assert html.index("Unsere Einschätzung") < html.index("Hier bekommst du es")  # Kasten nach der Einschätzung
    assert html.count('class="buy"') >= 2  # Schnell-Button unter den Kernpunkten + Kasten

    cfg.affiliate_enabled = False
    out2 = pipeline.build(cfg, store, tmp_path / "pub2")
    off = (out2 / "a" / rec["slug"] / "index.html").read_text(encoding="utf-8")
    assert "Hier bekommst du es" not in off and "sponsored" not in off and "amazon" not in off.lower()


def test_no_amazon_notice_without_amazon(cfg, tmp_path):
    cfg.affiliate_enabled, cfg.affiliate_programs = True, [OTTO]
    store = Store(tmp_path / "d")
    (rec,) = pipeline.generate(cfg, store, StubWriter(), items=items(), now=NOW)
    out = pipeline.build(cfg, store, tmp_path / "pub")
    assert "Als Amazon-Partner" not in (out / "a" / rec["slug"] / "index.html").read_text(encoding="utf-8")


def test_social_texts_never_contain_affiliate_links(cfg, tmp_path):
    cfg.affiliate_enabled, cfg.affiliate_programs = True, [AMAZON, OTTO]
    store = Store(tmp_path / "d")
    (rec,) = pipeline.generate(cfg, store, StubWriter(), items=items(), now=NOW)
    a = rec["article"]
    for field in ("instagram_caption", "tiktok_caption", "facebook_text", "narration"):
        assert "amazon" not in a[field].lower() and "awin" not in a[field].lower() and "tag=" not in a[field]


def test_drafts_summary_previews_shop_links(cfg, tmp_path):
    cfg.review = True
    cfg.affiliate_enabled, cfg.affiliate_programs = True, [AMAZON]
    store = Store(tmp_path / "d")
    pipeline.generate(cfg, store, StubWriter(), items=items(), now=NOW)
    md = pipeline.drafts_markdown(store, cfg)
    assert "Produktideen" in md and "tag=meinblog-21" in md
    assert "keine Links" in pipeline.drafts_markdown(store)  # ohne Konfiguration nur die Ideen


def test_shop_ideas_are_limited_by_normalization():
    art = StubWriter().write(items()).model_copy(update={"shopping": [ShopIdea(label="x" * 200, query="q" * 200)] * 6})
    n = art.normalized()
    assert len(n.shopping) == 4 and len(n.shopping[0].label) <= 60 and len(n.shopping[0].query) <= 60
