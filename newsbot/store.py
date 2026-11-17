"""Dateibasierter Speicher (JSON), damit der Zustand im Git-Repo liegt und CI-Läufe ihn teilen."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

SEEN_LIMIT = 5000
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def slugify(text: str, max_len: int = 60) -> str:
    text = text.translate(_UMLAUTS).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len].strip("-") or "beitrag"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, data_dir: str | Path = "data"):
        self.dir = Path(data_dir)
        self.articles_dir = self.dir / "articles"
        self.articles_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir = self.dir / "audio"
        self.seen_path = self.dir / "seen.json"

    # --- gesehene Quell-URLs (verhindert doppelte Beiträge und doppelte API-Kosten)
    def seen(self) -> dict[str, str]:
        if self.seen_path.exists():
            return json.loads(self.seen_path.read_text(encoding="utf-8"))
        return {}

    def mark_seen(self, urls: list[str]) -> None:
        seen = self.seen()
        stamp = now_iso()
        for u in urls:
            seen[u] = stamp
        if len(seen) > SEEN_LIMIT:
            seen = dict(sorted(seen.items(), key=lambda kv: kv[1])[-SEEN_LIMIT:])
        self.seen_path.write_text(json.dumps(seen, indent=0, ensure_ascii=False), encoding="utf-8")

    # --- Sprachaufnahmen (einmal erzeugt und committet, damit CI-Läufe nicht erneut bezahlen)
    def audio_path(self, article_id: str) -> Path:
        return self.audio_dir / f"{article_id}.mp3"

    def prune_audio(self, keep_ids: list[str]) -> None:
        """Löscht Aufnahmen älterer Beiträge, die kein Video mehr bekommen (hält das Repo klein)."""
        keep = {f"{i}.mp3" for i in keep_ids}
        if self.audio_dir.exists():
            for p in self.audio_dir.glob("*.mp3"):
                if p.name not in keep:
                    p.unlink()

    # --- Beiträge
    def save(self, rec: dict) -> None:
        path = self.articles_dir / f"{rec['id']}.json"
        path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")

    def all(self) -> list[dict]:
        recs = [json.loads(p.read_text(encoding="utf-8")) for p in self.articles_dir.glob("*.json")]
        return sorted(recs, key=lambda r: r["created_at"], reverse=True)

    def live(self) -> list[dict]:
        return [r for r in self.all() if r.get("status") == "live"]
