"""Ablauf: generate (Quellen -> Beiträge) -> build (Website) -> publish (Social)."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from .config import RISK_ORDER, Config
from .ingest import SourceItem, fetch, select
from .site import build_site
from .social import publish_pending
from . import voice as voice_mod
from .store import Store, now_iso, slugify

log = logging.getLogger("newsbot.pipeline")


def article_id(link: str) -> str:
    return hashlib.sha1(link.encode()).hexdigest()[:10]


def add_voice(cfg: Config, store: Store, rec: dict, synth=None) -> bool:
    """Erzeugt die Sprachaufnahme einmal pro Beitrag. Ein Fehler stoppt den Beitrag nicht (dann stummes Video)."""
    synth = synth or voice_mod.synthesize
    text = rec["article"].get("narration", "").strip()
    if not (cfg.voice_enabled and text):
        return False
    try:
        audio = synth(text, cfg.voice_id, cfg.voice_model)
    except Exception as exc:
        log.warning("Sprachaufnahme für %s fehlgeschlagen: %s", rec["id"], exc)
        return False
    store.audio_dir.mkdir(parents=True, exist_ok=True)
    store.audio_path(rec["id"]).write_bytes(audio)
    return True


def generate(cfg: Config, store: Store, writer, items: list[SourceItem] | None = None,
             now: datetime | None = None, synth=None) -> list[dict]:
    """Holt neue Meldungen, lässt die KI Beiträge schreiben und speichert sie.

    Status: "live" (wird veröffentlicht), "held" (Risiko zu hoch, bleibt unveröffentlicht),
    übersprungene Meldungen (nicht nachrichtenwürdig / KI-Fehler) werden nur als gesehen markiert.
    """
    now = now or datetime.now(timezone.utc)
    if items is None:
        items = fetch(cfg.sources)
    seen = store.seen()
    # Doppelt so viele Kandidaten wie gewünscht, weil manche aussortiert werden.
    candidates = select(items, set(seen), cfg.max_age_hours, cfg.articles_per_run * 2, now)

    created: list[dict] = []
    for item in candidates:
        if len(created) >= cfg.articles_per_run:
            break
        art = writer.write(item)
        store.mark_seen([item.link])  # auch Fehlschläge: keine doppelten Kosten
        if art is None or not art.newsworthy or not art.body:
            log.info("Übersprungen: %s (%s)", item.title, getattr(art, "skip_reason", "KI-Fehler"))
            continue
        status = "live" if RISK_ORDER[art.risk] <= RISK_ORDER[cfg.max_auto_risk] else "held"
        rec = {
            "id": article_id(item.link),
            "slug": f"{slugify(art.headline)}-{article_id(item.link)[:6]}",
            "created_at": now_iso(),
            "status": status,
            "source": {"name": item.source, "url": item.link, "title": item.title,
                       "published": item.published.isoformat(timespec="seconds")},
            "article": art.model_dump(),
            "published": {},
        }
        store.save(rec)
        created.append(rec)
        if status == "live" and (synth or voice_mod.available()):
            add_voice(cfg, store, rec, synth)  # nur für Beiträge, die wirklich erscheinen
        log.info("[%s] %s (Risiko: %s%s)", status, art.headline, art.risk,
                 f", {art.risk_reason}" if art.risk_reason else "")
    store.prune_audio([r["id"] for r in store.live()[: cfg.videos_for_recent]])
    return created


def build(cfg: Config, store: Store, out: str | Path = "public") -> Path:
    records = store.live()
    build_site(cfg, records, Path(out), audio_dir=store.audio_dir)
    log.info("Website mit %d Beiträgen nach %s gebaut", len(records), out)
    return Path(out)


def publish(cfg: Config, store: Store, public_root: str | Path = "public") -> list[str]:
    return publish_pending(cfg, store, Path(public_root))
