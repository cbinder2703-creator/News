import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from newsbot import cli, notify, pipeline
from newsbot.config import load_config
from newsbot.guides import StubGuideWriter
from newsbot.ingest import SourceItem
from newsbot.store import Store
from newsbot.writer import StubWriter

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg():
    c = load_config(ROOT / "config.yaml")
    c.site_url = "https://news.example"
    c.review = True
    c.guides_enabled = True
    return c


@pytest.fixture
def store(cfg, tmp_path):
    s = Store(tmp_path / "data")
    items = [SourceItem("Apple stellt neues iPhone vor", "Teaser", "https://x.example/1", "Q", NOW)]
    pipeline.generate(cfg, s, StubWriter(), items=items, now=NOW)
    pipeline.generate_guides(cfg, s, StubGuideWriter())
    return s


def test_drafts_index_contains_news_and_guides_in_a_uniform_shape(store):
    items = pipeline.drafts_index(store)
    kinds = sorted(i["kind"] for i in items)
    assert kinds == ["guide", "news"]
    for i in items:
        for key in ("id", "status", "rubrik", "risk", "headline", "teaser", "body", "sections", "verdict", "sources"):
            assert key in i
    news = next(i for i in items if i["kind"] == "news")
    assert news["sources"][0]["url"] == "https://x.example/1"
    guide = next(i for i in items if i["kind"] == "guide")
    assert guide["id"].startswith("kb-") and guide["sections"]


def test_drafts_index_drops_decided_items(cfg, store):
    news_id = next(i["id"] for i in pipeline.drafts_index(store) if i["kind"] == "news")
    pipeline.approve(cfg, store, news_id)
    assert all(i["id"] != news_id for i in pipeline.drafts_index(store))
    guide_id = next(i["id"] for i in pipeline.drafts_index(store))
    notify.reject(store, [guide_id])
    assert pipeline.drafts_index(store) == []


def test_write_drafts_index_creates_json(store):
    path = pipeline.write_drafts_index(store)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["drafts"]) == 2 and data["updated_at"]


def test_cli_writes_index_after_approve(tmp_path, monkeypatch):
    data = tmp_path / "d"
    monkeypatch.chdir(ROOT)
    assert cli.main(["approve", "alle", "--data", str(data)]) == 0
    assert (data / "drafts.json").exists()


def test_admin_page_only_built_when_api_url_is_set(cfg, store, tmp_path):
    cfg.admin_api_url = ""
    pipeline.build(cfg, store, tmp_path / "off")
    assert not (tmp_path / "off" / "admin").exists()

    cfg.admin_api_url = "https://dealpuls-admin.example.workers.dev"
    pipeline.approve(cfg, store, "alle")
    out = pipeline.build(cfg, store, tmp_path / "on")
    page = (out / "admin" / "index.html").read_text(encoding="utf-8")
    assert 'name="robots" content="noindex' in page
    assert "connect-src https://dealpuls-admin.example.workers.dev" in page
    assert "script-src 'self'" in page and "unsafe-inline" not in page.split("script-src")[1].split(";")[0]
    assert (out / "static" / "admin.js").exists()
    # nicht verlinkt und nicht in der Sitemap
    assert "/admin" not in (out / "sitemap.xml").read_text(encoding="utf-8")
    assert "/admin" not in (out / "index.html").read_text(encoding="utf-8")


def test_admin_js_never_uses_html_injection():
    js = (ROOT / "newsbot" / "static" / "admin.js").read_text(encoding="utf-8")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert bad not in js, bad
