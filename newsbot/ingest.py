"""Quellen einlesen: RSS/Atom holen, bereinigen, deduplizieren, auswählen."""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import feedparser
import requests

log = logging.getLogger("newsbot.ingest")
USER_AGENT = "newsbot/1.0 (+RSS-Reader)"


@dataclass
class SourceItem:
    title: str
    summary: str
    link: str
    source: str
    published: datetime


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_feed(content: bytes, source_name: str, now: datetime | None = None) -> list[SourceItem]:
    now = now or datetime.now(timezone.utc)
    parsed = feedparser.parse(content)
    items: list[SourceItem] = []
    for e in parsed.entries:
        link = e.get("link")
        title = clean(e.get("title", ""))
        if not link or not title:
            continue
        ts = e.get("published_parsed") or e.get("updated_parsed")
        published = datetime(*ts[:6], tzinfo=timezone.utc) if ts else now
        items.append(SourceItem(title, clean(e.get("summary", ""))[:1500], link, source_name, published))
    return items


def fetch(sources: list[dict], timeout: int = 15) -> list[SourceItem]:
    items: list[SourceItem] = []
    for src in sources:
        try:
            r = requests.get(src["url"], timeout=timeout, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            items.extend(parse_feed(r.content, src["name"]))
        except Exception as exc:  # eine kaputte Quelle darf den Lauf nicht stoppen
            log.warning("Quelle %s nicht lesbar: %s", src.get("name"), exc)
    return items


def select(
    items: list[SourceItem],
    seen_urls: set[str],
    max_age_hours: int,
    limit: int,
    now: datetime | None = None,
) -> list[SourceItem]:
    """Neueste, ungesehene, nicht doppelte Meldungen, reihum über die Quellen verteilt."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    fresh = [i for i in items if i.link not in seen_urls and i.published >= cutoff]
    fresh.sort(key=lambda i: i.published, reverse=True)

    unique: list[SourceItem] = []
    for it in fresh:
        t = it.title.lower()
        if any(SequenceMatcher(None, t, u.title.lower()).ratio() > 0.75 for u in unique):
            continue
        unique.append(it)

    by_source: dict[str, list[SourceItem]] = {}
    for it in unique:
        by_source.setdefault(it.source, []).append(it)
    picked: list[SourceItem] = []
    while len(picked) < limit and any(by_source.values()):
        for queue in by_source.values():
            if queue and len(picked) < limit:
                picked.append(queue.pop(0))
    return picked
