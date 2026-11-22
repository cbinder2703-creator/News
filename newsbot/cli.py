from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

from . import notify, photos, pipeline
from .config import load_config
from .store import Store
from .editor import Editor, StubEditor
from .guides import GuideWriter, StubGuideWriter
from .writer import StubWriter, Writer


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def _write_summary(markdown: str) -> None:
    """In GitHub Actions: Entwürfe in die Zusammenfassung des Laufs schreiben (am Handy lesbar)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    print(markdown)
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="newsbot", description="Automatische Nachrichtenmarke")
    ap.add_argument("command", choices=["generate", "approve", "reject", "decisions", "notify", "drafts", "build",
                                        "publish", "run", "guide", "photos", "demo"],
                    help="generate: Entwürfe erzeugen (News + fehlende Kaufberater) | approve: Entwürfe freigeben | "
                         "reject: Entwürfe ablehnen | decisions: Klicks aus WhatsApp umsetzen (data/decisions) | "
                         "notify: neue Entwürfe per WhatsApp schicken | photos: Titelfotos von Pexels holen | "
                         "drafts: offene Entwürfe zeigen | build: Website | publish: Social-Posts | run: generate+build | "
                         "guide: Kaufberater <slug> neu schreiben (als Entwurf) | demo: Offline-Demo ohne API-Keys")
    ap.add_argument("arg", nargs="?", default="",
                    help="bei approve/reject: IDs (Komma-getrennt), bei approve auch 'alle'; bei guide: slug")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--data", default="data", help="Ordner für Beiträge/Zustand")
    ap.add_argument("--out", default="public", help="Ausgabeordner der Website")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _load_dotenv()
    cfg = load_config(args.config)

    if args.command == "demo":
        from .demo_data import demo_items, fake_synth

        cfg.site_url = "http://localhost:8000"
        store = Store(".demo/data")
        guide = cfg.guide_topics[0]["slug"] if cfg.guide_topics else ""
        pipeline.generate(cfg, store, StubWriter(guide), items=demo_items(), synth=fake_synth, editor=StubEditor(cfg))
        if cfg.guide_topics:  # Demo zeigt Kaufberater auch, wenn sie in config.yaml noch aus sind
            cfg.guides_per_run = len(cfg.guide_topics)
            pipeline.generate_guides(cfg, store, StubGuideWriter())
        pipeline.approve(cfg, store, "alle", synth=fake_synth)  # Demo: alles freigeben
        out = pipeline.build(cfg, store, ".demo/public")
        print(f"\nDemo gebaut: {out}\nAnsehen:  python -m http.server 8000 --directory {out}")
        return 0

    store = Store(args.data)
    if args.command in ("generate", "run"):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY fehlt (siehe .env.example). Zum Ausprobieren: python -m newsbot demo", file=sys.stderr)
            return 2
        pipeline.generate(cfg, store, Writer(cfg), editor=Editor(cfg))
        if cfg.guides_enabled:
            pipeline.generate_guides(cfg, store, GuideWriter(cfg))
        _write_summary(pipeline.drafts_markdown(store, cfg))
    if args.command == "guide":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY fehlt (siehe .env.example).", file=sys.stderr)
            return 2
        try:
            done = pipeline.generate_guides(cfg, store, GuideWriter(cfg), only=args.arg)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(f"{len(done)} Kaufberater-Entwurf erzeugt. Lesen: python -m newsbot drafts")
    if args.command == "approve":
        done = pipeline.approve(cfg, store, args.arg or "alle")
        print(f"{len(done)} Beiträge freigegeben")
        if not done:
            print("Nichts freigegeben: IDs prüfen (siehe `python -m newsbot drafts`).", file=sys.stderr)
    if args.command == "reject":
        ids = [i for i in re.split(r"[,\s]+", args.arg.strip().lower()) if i]
        done = notify.reject(store, ids)
        print(f"{len(done)} Entwürfe abgelehnt")
    if args.command == "decisions":
        res = notify.apply_decisions(cfg, store, pipeline.approve)
        print(f"WhatsApp-Entscheidungen: {len(res['approved'])} freigegeben, {len(res['rejected'])} abgelehnt")
    if args.command == "notify":
        print(f"{notify.notify(cfg, store)} WhatsApp-Nachrichten gesendet")
    if args.command == "photos":
        print(f"{photos.backfill(store)} Fotos geholt")
    if args.command == "drafts":
        print(pipeline.drafts_markdown(store, cfg))
    if args.command in ("build", "run"):
        pipeline.build(cfg, store, args.out)
    if args.command == "publish":
        done = pipeline.publish(cfg, store, args.out)
        print(f"{len(done)} Posts veröffentlicht")
    if args.command in ("generate", "run", "approve", "reject", "decisions", "guide"):
        pipeline.write_drafts_index(store)  # Grundlage der Admin-Seite
    return 0
