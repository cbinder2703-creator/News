from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from newsbot import pipeline
from newsbot.config import load_config
from newsbot.ingest import SourceItem, parse_feed, select
from newsbot.social import PublishError, publish_pending
from newsbot.store import Store, slugify
from newsbot.writer import Article, StubWriter

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
<item><title>Neue &lt;b&gt;KI&lt;/b&gt; erscheint</title><link>https://a.example/1</link>
<description>&lt;p&gt;Teaser &amp;amp; mehr&lt;/p&gt;</description><pubDate>Mon, 16 Nov 2026 10:00:00 +0000</pubDate></item>
<item><title>Ohne Link</title></item></channel></rss>"""


@pytest.fixture
def cfg():
    c = load_config(ROOT / "config.yaml")
    c.site_url = "https://news.example"
    c.review = False  # diese Tests prüfen den Ablauf ohne Freigabeschritt
    return c


def item(title, link, hours=1, source="Q"):
    return SourceItem(title, "Teaser", link, source, NOW - timedelta(hours=hours))


def test_parse_feed_cleans_html_and_skips_incomplete():
    items = parse_feed(RSS, "Q", now=NOW)
    assert len(items) == 1
    assert items[0].title == "Neue KI erscheint"
    assert items[0].summary == "Teaser & mehr"


def test_select_filters_seen_old_and_duplicates_and_spreads_sources():
    items = [
        item("Apple stellt neues iPhone vor", "u1", 1, "A"),
        item("Apple stellt neues iPhone vor!", "u2", 2, "B"),  # Dublette
        item("Ganz anderes Thema Grafikkarte", "u3", 3, "A"),
        item("Schon gesehen", "u4", 1, "A"),
        item("Viel zu alt", "u5", 48, "A"),
        item("Quelle B Meldung zu Robotern", "u6", 4, "B"),
    ]
    picked = select(items, {"u4"}, 24, 3, NOW)
    assert [p.link for p in picked] == ["u1", "u6", "u3"]  # reihum A, B, A


def test_slugify_umlauts():
    assert slugify("Größe: Äpfel & Öl über alles") == "groesse-aepfel-oel-ueber-alles"


def test_generate_holds_risky_skips_unnewsworthy_and_marks_seen(cfg, tmp_path):
    class W:
        def write(self, items, topic=None):
            it = items[0]
            base = StubWriter().write(items, topic)
            if "riskant" in it.title:
                return base.model_copy(update={"risk": "high", "risk_reason": "Straftat"})
            if "werbung" in it.title:
                return base.model_copy(update={"newsworthy": False})
            if "kaputt" in it.title:
                return None
            return base

    store = Store(tmp_path)
    cfg.articles_per_run = 5
    items = [item("normal", "n"), item("riskant", "r"), item("werbung", "w"), item("kaputt", "k")]
    created = pipeline.generate(cfg, store, W(), items=items, now=NOW)

    by_status = {r["source"]["url"]: r["status"] for r in created}
    assert by_status == {"n": "live", "r": "held"}
    assert set(store.seen()) == {"n", "r", "w", "k"}  # nichts wird zweimal bezahlt
    assert [r["source"]["url"] for r in store.live()] == ["n"]
    assert pipeline.generate(cfg, store, W(), items=items, now=NOW) == []


def test_article_normalized_enforces_limits():
    a = StubWriter().write([item("x", "u")]).model_copy(
        update={"tiktok_caption": "a" * 400, "hashtags": ["#KI", "Tech News", "c", "d", "e", "f", "g"]})
    n = a.normalized()
    assert len(n.tiktok_caption) <= 150
    assert n.hashtags[:2] == ["KI", "TechNews"] and len(n.hashtags) == 6


def test_build_site(cfg, tmp_path):
    store = Store(tmp_path / "d")
    cfg.articles_per_run = 2
    cfg.videos_for_recent = 1
    pipeline.generate(cfg, store, StubWriter(), items=[item("Eins", "a"), item("Zwei", "b", 2)], now=NOW)
    out = pipeline.build(cfg, store, tmp_path / "public")
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Eins" in html and "Zwei" in html
    rec = store.live()[0]
    page = (out / "a" / rec["slug"] / "index.html").read_text(encoding="utf-8")
    assert "KI" in page and rec["source"]["url"] in page and "application/ld+json" in page
    assert (out / "media" / rec["id"] / "card.jpg").stat().st_size > 1000
    assert (out / "media" / rec["id"] / "video.mp4").exists()  # nur der neueste hat ein Video
    assert not (out / "media" / store.live()[1]["id"] / "video.mp4").exists()
    assert (out / "feed.xml").exists() and (out / "sitemap.xml").exists() and (out / "impressum" / "index.html").exists()


class FakePub:
    def __init__(self, name, fail=False):
        self.name, self.fail, self.enabled, self.calls = name, fail, True, []

    def post(self, kind, rec, assets):
        self.calls.append((rec["id"], kind))
        if self.fail:
            raise PublishError("boom")
        return "id123"


def test_publish_limits_retries_and_isolates_platform_errors(cfg, tmp_path):
    store = Store(tmp_path / "d")
    cfg.articles_per_run = 3
    cfg.publish_per_run = 2
    cfg.facebook, cfg.instagram, cfg.tiktok = ["link"], ["image"], ["video"]
    pipeline.generate(cfg, store, StubWriter(),
                      items=[item("A1", "a", 1), item("A2", "b", 2), item("A3", "c", 3)], now=NOW)
    fb, ig, tt = FakePub("facebook"), FakePub("instagram", fail=True), FakePub("tiktok")
    noop = lambda url: None  # Website-Wartezeit überspringen

    done = publish_pending(cfg, store, tmp_path / "public", publishers=[fb, ig, tt], wait=noop)
    assert len(fb.calls) == 2 and len(ig.calls) == 2           # Limit je Plattform
    assert len(done) == 4                                      # Facebook + TikTok gingen durch
    published = [r for r in store.all() if r["published"]]
    assert len(published) == 2
    assert all("instagram:image" not in r["published"] for r in store.all())  # Fehler blockiert andere nicht
    assert sum(r.get("attempts", {}).get("instagram:image", 0) for r in store.all()) == 2

    for _ in range(4):  # Instagram-Fehler werden max. 3-mal je Format versucht
        publish_pending(cfg, store, tmp_path / "public", publishers=[fb, ig, tt], wait=noop)
    assert max(r.get("attempts", {}).get("instagram:image", 0) for r in store.all()) == 3
    assert len(store.live()) == 3 and all("facebook:link" in r["published"] for r in store.all())
