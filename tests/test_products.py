from newsbot import affiliate, products
from newsbot.config import load_config
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GOLEM = """<p>Den <a href="https://www.amazon.de/Fanttik-Elektroschrauber-Akku-Schraubendreher/dp/B0F3X74WT9?tag=golem-21">
<img alt="amazon Affiliate"></a> gibt es gerade günstig.</p>
<aside><p>Garmin Fenix 8 <a href="https://www.amazon.de/dp/B0DC6ZD321">Zum Angebot</a></p></aside>
<p>Dazu passt das <a href="https://www.amazon.de/gp/product/B0BITSET01">Wera Bit Set 30-teilig</a>.</p>
<p><a href="https://example.com/dp/B0FAKEFAKE">fremd</a></p>"""


def test_extract_links_reads_asin_text_slug_and_context():
    links = products.extract_links(GOLEM)
    assert [l["asin"] for l in links] == ["B0F3X74WT9", "B0DC6ZD321", "B0BITSET01"]  # fremde Seiten ignoriert
    assert "Fanttik Elektroschrauber" in links[0]["slug"] and links[0]["text"] == "amazon Affiliate"
    assert "Garmin Fenix 8" in links[1]["context"]


def test_attach_asins_main_product_by_brand_and_others_by_words():
    art = {"shopping": [{"label": "Fanttik S2 Pro", "query": "Fanttik S2 Pro"},
                        {"label": "Garmin Fenix 7", "query": "Garmin Fenix 7"},
                        {"label": "Bit-Set", "query": "Wera Bit Set"}]}
    n = products.attach_asins(art, products.extract_links(GOLEM))
    asins = [i.get("asin") for i in art["shopping"]]
    assert n == 2 and asins == ["B0F3X74WT9", None, "B0BITSET01"]  # Fenix 7 ist nicht Fenix 8


def test_attach_asins_never_uses_unrelated_first_link():
    art = {"shopping": [{"label": "Coros Vertix 4", "query": "Coros Vertix 4"}]}
    links = [{"asin": "B0DC6ZD321", "text": "Hier geht es zur Garmin Fenix", "slug": "", "context": ""}]
    assert products.attach_asins(art, links) == 0 and "asin" not in art["shopping"][0]


def test_shop_box_links_directly_to_product_page():
    cfg = load_config(ROOT / "config.yaml")
    boxes = affiliate.build_shop_boxes(cfg, [{"label": "Fanttik S2 Pro", "query": "Fanttik S2 Pro", "asin": "B0F3X74WT9"},
                                             {"label": "Bosch IXO", "query": "Bosch IXO"}])
    assert boxes[0]["links"][0]["url"] == "https://www.amazon.de/dp/B0F3X74WT9?tag=dealpuls-21"
    assert boxes[1]["links"][0]["url"] == "https://www.amazon.de/s?k=Bosch+IXO&tag=dealpuls-21"
    bad = affiliate.build_shop_boxes(cfg, [{"label": "x", "query": "x", "asin": "<script>"}])
    assert "/s?k=x" in bad[0]["links"][0]["url"]


def test_backfill_reads_sources_once(tmp_path):
    from newsbot.store import Store

    class Http:
        calls = 0

        def get(self, url, timeout=None, headers=None):
            Http.calls += 1
            return type("R", (), {"status_code": 200, "content": GOLEM.encode(), "text": GOLEM})()

    store = Store(tmp_path / "d")
    store.save({"id": "a1", "slug": "a", "status": "live", "created_at": "2026-11-27T10:00:00+00:00",
                "sources": [{"url": "https://golem.example/x"}],
                "article": {"headline": "Fanttik", "shopping": [{"label": "Fanttik S2 Pro", "query": "Fanttik S2 Pro"}]}})
    assert products.backfill(store, Http()) == 1 and store.all()[0]["article"]["shopping"][0]["asin"] == "B0F3X74WT9"
    assert products.backfill(store, Http()) == 0 and Http.calls == 1
