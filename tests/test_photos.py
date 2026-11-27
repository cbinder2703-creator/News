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


def commons_result(rid, w=3000, h=2000, lic="cc0", host="upload.wikimedia.org"):
    return {"id": rid, "width": w, "height": h, "creator": f"Autor {rid}", "creator_url": "", "license": lic,
            "url": f"https://{host}/wikipedia/commons/{rid}.jpg", "thumbnail": f"https://api.openverse.org/v1/images/{rid}/thumb/",
            "foreign_landing_url": f"https://commons.wikimedia.org/wiki/File:{rid}.jpg"}


class FakeHttp:
    def __init__(self, results, status=200, img_status=200, commons=(), pixabay=()):
        self.results, self.status, self.img_status, self.commons, self.calls = results, status, img_status, list(commons), []
        self.pixabay = list(pixabay)

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        self.calls.append((url, params, headers))
        if url == photos.PIXABAY_URL:
            return type("R", (), {"status_code": 200, "json": lambda s: {"hits": self.pixabay}})()
        if "api.pexels.com" in url:
            return type("R", (), {"status_code": self.status, "json": lambda s: {"photos": self.results}})()
        if url.startswith("https://api.openverse.org/v1/images/?") or url == "https://api.openverse.org/v1/images/":
            return type("R", (), {"status_code": 200, "json": lambda s: {"results": self.commons}})()
        return type("R", (), {"status_code": self.img_status, "content": jpeg()})()


class FakeClient:
    """Statt Claude: wählt immer Bild `choice` und merkt sich, wie viele Bilder es gesehen hat."""

    def __init__(self, choice=1):
        self.choice, self.seen = choice, 0
        self.messages = self

    def parse(self, model, max_tokens, output_format, messages):
        self.seen = sum(1 for b in messages[0]["content"] if b["type"] == "image")
        return type("R", (), {"stop_reason": "end_turn", "parsed_output": photos.Pick(choice=self.choice, reason="passt")})()


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


def test_usable_skips_small_portrait_and_used_photos():
    cands = photos.pexels_candidates("q", "KEY", FakeHttp([pexels_photo(1, 800, 600), pexels_photo(2, 1500, 3000), pexels_photo(3)]))
    assert [c["id"] for c in cands if photos.usable(c, set())] == ["pexels:3"]
    assert [c for c in cands if photos.usable(c, {"pexels:3"})] == []


def rec_for(query="balcony solar panels", product="Balkonkraftwerk 800 Watt"):
    return {"id": "abc", "article": {"headline": "Balkonkraftwerk günstig", "image_query": query,
                                     "shopping": [{"query": product}] if product else []}}


def test_find_photo_without_ai_uses_pexels_and_returns_credit(tmp_path):
    http = FakeHttp([pexels_photo(7)], commons=[commons_result("c1")])
    out = tmp_path / "p" / "x.jpg"
    meta = photos.find_photo(rec_for(), out, set(), "KEY", http=http)
    assert meta == {"id": "pexels:7", "query": "balcony solar panels", "photographer": "Foto Graf 7",
                    "photographer_url": "https://www.pexels.com/@g7", "page_url": "https://www.pexels.com/photo/7/",
                    "source": "Pexels", "license": "Pexels-Lizenz"}
    assert Image.open(out).size == (1200, 630)
    url, params, headers = http.calls[0]
    assert headers["Authorization"] == "KEY" and params["query"] == "balcony solar panels"
    assert not any("openverse" in c[0] for c in http.calls)  # freie Bilder nur mit KI-Prüfung


def test_ai_picks_among_pexels_and_free_commons_images(tmp_path):
    http = FakeHttp([pexels_photo(1)], commons=[commons_result("c1"), commons_result("c2", lic="by")])
    client = FakeClient(choice=2)
    meta = photos.find_photo(rec_for(), tmp_path / "x.jpg", set(), "KEY", client, "claude-sonnet-5-5", http)
    assert client.seen == 2  # CC-BY-Bild wurde gar nicht erst angeboten
    assert meta["id"] == "commons:c1" and meta["license"] == "CC0" and meta["source"] == "Wikimedia Commons"
    search = next(c for c in http.calls if c[0] == photos.OPENVERSE_URL)
    assert search[1]["license"] == "cc0,pdm" and search[1]["source"] == "wikimedia" and search[1]["q"] == "Balkonkraftwerk 800 Watt"


def test_ai_can_reject_all_images(tmp_path):
    out = tmp_path / "x.jpg"
    assert photos.find_photo(rec_for(), out, set(), "KEY", FakeClient(choice=0), "m", FakeHttp([pexels_photo(1)])) is None
    assert not out.exists()


def test_find_photo_fails_softly(tmp_path):
    out = tmp_path / "x.jpg"
    assert photos.find_photo(rec_for(), out, set(), "", http=FakeHttp([pexels_photo(1)])) is None  # kein Schlüssel, keine KI
    assert photos.find_photo(rec_for(), out, set(), "KEY", http=FakeHttp([pexels_photo(1)], status=429)) is None
    assert photos.find_photo(rec_for(), out, set(), "KEY", http=FakeHttp([])) is None
    assert photos.find_photo(rec_for(), out, set(), "KEY", http=FakeHttp([pexels_photo(1)], img_status=500)) is None
    assert not out.exists()

    class Boom:
        def get(self, *a, **k):
            raise requests.ConnectionError("weg")

    assert photos.find_photo(rec_for(), out, set(), "KEY", http=Boom()) is None


def test_foreign_image_hosts_are_never_downloaded(tmp_path):
    http = FakeHttp([pexels_photo(1, host="evil.example")], commons=[commons_result("c9", host="evil.example")])
    assert photos.find_photo(rec_for(), tmp_path / "x.jpg", set(), "KEY", FakeClient(), "m", http) is None
    assert [c for c in http.calls if "evil.example" in c[0]] == []


def test_backfill_gives_each_article_its_own_photo(store):
    http = FakeHttp([pexels_photo(i) for i in range(1, 6)])
    assert photos.backfill(store, "KEY", http=http) == 2
    ids = [r["photo"]["id"] for r in store.all()]
    assert len(set(ids)) == 2  # nie dasselbe Foto zweimal
    assert all(store.photo_path(r["id"]).exists() for r in store.all())
    assert photos.backfill(store, "KEY", http=http) == 0  # nichts mehr zu tun


def test_backfill_without_keys_does_nothing(store, monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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

    photos.backfill(store, "KEY", http=FakeHttp([pexels_photo(i) for i in range(1, 6)]))
    out = pipeline.build(cfg, store, tmp_path / "yes")
    page = next((out / "a").glob("*/index.html")).read_text(encoding="utf-8")
    assert ".jpg\" srcset=" in page and "-640.jpg 640w" in page and "Foto Graf" in page and "auf <a href=\"https://www.pexels.com/photo/" in page
    assert 'rel="noopener nofollow"' in page and "thumb hero" not in page
    rec = store.all()[0]
    assert (out / "media" / rec["id"] / f"{rec['slug']}.jpg").exists()  # sprechender Dateiname
    assert (out / "media" / rec["id"] / f"{rec['slug']}-1x1.jpg").exists() and (out / "media" / rec["id"] / f"{rec['slug']}-4x3.jpg").exists()
    home = (out / "index.html").read_text(encoding="utf-8")
    assert home.count(".jpg\" srcset=") == 2 and home.count("-640.jpg 640w") == 2  # beide Karten mit Foto, kleine Variante fürs Handy


def test_icons_are_picked_by_ai_choice_then_keywords():
    assert icons.pick_icon("irgendwas", "solar") == "solar"  # Wahl der KI gilt
    assert icons.pick_icon("Balkonkraftwerk 200 Euro bei Amazon") == "solar"
    assert icons.pick_icon("WLAN-Router Sicherheitslücke") == "router"
    assert icons.pick_icon("Ganz anderes Thema") == "tag"
    assert icons.pick_icon("x", "gibt-es-nicht") == "tag"
    assert set(icons.ICON_QUERIES) == set(icons.ICONS)
    html = str(icons.thumb("Powerbank", "Zubehör"))
    assert 'data-icon="powerbank"' in html and "<svg" in html and "--c1:" in html


def pixabay_hit(pid, w=4000, h=2600, host="cdn.pixabay.com"):
    return {"id": pid, "imageWidth": w, "imageHeight": h, "user": "Knipser", "user_id": 42,
            "pageURL": f"https://pixabay.com/photos/x-{pid}/", "webformatURL": f"https://{host}/photo/{pid}_640.jpg",
            "largeImageURL": f"https://{host}/photo/{pid}_1280.jpg"}


def test_pixabay_photo_with_credit_and_key_never_logged(tmp_path, caplog):
    http = FakeHttp([], pixabay=[pixabay_hit(5), pixabay_hit(6, 800, 600)])
    meta = photos.find_photo(rec_for(), tmp_path / "x.jpg", set(), http=http, pixabay_key="SECRET")
    assert meta["id"] == "pixabay:5" and meta["source"] == "Pixabay" and meta["photographer"] == "Knipser"
    assert meta["photographer_url"] == "https://pixabay.com/users/Knipser-42/"
    search = next(c for c in http.calls if c[0] == photos.PIXABAY_URL)
    assert search[1]["key"] == "SECRET" and search[1]["safesearch"] == "true" and search[1]["image_type"] == "photo"

    class Boom:
        def get(self, url, params=None, **k):
            raise requests.ConnectionError(f"{url}?key={(params or {}).get('key')}")

    photos.find_photo(rec_for(), tmp_path / "y.jpg", set(), http=Boom(), pixabay_key="SECRET")
    assert "SECRET" not in caplog.text


def test_ai_rejection_triggers_search_with_other_terms(tmp_path):
    class PickSecondRound(FakeClient):
        def __init__(self):
            super().__init__()
            self.rounds = 0

        def parse(self, model, max_tokens, output_format, messages):
            self.rounds += 1
            self.choice = 0 if self.rounds == 1 else 1
            return super().parse(model, max_tokens, output_format, messages)

    rec = rec_for(query="car jump starter", product="")
    rec["article"]["icon"] = "powerbank"
    http = FakeHttp([], pixabay=[pixabay_hit(1), pixabay_hit(2)])
    client = PickSecondRound()
    meta = photos.find_photo(rec, tmp_path / "x.jpg", set(), client=client, model="m", http=http, pixabay_key="K")
    queries = [c[1]["q"] for c in http.calls if c[0] == photos.PIXABAY_URL]
    assert queries[:2] == ["car jump starter", "jump starter"] and client.rounds == 2 and meta is not None
    assert photos.fallback_queries(rec, "car jump starter") == ["jump starter", "power bank charging"]
