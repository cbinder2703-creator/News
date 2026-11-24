"""Ablauf: generate (Themen -> Entwürfe) -> approve (Freigabe) -> build (Website) -> publish (Social)."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from . import voice as voice_mod
from .config import RISK_ORDER, Config
from .affiliate import build_shop_boxes
from .editor import Topic
from .guides import guide_id
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
        if art.guide not in {t["slug"] for t in cfg.guide_topics}:
            art = art.model_copy(update={"guide": ""})
        if RISK_ORDER[art.risk] > RISK_ORDER[cfg.max_auto_risk]:
            status = "held"
        else:
            status = "draft" if cfg.review else "live"
        sources = [{"name": i.source, "url": i.link, "title": i.title,
                    "published": i.published.isoformat(timespec="seconds")} for i in topic_items]
        rec = {
            "id": article_id(primary.link),
            "slug": f"{slugify(art.focus_keyword or art.headline, 50)}-{article_id(primary.link)[:6]}",
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


def generate_guides(cfg: Config, store: Store, guide_writer, only: str | None = None) -> list[dict]:
    """Schreibt Kaufberater als Entwurf: fehlende Themen (höchstens guides_per_run pro Lauf) oder,
    mit `only`, eine neue Fassung genau dieses Kaufberaters. Die Online-Fassung bleibt bis zur Freigabe stehen."""
    topics = {t["slug"]: t for t in cfg.guide_topics}
    if only is not None:
        if only not in topics:
            raise ValueError(f"Kaufberater {only!r} steht nicht in config.yaml (guides.topics)")
        todo = [topics[only]]
    else:
        todo = [t for t in cfg.guide_topics if store.guide(t["slug"]) is None][: cfg.guides_per_run]
    created = []
    for topic in todo:
        guide = guide_writer.write(topic)
        if guide is None:
            continue
        rec = store.guide(topic["slug"]) or {"id": guide_id(topic["slug"]), "slug": topic["slug"],
                                             "created_at": now_iso(), "article": None}
        rec.update(topic=topic, draft=guide.model_dump(), drafted_at=now_iso())
        store.save_guide(rec)
        created.append(rec)
        log.info("[Kaufberater-Entwurf] %s | %s", rec["id"], guide.headline)
    return created


def rewrite(cfg: Config, store: Store, writer, selector: str) -> list[dict]:
    """Beiträge nach dem aktuellen Briefing neu schreiben lassen. selector: "alle" (alle live/Entwürfe) oder IDs.
    Mit Freigabe (review) gehen sie als Entwurf zurück in die Freigabe; die Adresse (slug) bleibt gleich."""
    sel = selector.strip().lower()
    wanted = None if sel in ("alle", "all") else {s for s in re.split(r"[,\s]+", sel) if s}
    done = []
    for rec in store.all():
        if rec["status"] not in ("live", "draft") or (wanted is not None and rec["id"] not in wanted):
            continue
        names = [s.get("name", "") for s in (rec.get("sources") or [rec.get("source") or {}])]
        art = writer.rewrite(rec["article"], names)
        if art is None:
            continue
        was_live = rec["status"] == "live"
        rec["article"] = art.model_dump()
        rec["rewritten_at"] = now_iso()
        if cfg.review:
            rec["status"] = "draft"
            if was_live:
                rec["keep_date"] = True
        store.save(rec)
        done.append(rec)
        log.info("Neu geschrieben: %s | %s", rec["id"], art.headline)
    return done


def approve(cfg: Config, store: Store, selector: str, synth=None) -> list[dict]:
    """Gibt Entwürfe frei. selector: "alle" (alle Entwürfe) oder IDs, getrennt durch Komma/Leerzeichen.
    Nur mit ausdrücklicher ID lassen sich auch "held"-Beiträge (hohes Risiko) freigeben.
    Kaufberater (IDs "kb-...") werden ebenso freigegeben."""
    sel = selector.strip().lower()
    wanted = None if sel in ("alle", "all") else {s for s in re.split(r"[,\s]+", sel) if s}
    approved: list[dict] = []
    for g in store.guides():
        if g.get("draft") and (wanted is None or g["id"] in wanted):
            g["article"], g["draft"] = g["draft"], None
            g["updated_at"] = now_iso()
            store.save_guide(g)
            approved.append(g)
            log.info("Kaufberater freigegeben: %s | %s", g["id"], g["article"]["headline"])
    for rec in store.all():
        ok = (rec["status"] == "draft") if wanted is None else (rec["id"] in wanted and rec["status"] in ("draft", "held"))
        if not ok:
            continue
        rec["status"] = "live"
        if rec.pop("keep_date", False):  # neu geschriebener, schon veröffentlichter Beitrag behält sein Datum
            rec["updated_at"] = now_iso()
        else:
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
    guide_drafts = [g for g in store.guides() if g.get("draft")]
    if not pending and not guide_drafts:
        return "## Keine offenen Entwürfe\n"
    out = [f"## {len(pending) + len(guide_drafts)} Entwürfe warten auf Freigabe\n",
           "Zum Freigeben: Actions → newsbot → *Run workflow* → Feld **approve** mit den IDs (oder `alle`).\n"]
    for g in guide_drafts:
        d = g["draft"]
        state = "neue Fassung, die alte bleibt bis zur Freigabe online" if g.get("article") else "neu"
        out.append(f"### `{g['id']}` · Kaufberater ({state})\n**{d['headline']}**\n")
        out.append(f"SEO-Titel: {d['seo_title']} · Suchwort: {g['topic'].get('keyword') or g['topic']['title']}\n")
        secs = "\n\n".join(f"**{s['heading']}**\n\n{s['text']}" for s in d["sections"])
        crit = "\n".join(f"- **{c['name']}**: {c['text']}" for c in d["criteria"])
        faq = "\n\n".join(f"**{f['question']}** {f['answer']}" for f in d["faq"])
        out.append(f"<details><summary>Ganzen Kaufberater lesen</summary>\n\n{d['intro']}\n\n{secs}\n\n"
                   f"**Kaufkriterien:**\n{crit}\n\n**Typische Fehlkäufe:**\n" + "\n".join(f"- {m}" for m in d["mistakes"])
                   + f"\n\n**Häufige Fragen:**\n\n{faq}\n\n> {d['summary']}\n\n</details>\n")
    for r in pending:
        a = r["article"]
        flag = " ⚠️ **hohes Risiko, nur mit ausdrücklicher ID freigeben**" if r["status"] == "held" else ""
        out.append(f"### `{r['id']}` · {a.get('rubrik') or a['category']} · Risiko: {a['risk']}{flag}\n**{a['headline']}**\n")
        out.append(f"_{a['teaser']}_\n")
        if a.get("seo_title"):
            out.append(f"SEO-Titel: {a['seo_title']} · Suchwort: {a.get('focus_keyword', '')}"
                       + (f" · verlinkt Kaufberater `{a['guide']}`" if a.get("guide") else "") + "\n")
        body = "\n\n".join(a["body"])
        secs = "\n\n".join(f"**{s['heading']}**\n\n{s['text']}" for s in a.get("sections", []))
        if a.get("faq"):
            secs += "\n\n**Häufige Fragen:**\n\n" + "\n\n".join(f"**{f['question']}** {f['answer']}" for f in a["faq"])
        qs ="\n".join(f"- {q}" for q in a.get("open_questions", []))
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


def drafts_index(store: Store) -> list[dict]:
    """Alle offenen Entwürfe (News und Kaufberater) in einer einheitlichen, schlanken Form für die Admin-Seite."""
    items: list[dict] = []
    for r in store.all():
        if r["status"] not in ("draft", "held"):
            continue
        a = r["article"]
        items.append({
            "id": r["id"], "kind": "news", "status": r["status"], "created_at": r["created_at"],
            "rubrik": a.get("rubrik") or a["category"], "risk": a["risk"], "risk_reason": a.get("risk_reason", ""),
            "headline": a["headline"], "teaser": a["teaser"], "body": a["body"],
            "sections": [{"heading": s["heading"], "text": s["text"]} for s in a.get("sections", [])],
            "verdict": a.get("verdict", ""), "open_questions": a.get("open_questions", []),
            "sources": [{"name": s["name"], "url": s["url"], "title": s["title"]}
                        for s in r.get("sources", [r["source"]])],
            "shopping": [{"label": i["label"], "query": i["query"]} for i in a.get("shopping", [])],
        })
    for g in store.guides():
        d = g.get("draft")
        if not d:
            continue
        sections = [{"heading": s["heading"], "text": s["text"]} for s in d["sections"]]
        sections += [{"heading": c["name"], "text": c["text"]} for c in d["criteria"]]
        if d.get("mistakes"):
            sections.append({"heading": "Typische Fehlkäufe", "text": "\n".join(f"- {m}" for m in d["mistakes"])})
        items.append({
            "id": g["id"], "kind": "guide", "status": "draft", "created_at": g.get("drafted_at") or g["created_at"],
            "rubrik": "Kaufberater" + (" (neue Fassung)" if g.get("article") else ""), "risk": "low", "risk_reason": "",
            "headline": d["headline"], "teaser": d["meta_description"], "body": [d["intro"]], "sections": sections,
            "verdict": d.get("summary", ""), "open_questions": [], "sources": [],
            "shopping": [{"label": i["label"], "query": i["query"]} for i in d.get("shopping", [])],
        })
    return sorted(items, key=lambda i: i["created_at"], reverse=True)


def write_drafts_index(store: Store) -> Path:
    """Schreibt data/drafts.json. Die Admin-Seite (über den Worker) liest diese Datei."""
    path = store.dir / "drafts.json"
    path.write_text(json.dumps({"updated_at": now_iso(), "drafts": drafts_index(store)}, indent=1, ensure_ascii=False),
                    encoding="utf-8")
    return path


def build(cfg: Config, store: Store, out: str | Path = "public") -> Path:
    records = store.live()
    build_site(cfg, records, Path(out), audio_dir=store.audio_dir, guides=store.guides(),
               photos_dir=store.dir / "photos")
    log.info("Website mit %d Beiträgen nach %s gebaut", len(records), out)
    return Path(out)


def publish(cfg: Config, store: Store, public_root: str | Path = "public") -> list[str]:
    return publish_pending(cfg, store, Path(public_root))
