from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import pipeline
from .config import load_config
from .store import Store
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="newsbot", description="Automatische Nachrichtenmarke")
    ap.add_argument("command", choices=["generate", "build", "publish", "run", "demo"],
                    help="generate: neue Beiträge | build: Website | publish: Social-Posts | "
                         "run: generate+build | demo: Offline-Demo ohne API-Keys")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--data", default="data", help="Ordner für Beiträge/Zustand")
    ap.add_argument("--out", default="public", help="Ausgabeordner der Website")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _load_dotenv()
    cfg = load_config(args.config)

    if args.command == "demo":
        from .demo_data import demo_items

        cfg.site_url = "http://localhost:8000"
        store = Store(".demo/data")
        pipeline.generate(cfg, store, StubWriter(), items=demo_items())
        out = pipeline.build(cfg, store, ".demo/public")
        print(f"\nDemo gebaut: {out}\nAnsehen:  python -m http.server 8000 --directory {out}")
        return 0

    store = Store(args.data)
    if args.command in ("generate", "run"):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY fehlt (siehe .env.example). Zum Ausprobieren: python -m newsbot demo", file=sys.stderr)
            return 2
        pipeline.generate(cfg, store, Writer(cfg.model, cfg.brand_name, cfg.tagline))
    if args.command in ("build", "run"):
        pipeline.build(cfg, store, args.out)
    if args.command == "publish":
        done = pipeline.publish(cfg, store, args.out)
        print(f"{len(done)} Posts veröffentlicht")
    return 0
