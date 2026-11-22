import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from newsbot import pipeline, voice
from newsbot.config import load_config
from newsbot.demo_data import fake_synth
from newsbot.ingest import SourceItem
from newsbot.media import audio_duration, caption_durations, split_captions
from newsbot.store import Store
from newsbot.writer import StubWriter

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
TEXT = ("Ein neues Sprachmodell schlägt die Konkurrenz in mehreren Tests. "
        "Entwickler sprechen von einem Sprung bei der Genauigkeit, Details nennen sie nicht. Quelle: THE DECODER.")


@pytest.fixture
def cfg():
    c = load_config(ROOT / "config.yaml")
    c.site_url = "https://news.example"
    c.review = False
    c.videos_for_recent = 20  # Videos sind in config.yaml abgeschaltet, hier werden sie ja getestet
    return c


def one_item():
    return [SourceItem("Neues Sprachmodell", "Teaser", "https://x.example/1", "THE DECODER", NOW)]


def test_split_captions_short_and_complete():
    chunks = split_captions(TEXT)
    assert all(len(c) <= 40 for c in chunks)
    assert " ".join(chunks) == TEXT  # nichts geht verloren


def test_caption_durations_add_up_to_audio_length():
    chunks = split_captions(TEXT)
    durs = caption_durations(chunks, 12.0)
    assert abs(sum(durs) - 12.0) < 0.01 and min(durs) > 0.3


def test_synthesize_calls_elevenlabs(monkeypatch):
    seen = {}

    class R:
        ok, status_code, content, text = True, 200, b"MP3DATA", ""

    def fake_post(url, **kw):
        seen.update(url=url, **kw)
        return R()

    monkeypatch.setattr(voice.requests, "post", fake_post)
    assert voice.synthesize("Hallo", "VOICE1", "model-x", api_key="k") == b"MP3DATA"
    assert seen["url"].endswith("/text-to-speech/VOICE1")
    assert seen["headers"]["xi-api-key"] == "k" and seen["json"] == {"text": "Hallo", "model_id": "model-x"}
    with pytest.raises(voice.VoiceError):
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        voice.synthesize("Hallo", "V", "m")


def test_voice_error_does_not_block_article(cfg, tmp_path):
    def broken(*a):
        raise voice.VoiceError("kaputt")

    store = Store(tmp_path)
    created = pipeline.generate(cfg, store, StubWriter(), items=one_item(), now=NOW, synth=broken)
    assert len(created) == 1 and not store.audio_path(created[0]["id"]).exists()


def test_narrated_video_has_audio_and_matches_length(cfg, tmp_path):
    store = Store(tmp_path / "d")
    created = pipeline.generate(cfg, store, StubWriter(), items=one_item(), now=NOW, synth=fake_synth)
    rid = created[0]["id"]
    assert store.audio_path(rid).stat().st_size > 100
    out = pipeline.build(cfg, store, tmp_path / "public")
    video = out / "media" / rid / "video.mp4"
    assert video.exists()
    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True).stdout
    assert "video,1080,1920" in streams and "audio" in streams
    # Videolänge = Sprechdauer + Abbinder (ca. 1,8 s)
    speech = audio_duration(store.audio_path(rid))
    total = audio_duration(video)
    assert speech and total and speech + 1.0 < total < speech + 3.0


def test_old_audio_is_pruned(cfg, tmp_path):
    store = Store(tmp_path)
    store.audio_dir.mkdir(parents=True)
    (store.audio_dir / "old.mp3").write_bytes(b"x")
    cfg.videos_for_recent = 5
    pipeline.generate(cfg, store, StubWriter(), items=one_item(), now=NOW, synth=fake_synth)
    assert not (store.audio_dir / "old.mp3").exists()
