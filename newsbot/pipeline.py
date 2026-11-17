"""Ablauf: generate (Themen -> Entwürfe) -> approve (Freigabe) -> build (Website) -> publish (Social)."""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from . import voice as voice_mod
from .config import RISK_ORDER, Config
from .affiliate import build_shop_boxes
from .editor import Topic
from .ingest import SourceItem, fetch, select
from .site import build_site
from .social import publish_pending
from .store import Store, now_iso, slugify

log = logging.getLogger("newsbot.pipeline")
POOL_SIZE = 40  # so viele frische Meldungen sieht die Chefredaktion pro Lauf


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


def _voice_wanted(synth) -> bool:
    return bool(synth or voice_mod.available())


def generate(cfg: Config, store: Store, writer, items: list[SourceItem] | None = None,
             now: datetime | None = None, synth=None, editor=None) -> list[dict]:
    """Holt frische Meldungen, lässt die Chefredaktion Themen bündeln und den Autor Beiträge schreiben.

    Status: "draft" (wartet auf deine Freigabe, Standard), "live" (mode: auto), "held" (Risiko zu hoch,
    nur per ausdrücklicher Freigabe). Nicht nachrichtenwürdige Themen oder KI-Fehler werden nur als gesehen markiert.
    """
    now = now or datetime.now(timezone.utc)
    if items is None:
        items = fetch(cfg.sources)
    seen = set(store.seen())

    if editor is not None:
        pool = select(items, seen, cfg.max_age_hours, POOL_SIZE, now, dedupe=False)
        recent = [r["article"]["headline"] for r in store.all()[:15]]
        topics = editor.plan(pool, recent, now)
    else:  # ohne Chefredaktion: jede Meldung ein eigenes Thema (Tests, einfacher Betrieb)
        pool = select(items, seen, cfg.max_age_hours, cfg.articles_per_run * 2, now)
        topics = [Topic(title=i.title, item_numbers=[n]) for n, i in enumerate(pool, 1)]

    created: list[dict] = []
    for topic in topics:
        if len(created) >= cfg.articles_per_run:
            break
        topic_items = [pool[n - 1] for n in topic.item_numbers]
        primary = topic_items[0]
        art = writer.write(topic_items, topic)
        store.mark_seen([i.link for i in topic_items])  # auch Fehlschläge: keine doppelten Kosten
        if art is None or not art.newsworthy or not art.body:
            log.info("Übersprungen: %s (%s)", topic.title, getattr(art, "skip_reason", "KI-Fehler"))
            continue
        if not art.rubrik:
            art = art.model_copy(update={"rubrik": topic.rubrik})
        if RISK_ORDER[art.risk] > RISK_ORDER[cfg.max_auto_risk]:
            status = "held"
        else:
            status = "draft" if cfg.review else "live"
        sources = [{"name": i.source, "url": i.link, "title": i.title,
                    "published": i.published.isoformat(timespec="seconds")} for i in topic_items]
        rec = {
            "id": article_id(primary.link),
            "slug": f"{slugify(art.headline)}-{article_id(primary.link)[:6]}",
            "created_at": now_iso(),
            "status": status,
            "source": sources[0],
            "sources": sources,
            "topic": {"title": topic.title, "angle": topic.angle},
            "article": art.model_dump(),
            "published": {},
        }
        store.save(rec)
        created.append(rec)
        if status == "live" and _voice_wanted(synth):
            add_voice(cfg, store, rec, synth)
        log.info("[%s] %s | %s (Risiko: %s%s)", status, art.rubrik or "-", art.headline, art.risk,
                 f", {art.risk_reason}" if art.risk_reason else "")
    store.prune_audio([r["id"] for r in store.live()[: cfg.videos_for_recent]])
    return created


def approve(cfg: Config, store: Store, selector: str, synth=None) -> list[dict]:
    """Gibt Entwürfe frei. selector: "alle" (alle Entwürfe) oder IDs, getrennt durch Komma/Leerzeichen.
    Nur mit ausdrücklicher ID lassen sich auch "held"-Beiträge (hohes Risiko) freigeben."""
    sel = selector.strip().lower()
    wanted = None if sel in ("alle", "all") else {s for s in re.split(r"[,\s]+", sel) if s}
    approved: list[dict] = []
    for rec in store.all():
        ok = (rec["status"] == "draft") if wanted is None else (rec["id"] in wanted and rec["status"] in ("draft", "held"))
        if not ok:
            continue
        rec["status"] = "live"
        rec["drafted_at"] = rec["created_at"]
        rec["created_at"] = now_iso()  # Veröffentlichungszeit = Freigabe
        store.save(rec)
        if _voice_wanted(synth):
            add_voice(cfg, store, rec, synth)
        approved.append(rec)
        log.info("Freigegeben: %s | %s", rec["id"], rec["article"]["headline"])
    store.prune_audio([r["id"] for r in store.live()[: cfg.videos_for_recent]])
    return approved


def drafts_markdown(store: Store, cfg: Config | None = None) -> str:
    """Übersicht der offenen Entwürfe zum schnellen Lesen (z. B. in der GitHub-Actions-Zusammenfassung am Handy)."""
    pending = [r for r in store.all() if r["status"] in ("draft", "held")]
    if not pending:
        return "## Keine offenen Entwürfe\n"
    out = [f"## {len(pending)} Entwürfe warten auf Freigabe\n",
           "Zum Freigeben: Actions → newsbot → *Run workflow* → Feld **approve** mit den IDs (oder `alle`).\n"]
    for r in pending:
        a = r["article"]
        flag = " ⚠️ **hohes Risiko, nur mit ausdrücklicher ID freigeben**" if r["status"] == "held" else ""
        out.append(f"### `{r['id']}` · {a.get('rubrik') or a['category']} · Risiko: {a['risk']}{flag}\n**{a['headline']}**\n")
        out.append(f"_{a['teaser']}_\n")
        body = "\n\n".join(a["body"])
        secs = "\n\n".join(f"**{s['heading']}**\n\n{s['text']}" for s in a.get("sections", []))
        qs = "\n".join(f"- {q}" for q in a.get("open_questions", []))
        srcs = "\n".join(f"- [{s['name']}: {s['title']}]({s['url']})" for s in r.get("sources", [r["source"]]))
        shop = ""
        ideas = a.get("shopping", [])
        if ideas:
            boxes = build_shop_boxes(cfg, ideas) if cfg else []
            shop = "\n\n**Produktideen (Anzeige-Kasten):**\n" + (
                "\n".join(f"- {b['label']} (Suche: {b['query']}): " + ", ".join(f"[{l['program']}]({l['url']})" for l in b["links"])
                          for b in boxes) if boxes else
                "\n".join(f"- {i['label']} (Suche: {i['query']})" for i in ideas) + "\n_(Affiliate aus oder nicht eingerichtet: keine Links)_")
        out.append(f"<details><summary>Ganzen Entwurf lesen</summary>\n\n{body}\n\n{secs}\n\n"
                   f"> {a.get('verdict', '')}\n\n**Noch offen:**\n{qs}\n\n**Quellen:**\n{srcs}{shop}\n\n"
                   f"**Sprechtext:** {a.get('narration', '')}\n\n</details>\n")
    return "\n".join(out)


def build(cfg: Config, store: Store, out: str | Path = "public") -> Path:
    records = store.live()
    build_site(cfg, records, Path(out), audio_dir=store.audio_dir)
    log.info("Website mit %d Beiträgen nach %s gebaut", len(records), out)
    return Path(out)


def publish(cfg: Config, store: Store, public_root: str | Path = "public") -> list[str]:
    return publish_pending(cfg, store, Path(public_root))
