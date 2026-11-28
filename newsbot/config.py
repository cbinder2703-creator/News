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
    voice_enabled: bool = True
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    voice_model: str = "eleven_multilingual_v2"
    review: bool = True
    brand_description: str = ""
    indexnow_key: str = ""
    analytics_token: str = ""
    haltung: str = ""
    rubriken: list[dict] = field(default_factory=list)
    focus: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    affiliate_enabled: bool = False
    affiliate_max: int = 3
    affiliate_disclosure: str = ""
    affiliate_amazon_notice: str = ""
    affiliate_programs: list[dict] = field(default_factory=list)
    commerce: bool = False
    guides_enabled: bool = False
    guides_per_run: int = 1
    guide_topics: list[dict] = field(default_factory=list)
    admin_api_url: str = ""
    show_sources: bool = True
    show_video: bool = False
    contact_form: bool = False
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
    v = raw.get("voice") or {}
    ed = raw.get("editorial") or {}
    af = raw.get("affiliate") or {}
    gd = raw.get("guides") or {}
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
        voice_enabled=bool(v.get("enabled", True)),
        voice_id=v.get("voice_id", "21m00Tcm4TlvDq8ikWAM"),
        voice_model=v.get("model_id", "eleven_multilingual_v2"),
        review=ed.get("mode", "review") != "auto",
        haltung=(ed.get("haltung") or "").strip(),
        rubriken=ed.get("rubriken") or [],
        focus=ed.get("focus") or [],
        avoid=ed.get("avoid") or [],
        affiliate_enabled=bool(af.get("enabled", False)),
        affiliate_max=int(af.get("max_links_per_article", 3)),
        affiliate_disclosure=af.get("disclosure", "Anzeige: Affiliate-Links."),
        affiliate_amazon_notice=af.get("amazon_notice", ""),
        affiliate_programs=af.get("programs") or [],
        commerce=bool(ed.get("kaufbezug", False)),
        guides_enabled=bool(gd.get("enabled", False)),
        guides_per_run=int(gd.get("per_run", 1)),
        guide_topics=[t for t in (gd.get("topics") or []) if t.get("slug") and t.get("title")],
        show_sources=bool(ed.get("show_sources", True)),
        show_video=bool(ed.get("show_video", False)),
        analytics_token=str((raw.get("analytics") or {}).get("cloudflare_token") or "").strip(),
        indexnow_key=str((raw.get("indexnow") or {}).get("key") or "").strip(),
        brand_description=str((raw.get("brand") or {}).get("description") or "").strip(),
        contact_form=bool((raw.get("contact_form") or {}).get("enabled")),
        admin_api_url=((raw.get("admin") or {}).get("api_url") or "").rstrip("/"),
        sources=raw.get("sources", []),
    )
