"""IndexNow: neue und geänderte Seiten sofort an Bing melden (Bing teilt sie mit Yandex, Seznam, Naver).

Bing steckt auch hinter der Suche von ChatGPT, Copilot und DuckDuckGo. Google nutzt IndexNow nicht; dort hilft die Sitemap.
Der Schlüssel ist absichtlich öffentlich: Er liegt als Datei auf der Website und beweist, dass die Meldung von uns kommt.
Gemeldet wird nur, was sich seit der letzten Meldung geändert hat (Stand in data/indexnow.json).
"""
from __future__ import annotations

import json
import logging

import requests

from .config import Config
from .store import Store

log = logging.getLogger("newsbot.indexnow")
ENDPOINT = "https://api.indexnow.org/indexnow"


def page_stamps(cfg: Config, store: Store) -> dict[str, str]:
    """Öffentliche Seiten mit Änderungsstempel. Startseite und Übersichten ändern sich mit dem neuesten Beitrag."""
    from .site import RUBRIK_PAGES  # vermeidet Zyklus beim Import

    site = cfg.site_url.rstrip("/")
    live = store.live()
    out: dict[str, str] = {}
    for r in live:
        out[f"{site}/a/{r['slug']}/"] = r.get("updated_at") or r["created_at"]
    guides = [g for g in store.guides() if g.get("article")]
    for g in guides:
        out[f"{site}/kaufberater/{g['slug']}/"] = g.get("updated_at") or g.get("created_at", "")
    if live:
        newest = max(r["created_at"] for r in live)
        out[f"{site}/"] = newest
        for slug, _, rubs, _, _ in RUBRIK_PAGES:
            stamps = [r["created_at"] for r in live if (r["article"].get("rubrik") or "") in rubs]
            if stamps:
                out[f"{site}/{slug}/"] = max(stamps)
    if guides:
        out[f"{site}/kaufberater/"] = max(g.get("updated_at") or g.get("created_at", "") for g in guides)
    return out


def submit(cfg: Config, store: Store, http=None) -> int:
    """Meldet geänderte Seiten. Gibt die Zahl der gemeldeten Adressen zurück (0 ohne Schlüssel oder ohne Änderungen)."""
    if not cfg.indexnow_key:
        return 0
    http = http or requests
    state_path = store.dir / "indexnow.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    stamps = page_stamps(cfg, store)
    changed = [u for u, s in stamps.items() if state.get(u) != s]
    if not changed:
        log.info("IndexNow: nichts Neues zu melden")
        return 0
    host = cfg.site_url.split("://", 1)[-1].strip("/")
    body = {"host": host, "key": cfg.indexnow_key, "keyLocation": f"{cfg.site_url.rstrip('/')}/{cfg.indexnow_key}.txt",
            "urlList": changed[:10000]}
    try:
        res = http.post(ENDPOINT, json=body, timeout=30, headers={"Content-Type": "application/json; charset=utf-8"})
    except requests.RequestException as exc:
        log.warning("IndexNow nicht erreichbar: %s", type(exc).__name__)
        return 0
    if res.status_code not in (200, 202):
        log.warning("IndexNow: HTTP %s", res.status_code)
        return 0
    state.update({u: stamps[u] for u in changed})
    state_path.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    log.info("IndexNow: %d Adressen gemeldet", len(changed))
    return len(changed)
