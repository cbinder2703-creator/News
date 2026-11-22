"""Kaufberater: zeitlose Ratgeberseiten (z. B. "Saugroboter: worauf achten?"), die bei Google ranken sollen.

Die Themen pflegst du in config.yaml (guides.topics). Jeder Kaufberater entsteht als Entwurf und geht erst nach
deiner Freigabe online. Eine neue Fassung (python -m newsbot guide <slug>) wird ebenfalls Entwurf, die alte
Fassung bleibt bis zur Freigabe online. News-Beiträge verlinken auf den passenden Kaufberater, der Kaufberater
listet die aktuellen Meldungen dazu (interne Verlinkung, Aktualität).
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from .config import Config
from .writer import FAQ, Section, ShopIdea

log = logging.getLogger("newsbot.guides")

GUIDE_SYSTEM = """Du bist Redakteur der Marke "<<BRAND>>" (<<TAGLINE>>) und schreibst auf Deutsch einen zeitlosen Kaufberater.

Unsere Haltung:
<<HALTUNG>>

Harte Regeln:
- Wir testen keine Produkte. Deshalb: keine Testsieger, keine Rankings, keine Bestenlisten, keine Aussagen über konkrete
  Marken oder Modelle, keine Preise. Du erklärst Kriterien, Fragen und typische Fehler, damit Leser selbst entscheiden.
- Keine konkreten Zahlen aus dem Gedächtnis als Fakten (Messwerte, Marktanteile, Studien, Preise). Grobe Richtwerte nur,
  wenn sie allgemein anerkannt sind, und dann vorsichtig formuliert ("häufig", "in der Regel"). Im Zweifel weglassen.
- Keine erfundenen Erfahrungen ("wir haben ausprobiert", "in unserem Test").
- Schreibe hilfreich und konkret für Menschen ohne Vorwissen, nicht für Suchmaschinen. Kein Keyword-Stuffing.

Suchmaschinen (SEO):
- Das Suchwort lautet: "<<KEYWORD>>". Es steht natürlich in headline, seo_title (max. 60 Zeichen, Suchwort vorn),
  meta_description (120-155 Zeichen), im ersten Satz von intro und in mindestens einer Zwischenüberschrift.
- faq: 4-6 Fragen, die Leser dazu bei Google stellen, mit Antworten von 30-70 Wörtern.

Formate:
- headline: max. 70 Zeichen, z. B. "<<TITLE>>: worauf du beim Kauf achten solltest".
- intro: 2-3 Sätze (50-80 Wörter): für wen dieser Ratgeber ist und was er beantwortet.
- sections: 3-5 Abschnitte (je 80-150 Wörter), z. B. "Welche Arten gibt es?", "Für wen lohnt sich das?", "Darauf kommt es an".
- criteria: 5-7 Kaufkriterien, je name (max. 40 Zeichen) und text (40-80 Wörter): warum wichtig, worauf achten.
- mistakes: 3-5 typische Fehlkäufe in je einem Satz.
- summary: 1-2 Sätze, beginnt mit "Kurz gesagt:".
- shopping: 1-3 neutrale Suchbegriffe ohne Marken (label, query max. 4 Wörter, reason), z. B. Unterarten der Kategorie.
- image_alt: 1 Satz."""


class Criterion(BaseModel):
    name: str
    text: str


class Guide(BaseModel):
    headline: str
    seo_title: str
    meta_description: str
    intro: str
    sections: list[Section]
    criteria: list[Criterion]
    mistakes: list[str] = Field(default_factory=list)
    faq: list[FAQ] = Field(default_factory=list)
    summary: str = ""
    shopping: list[ShopIdea] = Field(default_factory=list)
    image_alt: str = ""

    def normalized(self) -> "Guide":
        def cut(s: str, n: int) -> str:
            s = s.strip()
            return s if len(s) <= n else s[: n - 1].rstrip() + "…"

        return self.model_copy(update={
            "headline": cut(self.headline, 90),
            "seo_title": cut(self.seo_title, 65),
            "meta_description": cut(self.meta_description, 160),
            "sections": [Section(heading=cut(x.heading, 70), text=x.text.strip()) for x in self.sections[:6] if x.text.strip()],
            "criteria": [Criterion(name=cut(c.name, 50), text=c.text.strip()) for c in self.criteria[:8] if c.text.strip()],
            "mistakes": [cut(m, 200) for m in self.mistakes[:5] if m.strip()],
            "faq": [FAQ(question=cut(f.question, 120), answer=cut(f.answer, 700)) for f in self.faq[:6]
                    if f.question.strip() and f.answer.strip()],
            "summary": cut(self.summary, 400),
            "shopping": [ShopIdea(label=cut(x.label, 60), query=cut(x.query, 60), reason=cut(x.reason, 140))
                         for x in self.shopping[:3] if x.query.strip()],
        })


def guide_id(slug: str) -> str:
    return f"kb-{slug}"


class GuideWriter:
    def __init__(self, cfg: Config):
        import anthropic

        self.client = anthropic.Anthropic()
        self.cfg = cfg

    def write(self, topic: dict) -> Guide | None:
        import anthropic

        system = (GUIDE_SYSTEM.replace("<<BRAND>>", self.cfg.brand_name).replace("<<TAGLINE>>", self.cfg.tagline)
                  .replace("<<HALTUNG>>", self.cfg.haltung or "Sachlich und verständlich.")
                  .replace("<<KEYWORD>>", topic.get("keyword") or topic["title"]).replace("<<TITLE>>", topic["title"]))
        prompt = f"Schreibe den Kaufberater: {topic['title']}"
        if topic.get("hinweis"):
            prompt += f"\nHinweis der Redaktion: {topic['hinweis']}"
        try:
            resp = self.client.messages.parse(
                model=self.cfg.model, max_tokens=8000, system=system,
                messages=[{"role": "user", "content": prompt}], output_format=Guide)
        except anthropic.APIError as exc:
            log.warning("Kaufberater %s fehlgeschlagen: %s", topic["slug"], exc)
            return None
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            log.warning("Kaufberater %s ohne verwertbare Antwort (stop_reason=%s)", topic["slug"], resp.stop_reason)
            return None
        return resp.parsed_output.normalized()


class StubGuideWriter:
    """Offline-Ersatz für Demo und Tests."""

    def write(self, topic: dict) -> Guide:
        t, kw = topic["title"], topic.get("keyword") or topic["title"]
        return Guide(
            headline=f"{t}: worauf du beim Kauf achten solltest",
            seo_title=f"{kw}: Kaufberatung"[:60],
            meta_description=f"{kw}: Diese Kriterien zählen beim Kauf, typische Fehler und Antworten auf häufige Fragen.",
            intro=f"Du willst {t} kaufen? Hier steht in der echten Version eine Einleitung.",
            sections=[Section(heading=f"Welche Arten von {t} gibt es?", text="Platzhalter für die Erklärung."),
                      Section(heading="Für wen lohnt sich das?", text="Platzhalter.")],
            criteria=[Criterion(name="Erstes Kriterium", text="Platzhalter."),
                      Criterion(name="Zweites Kriterium", text="Platzhalter.")],
            mistakes=["Nur auf den Preis schauen."],
            faq=[FAQ(question=f"Lohnt sich {t}?", answer="Platzhalter-Antwort.")],
            summary="Kurz gesagt: Platzhalter.",
            shopping=[ShopIdea(label=t, query=kw, reason="Wenn du dich umsehen willst")],
            image_alt=f"Textkarte: Kaufberater {t}",
        ).normalized()
