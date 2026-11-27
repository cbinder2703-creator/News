from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from newsbot import pipeline
from newsbot.config import load_config
from newsbot.demo_data import fake_synth
from newsbot.editor import StubEditor, Topic, render_items, validate_topics
from newsbot.ingest import SourceItem
from newsbot.store import Store
from newsbot.writer import Article, StubWriter, user_prompt

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg():
    c = load_config(ROOT / "config.yaml")
    c.site_url = "https://news.example"
    c.videos_for_recent = 20  # die Tests prüfen auch die Videofunktion, die in der echten Konfiguration aus ist
    c.review = True  # die Tests prüfen den Freigabe-Ablauf; live läuft der Modus "auto"
    return c


def item(title, link, source="Q", hours=1):
    return SourceItem(title, f"Teaser {title}", link, source, NOW - timedelta(hours=hours))


class BundlingEditor:
    """Bündelt Meldung 1 und 2 zu einem Thema (zwei Quellen), Meldung 3 allein."""

    def plan(self, items, recent, now=None):
        return [Topic(title="Thema A", item_numbers=[1, 2], rubrik="Hype-Check", angle="Was ist dran?"),
                Topic(title="Thema B", item_numbers=[3], rubrik="Kurz erklärt")]


ITEMS = [item("A bei heise", "u1", "heise"), item("A bei Golem", "u2", "Golem", 2), item("B anderswo", "u3", "t3n", 3)]


def test_config_has_editorial_line(cfg):
    assert load_config(ROOT / "config.yaml").review is False  # Beiträge gehen automatisch online
    assert "begeisterung" in cfg.haltung.lower() and "testen nicht selbst" in cfg.haltung
    names = [r["name"] for r in cfg.rubriken]
    assert names[0] == "Deal-Check" and "Neuheiten-Check" in names and "Ratgeber" in names


def test_validate_topics_drops_bad_numbers_and_duplicates():
    topics = [Topic(title="a", item_numbers=[1, 1, 9, 0]), Topic(title="b", item_numbers=[1]),
              Topic(title="c", item_numbers=[2])]
    out = validate_topics(topics, 3, 5)
    assert [(t.title, t.item_numbers) for t in out] == [("a", [1]), ("c", [2])]
    assert len(validate_topics(topics, 3, 1)) == 1


def test_render_items_numbers_and_age():
    text = render_items(ITEMS, NOW)
    assert text.splitlines()[0].startswith("1. [heise, vor 1 h] A bei heise")
    assert "3. [t3n, vor 3 h]" in text


def test_user_prompt_lists_all_sources_and_marks_them_as_data():
    p = user_prompt(ITEMS[:2], Topic(title="Thema A", item_numbers=[1, 2], rubrik="Hype-Check", angle="Was ist dran?"))
    assert "<quelle>" in p and "[1] Quellname: heise" in p and "[2] Quellname: Golem" in p
    assert "Rubrik: Hype-Check" in p and "Blickwinkel: Was ist dran?" in p


def test_multi_source_topic_becomes_one_draft_with_all_sources(cfg, tmp_path):
    store = Store(tmp_path)
    created = pipeline.generate(cfg, store, StubWriter(), items=ITEMS, now=NOW, editor=BundlingEditor())
    assert len(created) == 2
    first = created[0]
    assert first["status"] == "draft" and first["article"]["rubrik"] == "Hype-Check"
    assert [s["name"] for s in first["sources"]] == ["heise", "Golem"]
    assert set(store.seen()) == {"u1", "u2", "u3"}
    assert store.live() == []  # Entwürfe sind nicht öffentlich


def test_approve_by_id_and_all_publishes_and_adds_voice(cfg, tmp_path):
    store = Store(tmp_path)
    a, b = pipeline.generate(cfg, store, StubWriter(), items=ITEMS, now=NOW, editor=BundlingEditor())
    done = pipeline.approve(cfg, store, a["id"], synth=fake_synth)
    assert [r["id"] for r in done] == [a["id"]]
    assert [r["id"] for r in store.live()] == [a["id"]]
    assert store.audio_path(a["id"]).exists() and not store.audio_path(b["id"]).exists()
    assert {r["id"]: r["status"] for r in store.all()}[b["id"]] == "draft"  # der andere bleibt Entwurf
    assert [r["id"] for r in pipeline.approve(cfg, store, "alle", synth=fake_synth)] == [b["id"]]


def test_held_high_risk_only_released_by_explicit_id(cfg, tmp_path):
    class Risky:
        def write(self, items, topic=None):
            return StubWriter().write(items, topic).model_copy(update={"risk": "high", "risk_reason": "Straftat"})

    store = Store(tmp_path)
    (rec,) = pipeline.generate(cfg, store, Risky(), items=ITEMS[:1], now=NOW)
    assert rec["status"] == "held"
    assert pipeline.approve(cfg, store, "alle", synth=fake_synth) == []   # "alle" fasst Hochrisiko nicht an
    assert pipeline.approve(cfg, store, "xyz", synth=fake_synth) == []    # falsche ID: nichts passiert
    assert [r["id"] for r in pipeline.approve(cfg, store, rec["id"], synth=fake_synth)] == [rec["id"]]


def test_auto_mode_publishes_directly(cfg, tmp_path):
    cfg.review = False
    store = Store(tmp_path)
    created = pipeline.generate(cfg, store, StubWriter(), items=ITEMS, now=NOW, editor=BundlingEditor())
    assert {r["status"] for r in created} == {"live"} and len(store.live()) == 2


def test_drafts_markdown_lists_ids_and_hides_nothing_risky(cfg, tmp_path):
    store = Store(tmp_path)
    (rec, _) = pipeline.generate(cfg, store, StubWriter(), items=ITEMS, now=NOW, editor=BundlingEditor())
    md = pipeline.drafts_markdown(store)
    assert rec["id"] in md and "approve" in md and "Quellen" in md and "Sprechtext" in md
    assert pipeline.drafts_markdown(Store(tmp_path / "leer")).startswith("## Keine offenen")


def test_explainer_page_renders_sections_verdict_and_all_sources(cfg, tmp_path):
    cfg.review = False
    cfg.show_sources = True
    store = Store(tmp_path / "d")
    (rec, _) = pipeline.generate(cfg, store, StubWriter(), items=ITEMS, now=NOW, editor=BundlingEditor())
    out = pipeline.build(cfg, store, tmp_path / "public")
    html = (out / "a" / rec["slug"] / "index.html").read_text(encoding="utf-8")
    for needle in ("Worum geht es genau?", "Einordnung", "Gut zu wissen", "heise", "Golem", "Quellen"):
        assert needle in html


def test_stub_editor_limits_topics_to_config(cfg):
    cfg.articles_per_run = 2
    assert len(StubEditor(cfg).plan(ITEMS, [], NOW)) == 2


def test_verdict_and_sections_are_length_limited():
    art = StubWriter().write(ITEMS[:1]).model_copy(update={"verdict": "x" * 900})
    assert len(art.normalized().verdict) <= 400


def test_sources_can_be_hidden_from_the_public_page_but_stay_in_the_data(cfg, tmp_path):
    cfg.review = False
    cfg.show_sources = False
    store = Store(tmp_path / "d")
    (rec, _) = pipeline.generate(cfg, store, StubWriter(), items=ITEMS, now=NOW, editor=BundlingEditor())
    out = pipeline.build(cfg, store, tmp_path / "public")
    html = (out / "a" / rec["slug"] / "index.html").read_text(encoding="utf-8")
    assert 'class="source"' not in html and "isBasedOn" not in html
    assert "Worum geht es genau?" in html  # Inhalt bleibt
    for url in (s["url"] for s in rec["sources"]):
        assert url not in html  # keine Quell-Links im Seitencode
    assert rec["sources"] and all(s["url"] for s in rec["sources"])  # für die Admin-Seite gespeichert
    about = (out / "so-arbeiten-wir" / "index.html").read_text(encoding="utf-8")
    assert "nennt und verlinkt" not in about  # die Seite behauptet nichts, was nicht mehr stimmt


def test_footer_and_prompts_follow_show_sources(cfg):
    from newsbot import media
    from newsbot.writer import Writer

    rec = {"source": {"name": "heise"}, "sources": [{"name": "heise"}, {"name": "Golem"}]}
    assert "heise" in media.footer_line(rec, True) and "heise" not in media.footer_line(rec, False)
    assert media.footer_line(rec, False, "KI-Stimme").endswith("KI-Stimme")

    import anthropic
    anthropic_client = anthropic.Anthropic
    anthropic.Anthropic = lambda *a, **k: None  # kein Schlüssel nötig, es wird nichts gesendet
    try:
        cfg.show_sources = True
        assert 'am Ende "Quelle: ..."' in Writer(cfg).system
        cfg.show_sources = False
        prompt = Writer(cfg).system
        assert 'am Ende "Quelle: ..."' not in prompt and "ohne eigene Quellenzeile" in prompt and "<<" not in prompt
    finally:
        anthropic.Anthropic = anthropic_client


def test_source_names_are_detected_in_every_text_field():
    from newsbot.writer import source_mentions
    a = {"headline": "AirPods Pro 3 günstig", "body": ["Laut Golem.de kosten sie unter 190 Euro."],
         "faq": [{"question": "Was sagt heise?", "answer": "Nichts."}], "sections": [], "shopping": []}
    assert source_mentions(a, ["Golem.de", "heise online", "THE DECODER"]) == ["golem", "heise"]
    clean = {**a, "body": ["Die AirPods kosten unter 190 Euro."], "faq": []}
    assert source_mentions(clean, ["Golem.de", "heise online"]) == []
    # Wortgrenzen: "heiser" ist kein Treffer
    assert source_mentions({"headline": "Ich bin heiser"}, ["heise online"]) == []


def test_prompt_forbids_source_names_when_sources_are_hidden(cfg, monkeypatch):
    import sys, types
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=lambda: None))
    from newsbot.writer import Writer
    cfg.show_sources = False
    hidden = Writer(cfg).system
    assert "Nenne NIE Quellen" in hidden and "Laut heise" not in hidden and "<<" not in hidden
    cfg.show_sources = True
    shown = Writer(cfg).system
    assert "Laut heise" in shown and "Nenne NIE Quellen" not in shown


def test_rewrite_sends_live_articles_back_to_review_and_keeps_their_date(cfg, tmp_path):
    from newsbot import pipeline
    from newsbot.store import Store
    store = Store(tmp_path / "d")
    (rec,) = pipeline.generate(cfg, store, StubWriter(), items=[ITEMS[0]], now=NOW)
    pipeline.approve(cfg, store, "alle")
    get = lambda i: next(r for r in store.all() if r["id"] == i)  # noqa: E731
    live = get(rec["id"])
    done = pipeline.rewrite(cfg, store, StubWriter(), "alle")
    again = get(rec["id"])
    assert len(done) == 1 and again["status"] == "draft" and again["article"]["headline"].startswith("Neu: ")
    assert again["slug"] == live["slug"]
    pipeline.approve(cfg, store, "alle")
    back = get(rec["id"])
    assert back["status"] == "live" and back["created_at"] == live["created_at"] and "keep_date" not in back


def test_auto_mode_publishes_but_holds_high_risk_and_says_so_honestly(tmp_path):
    from newsbot import notify
    c = load_config(ROOT / "config.yaml")
    c.site_url = "https://news.example"
    store = Store(tmp_path / "d")
    (rec,) = pipeline.generate(c, store, StubWriter(), items=[ITEMS[0]], now=NOW)
    assert rec["status"] == "live"
    out = pipeline.build(c, store, tmp_path / "pub")
    page = (out / "a" / rec["slug"] / "index.html").read_text(encoding="utf-8")
    assert "automatisch veröffentlicht" in page and "vor der Veröffentlichung von uns geprüft" not in page
    # Offline nehmen über die Admin-Seite (Entscheidungsdatei)
    pipeline.write_drafts_index(store)
    assert '"id": "%s"' % rec["id"] in (store.dir / "live.json").read_text(encoding="utf-8")
    (store.dir / "decisions").mkdir(exist_ok=True)
    (store.dir / "decisions" / f"unpublish-{rec['id']}.txt").write_text("x")
    res = notify.apply_decisions(c, store, pipeline.approve)
    assert res["unpublished"] == [rec["id"]] and store.live() == []
