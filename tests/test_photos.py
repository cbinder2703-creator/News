import io
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from PIL import Image

from newsbot import icons, photos, pipeline
from newsbot.config import load_config
from newsbot.ingest import SourceItem
from newsbot.store import Store
from newsbot.writer import StubWriter

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def jpeg(w=2400, h=1800, color=(200, 80, 60)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), color).save(out, "JPEG")
    return out.getvalue()


def pexels_photo(pid, w=3000, h=2000, host="images.pexels.com"):
    return {"id": pid, "width": w, "height": h, "photographer": f"Foto Graf {pid}", "photographer_url": f"https://www.pexels.com/@g{pid}",
            "url": f"https://www.pexels.com/photo/{pid}/", "src": {"large2x": f"https://{host}/photos/{pid}/x.jpeg"}}


class FakeHttp:
    def __init__(self, results, status=200, img_status=200):
        self.results, self.status, self.img_status, self.calls = results, status, img_status, []

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        self.calls.append((url, params, headers))
        if "api.pexels.com" in url:
            return type("R", (), {"status_code": self.status, "json": lambda s: {"photos": self.results}})()
        return type("R", (), {"status_code": self.img_status, "content": jpeg()})()


@pytest.fixture
def cfg():
    c = load_config(ROOT / "config.yaml")
    c.site_url = "https://news.example"
    c.review = False
    return c


@pytest.fixture
def store(cfg, tmp_path):
    s = Store(tmp_path / "d")
    items = [SourceItem("Balkonkraftwerk 200 Euro bei Amazon", "Teaser", "https://x.example/1", "Q", NOW),
             SourceItem("Neue Powerbank im Angebot", "Teaser", "https://x.example/2", "Q", NOW)]
    pipeline.generate(cfg, s, StubWriter(), items=items, now=NOW)
    return s


def test_crop_gives_exact_size_for_wide_and_tall_images():
    for w, h in ((3000, 1000), (1000, 3000), (1200, 630)):
        img = Image.open(io.BytesIO(photos.crop_to_size(jpeg(w, h))))
        assert img.size == (1200, 630) and img.format == "JPEG"


def test_choose_skips_small_portrait_and_used_photos():
    results = [pexels_photo(1, 800, 600), pexels_photo(2, 1500, 3000), pexels_photo(3), pexels_photo(4), pexels_photo(5)]
    assert photos.choose(results, "a", set())["id"] in (3, 4, 5)
    assert photos.choose(results, "a", {3, 4}) ["id"] == 5
    assert photos.choose(results, "a", {3, 4, 5}) is None
    assert photos.choose([], "a", set()) is None


def test_find_photo_saves_a_cropped_file_and_returns_credit(tmp_path):
    http = FakeHttp([pexels_photo(7)])
    out = tmp_path / "p" / "x.jpg"
    meta = photos.find_photo("balcony solar panels", "seed", "KEY", out, set(), http)
    assert meta == {"id": 7, "query": "balcony solar panels", "photographer": "Foto Graf 7",
                    "photographer_url": "https://www.pexels.com/@g7", "page_url": "https://www.pexels.com/photo/7/"}
    assert Image.open(out).size == (1200, 630)
    url, params, headers = http.calls[0]
    assert headers["Authorization"] == "KEY" and params["query"] == "balcony solar panels"


def test_find_photo_fails_softly(tmp_path):
    out = tmp_path / "x.jpg"
    assert photos.find_photo("", "s", "KEY", out, set(), FakeHttp([pexels_photo(1)])) is None  # keine Suchanfrage
    assert photos.find_photo("q", "s", "", out, set(), FakeHttp([pexels_photo(1)])) is None  # kein Schlüssel
    assert photos.find_photo("q", "s", "KEY", out, set(), FakeHttp([pexels_photo(1)], status=429)) is None
    assert photos.find_photo("q", "s", "KEY", out, set(), FakeHttp([])) is None
    assert photos.find_photo("q", "s", "KEY", out, set(), FakeHttp([pexels_photo(1)], img_status=500)) is None
    assert not out.exists()

    class Boom:
        def get(self, *a, **k):
            raise requests.ConnectionError("weg")

    assert photos.find_photo("q", "s", "KEY", out, set(), Boom()) is None


def test_foreign_image_hosts_are_never_downloaded(tmp_path):
    http = FakeHttp([pexels_photo(1, host="evil.example")])
    assert photos.find_photo("q", "s", "KEY", tmp_path / "x.jpg", set(), http) is None
    assert [c for c in http.calls if "evil.example" in c[0]] == []


def test_backfill_gives_each_article_its_own_photo(store):
    http = FakeHttp([pexels_photo(i) for i in range(1, 6)])
    assert photos.backfill(store, "KEY", http) == 2
    ids = [r["photo"]["id"] for r in store.all()]
    assert len(set(ids)) == 2  # nie dasselbe Foto zweimal
    assert all(store.photo_path(r["id"]).exists() for r in store.all())
    assert photos.backfill(store, "KEY", http) == 0  # nichts mehr zu tun


def test_backfill_without_key_does_nothing(store, monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert photos.backfill(store) == 0 and not store.photo_path(store.all()[0]["id"]).exists()


def test_query_prefers_the_ai_query_else_uses_the_icon_default(store):
    rec = store.all()[0]
    rec["article"]["image_query"] = "balcony solar panels"
    assert photos.query_for(rec) == "balcony solar panels"
    rec["article"]["image_query"] = ""
    rec["article"]["headline"] = "Balkonkraftwerk 200 Euro"
    assert photos.query_for(rec) == icons.ICON_QUERIES["solar"]


def test_site_shows_photo_with_credit_or_falls_back_to_icon(cfg, store, tmp_path):
    pipeline.build(cfg, store, tmp_path / "no")
    page = next((tmp_path / "no" / "a").glob("*/index.html")).read_text(encoding="utf-8")
    assert 'class="thumb hero"' in page and "photo.jpg" not in page and "Pexels" not in page

    photos.backfill(store, "KEY", FakeHttp([pexels_photo(i) for i in range(1, 6)]))
    out = pipeline.build(cfg, store, tmp_path / "yes")
    page = next((out / "a").glob("*/index.html")).read_text(encoding="utf-8")
    assert "photo.jpg" in page and "Foto Graf" in page and "auf <a href=\"https://www.pexels.com/photo/" in page
    assert 'rel="noopener nofollow"' in page and "thumb hero" not in page
    assert any((out / "media").glob("*/photo.jpg"))
    home = (out / "index.html").read_text(encoding="utf-8")
    assert home.count("photo.jpg") == 2  # beide Karten mit Foto


def test_icons_are_picked_by_ai_choice_then_keywords():
    assert icons.pick_icon("irgendwas", "solar") == "solar"  # Wahl der KI gilt
    assert icons.pick_icon("Balkonkraftwerk 200 Euro bei Amazon") == "solar"
    assert icons.pick_icon("WLAN-Router Sicherheitslücke") == "router"
    assert icons.pick_icon("Ganz anderes Thema") == "tag"
    assert icons.pick_icon("x", "gibt-es-nicht") == "tag"
    assert set(icons.ICON_QUERIES) == set(icons.ICONS)
    html = str(icons.thumb("Powerbank", "Zubehör"))
    assert 'data-icon="powerbank"' in html and "<svg" in html and "--c1:" in html
