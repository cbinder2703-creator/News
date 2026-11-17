"""Affiliate-Links (Amazon PartnerNet, OTTO über Awin u. a.) als gekennzeichneter Kasten unter dem Beitrag.

Grundsätze: Links entstehen erst beim Bauen der Seite aus neutralen Suchbegriffen (so wirkt eine geänderte ID sofort überall);
nur Suchlinks, keine Preise oder Produktbehauptungen; Programme ohne vollständige Zugangsdaten bleiben aus.
"""
from __future__ import annotations

import re
from urllib.parse import quote, quote_plus

from .config import Config

PLACEHOLDER = re.compile(r"DEINE_|MERCHANT_ID|XXX", re.I)


def active_programs(cfg: Config) -> list[dict]:
    if not cfg.affiliate_enabled:
        return []
    out = []
    for p in cfg.affiliate_programs:
        if not p.get("enabled"):
            continue
        if p.get("kind") == "amazon" and (p.get("tag") or "").strip() and not PLACEHOLDER.search(p["tag"]):
            out.append(p)
        elif p.get("kind") == "template":
            tpl, search = p.get("link_template", ""), p.get("search_url", "")
            if "{url}" in tpl and "{query}" in search and tpl.startswith("https://") and search.startswith("https://") \
                    and not PLACEHOLDER.search(tpl):
                out.append(p)
    return out


def has_amazon(cfg: Config) -> bool:
    return any(p.get("kind") == "amazon" for p in active_programs(cfg))


def link_for(program: dict, query: str) -> str:
    if program["kind"] == "amazon":
        return f"https://{program.get('domain', 'www.amazon.de')}/s?k={quote_plus(query)}&tag={quote(program['tag'].strip())}"
    target = program["search_url"].replace("{query}", quote(query))
    return program["link_template"].replace("{url}", quote(target, safe="")).replace("{query}", quote_plus(query))


def clean_query(q: str) -> str | None:
    q = re.sub(r"\s+", " ", q or "").strip()
    if not q or len(q) > 60 or re.search(r"https?:|www\.|[<>{}]", q, re.I):
        return None
    return q


def build_shop_boxes(cfg: Config, ideas: list[dict]) -> list[dict]:
    """[{label, reason, query, links:[{program, url}]}], leer wenn Affiliate aus oder kein Programm vollständig eingerichtet."""
    programs = active_programs(cfg)
    if not programs:
        return []
    boxes, seen = [], set()
    for idea in ideas:
        query = clean_query(idea.get("query", ""))
        if not query or query.lower() in seen:
            continue
        seen.add(query.lower())
        boxes.append({"label": idea.get("label") or query, "reason": idea.get("reason", ""), "query": query,
                      "links": [{"program": p["name"], "url": link_for(p, query)} for p in programs]})
        if len(boxes) >= cfg.affiliate_max:
            break
    return boxes
