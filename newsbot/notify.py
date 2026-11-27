"""Freigabe per WhatsApp: pro Entwurf eine Nachricht mit den Buttons „Freigeben“ und „Ablehnen“.

Ablauf: `python -m newsbot notify` schickt neue Entwürfe über die WhatsApp Cloud API (Vorlage mit Schnellantwort-Buttons).
Der Klick landet beim Webhook (worker/whatsapp_webhook.js), der die Entscheidung als Datei in data/decisions/ ablegt und
den Workflow startet. Dort setzt `python -m newsbot decisions` sie um. Nicht getestet gegen ein echtes WhatsApp-Konto.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import requests

from .config import Config
from .store import Store, now_iso

log = logging.getLogger("newsbot.notify")

TEMPLATE = "entwurf_freigabe"
LANGUAGE = "de"
# Vorlagentext, so in Meta Business Manager anlegen (Kategorie "Dienstprogramm", Sprache Deutsch, Buttons: Schnellantwort):
#   Neuer Entwurf ({{1}}): {{2}}
#   {{3}}
#   Einordnung: {{4}}
#   Quellen: {{5}}
# Buttons: "Freigeben" und "Ablehnen"
TEMPLATE_BODY = "Neuer Entwurf ({{1}}): {{2}}\n\n{{3}}\n\nEinordnung: {{4}}\n\nQuellen: {{5}}"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,60}$")


def _clean(text: str, limit: int) -> str:
    """WhatsApp-Vorlagenparameter: keine Zeilenumbrüche/Tabs, keine 4+ Leerzeichen am Stück, begrenzte Länge."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if len(t) > limit:
        t = t[: limit - 1].rstrip() + "…"
    return t or "-"


def _button(index: int, payload: str) -> dict:
    return {"type": "button", "sub_type": "quick_reply", "index": str(index),
            "parameters": [{"type": "payload", "payload": payload}]}


def message_for(to: str, rec_id: str, label: str, headline: str, teaser: str, verdict: str, sources: str,
                template: str = TEMPLATE, language: str = LANGUAGE) -> dict:
    """Request-Body für die WhatsApp Cloud API."""
    params = [label, headline, teaser, verdict, sources]
    limits = [60, 110, 220, 300, 140]
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": language},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": _clean(p, n)} for p, n in zip(params, limits)]},
                _button(0, f"approve:{rec_id}"),
                _button(1, f"reject:{rec_id}"),
            ],
        },
    }


def pending_messages(store: Store, to: str) -> list[tuple[str, dict, callable]]:
    """(id, Request-Body, Markierer) für alle Entwürfe, die noch keine Nachricht bekommen haben."""
    out = []
    for r in store.all():
        if r["status"] not in ("draft", "held") or r.get("notified"):
            continue
        a = r["article"]
        warn = " ⚠️ HOHES RISIKO" if r["status"] == "held" else ""
        label = f"{a.get('rubrik') or a['category']}, Risiko {a['risk']}{warn}"
        srcs = ", ".join(dict.fromkeys(s["name"] for s in r.get("sources", [r["source"]])))
        body = message_for(to, r["id"], label, a["headline"], a["teaser"], a.get("verdict", ""), srcs)

        def mark(rec=r):
            rec["notified"] = now_iso()
            store.save(rec)
        out.append((r["id"], body, mark))
    for g in store.guides():
        d = g.get("draft")
        if not d or g.get("notified_for") == g.get("drafted_at"):
            continue
        body = message_for(to, g["id"], "Kaufberater", d["headline"], d["meta_description"], d.get("summary", ""), "-")

        def mark(rec=g):
            rec["notified_for"] = rec.get("drafted_at")
            store.save_guide(rec)
        out.append((g["id"], body, mark))
    return out


def notify(cfg: Config, store: Store, session: requests.Session | None = None) -> int:
    """Schickt neue Entwürfe per WhatsApp. Ohne Zugangsdaten passiert nichts. Gibt die Zahl gesendeter Nachrichten zurück."""
    token = os.environ.get("WHATSAPP_TOKEN", "")
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    to = re.sub(r"\D", "", os.environ.get("WHATSAPP_TO", ""))
    if not (token and phone_id and to):
        log.info("WhatsApp nicht eingerichtet (WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_TO): keine Benachrichtigung")
        return 0
    http = session or requests
    url = f"https://graph.facebook.com/{cfg.graph_version}/{phone_id}/messages"
    sent = 0
    for rec_id, body, mark in pending_messages(store, to):
        if not ID_RE.match(rec_id):
            log.warning("ID %r passt nicht zum Muster, keine Nachricht", rec_id)
            continue
        try:
            resp = http.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        except requests.RequestException as exc:
            log.warning("WhatsApp-Versand fehlgeschlagen (%s): %s", rec_id, exc)
            continue
        if resp.status_code >= 300:
            log.warning("WhatsApp-Versand fehlgeschlagen (%s): HTTP %s %s", rec_id, resp.status_code, resp.text[:300])
            continue
        mark()
        sent += 1
        log.info("WhatsApp-Nachricht gesendet: %s", rec_id)
    return sent


# --- Entscheidungen aus dem Webhook (Dateien in data/decisions/, eine je Klick) ---

DECISION_RE = re.compile(r"^(approve|reject|unpublish)-([a-z0-9][a-z0-9-]{2,60})\.txt$")


def apply_decisions(cfg: Config, store: Store, approve_fn, synth=None) -> dict[str, list[str]]:
    """Setzt alle Dateien in data/decisions/ um und löscht sie. Gibt {"approved": [...], "rejected": [...]} zurück."""
    folder = store.dir / "decisions"
    result: dict[str, list[str]] = {"approved": [], "rejected": []}
    if not folder.exists():
        return result
    files = sorted(folder.glob("*.txt"))
    approve_ids, reject_ids, unpublish_ids = [], [], []
    for p in files:
        m = DECISION_RE.match(p.name)
        if not m:
            log.warning("Unbekannte Datei in decisions/ ignoriert: %s", p.name)
            continue
        {"approve": approve_ids, "reject": reject_ids, "unpublish": unpublish_ids}[m.group(1)].append(m.group(2))
    if unpublish_ids:
        result["unpublished"] = unpublish(store, unpublish_ids)
    approve_ids = [i for i in approve_ids if i not in reject_ids]  # im Zweifel gilt Ablehnen
    if reject_ids:
        result["rejected"] = reject(store, reject_ids)
    if approve_ids:
        done = approve_fn(cfg, store, ",".join(approve_ids), synth=synth)
        result["approved"] = [d["id"] for d in done]
    for p in files:
        p.unlink()
    return result


def unpublish(store: Store, ids: list[str]) -> list[str]:
    """Nimmt veröffentlichte Beiträge von der Seite: Status 'removed' (Daten bleiben, nur nicht mehr online)."""
    done, wanted = [], set(ids)
    for rec in store.all():
        if rec["id"] in wanted and rec["status"] == "live":
            rec["status"] = "removed"
            store.save(rec)
            done.append(rec["id"])
            log.info("Offline genommen: %s | %s", rec["id"], rec["article"]["headline"])
    return done


def reject(store: Store, ids: list[str]) -> list[str]:
    """Lehnt Entwürfe ab: Status 'rejected' (nie online, nicht mehr in der Entwurfsliste)."""
    done = []
    wanted = set(ids)
    for rec in store.all():
        if rec["id"] in wanted and rec["status"] in ("draft", "held"):
            rec["status"] = "rejected"
            store.save(rec)
            done.append(rec["id"])
    for g in store.guides():
        if g["id"] in wanted and g.get("draft"):
            g["draft"] = None
            store.save_guide(g)
            done.append(g["id"])
    return done
