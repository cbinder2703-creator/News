"""Veröffentlichung auf Facebook, Instagram und TikTok über die offiziellen APIs.

Hinweis: Diese Adapter sind nach der jeweils dokumentierten API gebaut, aber ohne echte
Konten nicht live getestet. Erster Lauf immer mit einem Testkonto bzw. TikTok `SELF_ONLY`.
Instagram und Facebook holen Bild/Video von einer öffentlichen URL (daher die Website),
TikTok bekommt die Videodatei direkt hochgeladen.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import Config

log = logging.getLogger("newsbot.social")
TIMEOUT = 60


class PublishError(RuntimeError):
    pass


@dataclass
class Assets:
    """Alles, was eine Plattform für einen Beitrag braucht."""
    article_url: str
    image_url: str
    video_url: str | None
    video_path: Path | None


def _json(resp: requests.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not resp.ok or "error" in data:
        raise PublishError(f"HTTP {resp.status_code}: {str(data)[:300] or resp.text[:300]}")
    return data


def wait_public(url: str, tries: int = 30, delay: float = 10) -> None:
    """Wartet, bis die Website-Datei öffentlich erreichbar ist (Deploy-Verzögerung)."""
    for _ in range(tries):
        try:
            if requests.head(url, timeout=15, allow_redirects=True).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(delay)
    raise PublishError(f"URL nicht erreichbar: {url}")


def _hashtags(art: dict) -> str:
    return " ".join(f"#{h}" for h in art["hashtags"])


class Facebook:
    name = "facebook"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.page = os.environ.get("FACEBOOK_PAGE_ID")
        self.token = os.environ.get("FACEBOOK_PAGE_TOKEN")

    @property
    def enabled(self) -> bool:
        return bool(self.page and self.token and self.cfg.facebook)

    def post(self, kind: str, rec: dict, assets: Assets) -> str:
        art = rec["article"]
        base = f"https://graph.facebook.com/{self.cfg.graph_version}/{self.page}"
        if kind == "link":
            # Link-Post: Facebook baut die Vorschau aus den og:-Tags der Beitragsseite
            r = requests.post(f"{base}/feed", timeout=TIMEOUT, data={
                "message": f"{art['facebook_text']}\n\n{_hashtags(art)}",
                "link": assets.article_url, "access_token": self.token})
        elif kind == "video" and assets.video_url:
            r = requests.post(f"{base}/videos", timeout=TIMEOUT, data={
                "file_url": assets.video_url, "title": art["headline"],
                "description": f"{art['facebook_text']}\n\n{assets.article_url}",
                "access_token": self.token})
        else:
            raise PublishError(f"Format {kind!r} nicht verfügbar")
        return str(_json(r).get("id"))


class Instagram:
    name = "instagram"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.user = os.environ.get("INSTAGRAM_USER_ID")
        self.token = os.environ.get("INSTAGRAM_TOKEN")

    @property
    def enabled(self) -> bool:
        return bool(self.user and self.token and self.cfg.instagram)

    def post(self, kind: str, rec: dict, assets: Assets) -> str:
        art = rec["article"]
        caption = f"{art['instagram_caption']}\n\nMehr: {assets.article_url}\n\n{_hashtags(art)}\n\nMit KI erstellt"
        base = f"https://graph.facebook.com/{self.cfg.graph_version}"
        params = {"caption": caption[:2200], "access_token": self.token}
        if kind == "image":
            params["image_url"] = assets.image_url
        elif kind == "reel" and assets.video_url:
            params.update(media_type="REELS", video_url=assets.video_url, share_to_feed="true")
        else:
            raise PublishError(f"Format {kind!r} nicht verfügbar")
        container = _json(requests.post(f"{base}/{self.user}/media", timeout=TIMEOUT, data=params))["id"]
        for _ in range(30):  # Verarbeitung abwarten
            status = _json(requests.get(f"{base}/{container}", timeout=TIMEOUT, params={
                "fields": "status_code", "access_token": self.token})).get("status_code")
            if status == "FINISHED":
                break
            if status in ("ERROR", "EXPIRED"):
                raise PublishError(f"Instagram-Container {status}")
            time.sleep(10)
        else:
            raise PublishError("Instagram-Container nicht rechtzeitig fertig")
        pub = requests.post(f"{base}/{self.user}/media_publish", timeout=TIMEOUT, data={
            "creation_id": container, "access_token": self.token})
        return str(_json(pub).get("id"))


class TikTok:
    name = "tiktok"
    API = "https://open.tiktokapis.com/v2/post/publish/video/init/"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.token = os.environ.get("TIKTOK_ACCESS_TOKEN")

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.cfg.tiktok)

    def post(self, kind: str, rec: dict, assets: Assets) -> str:
        if kind != "video" or not assets.video_path or not assets.video_path.exists():
            raise PublishError("Kein Video vorhanden")
        art = rec["article"]
        size = assets.video_path.stat().st_size
        title = f"{art['tiktok_caption']} {_hashtags(art)}"[:2200]
        init = _json(requests.post(
            self.API, timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json; charset=UTF-8"},
            json={
                "post_info": {"title": title, "privacy_level": self.cfg.tiktok_privacy,
                              "disable_comment": False, "is_aigc": True},  # KI-Kennzeichnung
                "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                "chunk_size": size, "total_chunk_count": 1},
            }))["data"]
        put = requests.put(init["upload_url"], timeout=300, data=assets.video_path.read_bytes(), headers={
            "Content-Type": "video/mp4", "Content-Length": str(size),
            "Content-Range": f"bytes 0-{size - 1}/{size}"})
        if not put.ok:
            raise PublishError(f"TikTok-Upload HTTP {put.status_code}: {put.text[:200]}")
        return str(init["publish_id"])


def publish_pending(cfg: Config, store, public_root: Path, limit: int | None = None,
                    publishers=None, wait=wait_public) -> list[str]:
    """Postet freigegebene, noch nicht veröffentlichte Beiträge (älteste zuerst).

    Pro Plattform und Lauf höchstens `limit` Beiträge. Fehlgeschlagene Formate werden
    bis zu 3-mal in späteren Läufen erneut versucht.
    """
    publishers = publishers or [Facebook(cfg), Instagram(cfg), TikTok(cfg)]
    active = [p for p in publishers if p.enabled]
    if not active:
        log.info("Keine Social-Plattform konfiguriert.")
        return []
    formats = {"facebook": cfg.facebook, "instagram": cfg.instagram, "tiktok": cfg.tiktok}
    limit = cfg.publish_per_run if limit is None else limit
    done: list[str] = []
    posted_articles = {p.name: 0 for p in active}

    for rec in reversed(store.live()):
        media = f"{cfg.site_url}/media/{rec['id']}"
        video_path = public_root / "media" / rec["id"] / "video.mp4"
        has_video = video_path.exists()
        assets = Assets(
            article_url=f"{cfg.site_url}/a/{rec['slug']}/",
            image_url=f"{media}/card.jpg",
            video_url=f"{media}/video.mp4" if has_video else None,
            video_path=video_path if has_video else None,
        )
        published = rec.setdefault("published", {})
        attempts = rec.setdefault("attempts", {})
        changed = False
        for p in active:
            todo = [k for k in (f"{p.name}:{f}" for f in formats[p.name])
                    if k not in published and attempts.get(k, 0) < 3]
            if not todo or posted_articles[p.name] >= limit:
                continue
            posted_articles[p.name] += 1
            for key in todo:
                kind = key.split(":", 1)[1]
                try:
                    wait(assets.image_url)
                    if assets.video_url and kind in ("video", "reel"):
                        wait(assets.video_url)
                    pid = p.post(kind, rec, assets)
                    published[key] = {"id": pid, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                    done.append(f"{rec['id']} -> {key}")
                    log.info("Veröffentlicht: %s -> %s", rec["id"], key)
                except Exception as exc:  # eine Plattform darf die anderen nicht blockieren
                    attempts[key] = attempts.get(key, 0) + 1
                    log.warning("Fehler bei %s -> %s: %s", rec["id"], key, exc)
                changed = True
        if changed:
            store.save(rec)
    return done
