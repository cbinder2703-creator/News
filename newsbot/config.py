from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass
class Config:
    brand_name: str
    tagline: str
    site_url: str
    accent: str
    contact_email: str
    model: str
    disclosure: str
    articles_per_run: int
    max_age_hours: int
    max_auto_risk: str
    videos_for_recent: int
    publish_per_run: int
    graph_version: str
    facebook: list[str]
    instagram: list[str]
    tiktok: list[str]
    tiktok_privacy: str
    sources: list[dict] = field(default_factory=list)

    @property
    def base_path(self) -> str:
        """Pfad-Präfix der Website (z.B. '/news' bei GitHub Pages)."""
        return urlparse(self.site_url).path.rstrip("/")

    @property
    def host(self) -> str:
        return urlparse(self.site_url).netloc or self.site_url


def load_config(path: str | Path = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    b, ai, p, s = raw["brand"], raw["ai"], raw["pipeline"], raw["social"]
    return Config(
        brand_name=b["name"],
        tagline=b.get("tagline", ""),
        site_url=b["site_url"].rstrip("/"),
        accent=b.get("accent", "#ff4d2e"),
        contact_email=b.get("contact_email", ""),
        model=ai.get("model", "claude-opus-5-5"),
        disclosure=ai["disclosure"],
        articles_per_run=int(p.get("articles_per_run", 3)),
        max_age_hours=int(p.get("max_age_hours", 24)),
        max_auto_risk=p.get("max_auto_risk", "medium"),
        videos_for_recent=int(p.get("videos_for_recent", 20)),
        publish_per_run=int(p.get("publish_per_run", 2)),
        graph_version=s.get("graph_version", "v23.0"),
        facebook=s.get("facebook") or [],
        instagram=s.get("instagram") or [],
        tiktok=s.get("tiktok") or [],
        tiktok_privacy=s.get("tiktok_privacy", "SELF_ONLY"),
        sources=raw.get("sources", []),
    )
