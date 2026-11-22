import json
from pathlib import Path

import pytest
import requests

from newsbot import notify, pipeline
from newsbot.config import load_config
from newsbot.guides import StubGuideWriter
from newsbot.ingest import SourceItem
from newsbot.store import Store
from newsbot.writer import StubWriter
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg():
    c = load_config(ROOT / "config.yaml")
    c.site_url = "https://news.example"
    c.review = True
    return c


@pytest.fixture
def store(cfg, tmp_path):
    s = Store(tmp_path / "data")
    titles = ["Apple stellt neues iPhone vor", "Grafikkarten werden endlich günstiger"]
    items = [SourceItem(t, "Teaser", f"https://x.example/{n}", "Q", NOW) for n, t in enumerate(titles, 1)]
    pipeline.generate(cfg, s, StubWriter(), items=items, now=NOW)
    return s


class FakeHttp:
    def __init__(self, status=200):
        self.status, self.calls = status, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers))
        return type("R", (), {"status_code": self.status, "text": "x"})()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("WHATSAPP_TOKEN", "tok")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
    monkeypatch.setenv("WHATSAPP_TO", "+49 151 123456")


def test_without_credentials_nothing_is_sent(cfg, store, monkeypatch):
    for k in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_TO"):
        monkeypatch.delenv(k, raising=False)
    http = FakeHttp()
    assert notify.notify(cfg, store, http) == 0
    assert http.calls == []


def test_sends_one_message_per_draft_with_buttons_and_marks_notified(cfg, store, env):
    http = FakeHttp()
    drafts = [r for r in store.all() if r["status"] == "draft"]
    assert len(drafts) == 2
    assert notify.notify(cfg, store, http) == 2
    url, body, headers = http.calls[0]
    assert url == "https://graph.facebook.com/v23.0/123/messages"
    assert headers["Authorization"] == "Bearer tok"
    assert body["to"] == "49151123456"  # nur Ziffern
    comps = body["template"]["components"]
    buttons = [c for c in comps if c["type"] == "button"]
    ids = {d["id"] for d in drafts}
    assert {b["parameters"][0]["payload"] for b in buttons} <= {f"{a}:{i}" for a in ("approve", "reject") for i in ids}
    assert [b["index"] for b in buttons] == ["0", "1"]
    assert all(r.get("notified") for r in store.all())
    # zweiter Lauf: nichts mehr zu melden
    assert notify.notify(cfg, store, http) == 0


def test_failed_send_is_retried_next_time(cfg, store, env):
    assert notify.notify(cfg, store, FakeHttp(status=400)) == 0
    assert not any(r.get("notified") for r in store.all())
    assert notify.notify(cfg, store, FakeHttp()) == 2


def test_network_error_does_not_crash(cfg, store, env):
    class Boom:
        def post(self, *a, **k):
            raise requests.ConnectionError("weg")

    assert notify.notify(cfg, store, Boom()) == 0


def test_template_parameters_are_clean_and_short():
    msg = notify.message_for("49151", "abc123", "Deal-Check, Risiko low", "Titel\nmit\tUmbruch " + "x" * 300,
                             "Teaser", "Einordnung    mit    Leerraum", "Quelle")
    params = msg["template"]["components"][0]["parameters"]
    for p in params:
        assert "\n" not in p["text"] and "\t" not in p["text"] and "    " not in p["text"]
        assert 0 < len(p["text"]) <= 300
    assert len(params[1]["text"]) <= 110


def test_held_draft_is_marked_as_high_risk(cfg, tmp_path):
    s = Store(tmp_path / "d")

    class Risky(StubWriter):
        def write(self, items, topic=None):
            return super().write(items, topic).model_copy(update={"risk": "high"})

    pipeline.generate(cfg, s, Risky(), items=[SourceItem("Risikothema", "T", "https://x.example/9", "Q", NOW)], now=NOW)
    rec = s.all()[0]
    assert rec["status"] == "held"
    _, body, _ = notify.pending_messages(s, "49151")[0]
    assert "HOHES RISIKO" in body["template"]["components"][0]["parameters"][0]["text"]


def test_guide_draft_is_notified_once_per_version(cfg, tmp_path, env):
    cfg.guides_enabled = True
    s = Store(tmp_path / "d")
    pipeline.generate_guides(cfg, s, StubGuideWriter())
    http = FakeHttp()
    n = notify.notify(cfg, s, http)
    assert n >= 1 and notify.notify(cfg, s, http) == 0
    assert http.calls[0][1]["template"]["components"][1]["parameters"][0]["payload"].startswith("approve:kb-")


def test_decisions_approve_and_reject_are_applied_and_files_removed(cfg, store):
    a, b = [r["id"] for r in store.all()]
    folder = store.dir / "decisions"
    folder.mkdir()
    (folder / f"approve-{a}.txt").write_text("x")
    (folder / f"reject-{b}.txt").write_text("x")
    (folder / "unfug.txt").write_text("x")
    res = notify.apply_decisions(cfg, store, pipeline.approve)
    assert res == {"approved": [a], "rejected": [b]}
    status = {r["id"]: r["status"] for r in store.all()}
    assert status == {a: "live", b: "rejected"}
    assert not list(folder.glob("*.txt"))
    # Abgelehnte tauchen nicht mehr als Entwurf auf und lassen sich nicht mit "alle" freigeben
    assert b not in pipeline.drafts_markdown(store, cfg)
    pipeline.approve(cfg, store, "alle")
    assert {r["id"]: r["status"] for r in store.all()}[b] == "rejected"


def test_conflicting_decisions_reject_wins(cfg, store):
    a = store.all()[0]["id"]
    folder = store.dir / "decisions"
    folder.mkdir()
    (folder / f"approve-{a}.txt").write_text("x")
    (folder / f"reject-{a}.txt").write_text("x")
    notify.apply_decisions(cfg, store, pipeline.approve)
    assert {r["id"]: r["status"] for r in store.all()}[a] == "rejected"


def test_decisions_without_folder_is_a_noop(cfg, store):
    assert notify.apply_decisions(cfg, store, pipeline.approve) == {"approved": [], "rejected": []}


def test_held_can_be_approved_by_explicit_id_via_decision(cfg, tmp_path):
    s = Store(tmp_path / "d")

    class Risky(StubWriter):
        def write(self, items, topic=None):
            return super().write(items, topic).model_copy(update={"risk": "high"})

    pipeline.generate(cfg, s, Risky(), items=[SourceItem("Risikothema", "T", "https://x.example/9", "Q", NOW)], now=NOW)
    rid = s.all()[0]["id"]
    (s.dir / "decisions").mkdir()
    (s.dir / "decisions" / f"approve-{rid}.txt").write_text("x")
    notify.apply_decisions(cfg, s, pipeline.approve)
    assert s.all()[0]["status"] == "live"
