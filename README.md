# TechPuls – automatische KI-Nachrichtenmarke

Eine Pipeline, die alle paar Stunden aktuelle Meldungen aus Tech-/KI-Quellen liest, mit Claude daraus eigene
Kurzbeiträge schreibt, Bilder und ein Kurzvideo erzeugt und alles automatisch auf **Website, Instagram,
Facebook und TikTok** veröffentlicht. Marke, Themen und Quellen stehen in `config.yaml`.

```
RSS-Quellen → Claude schreibt Beitrag + Social-Texte → Bildkarte + 9:16-Video
            → Website (GitHub Pages) → Facebook / Instagram / TikTok
```

## Sofort ausprobieren (ohne Keys)

```bash
pip install -r requirements.txt      # außerdem: ffmpeg installieren
python -m newsbot demo               # baut eine Demo-Website nach .demo/public
python -m http.server 8000 --directory .demo/public
python -m pytest                     # Tests
```

## In Betrieb nehmen

1. **Repo auf GitHub, Pages aktivieren**: Settings → Pages → Source „GitHub Actions“.
2. **`config.yaml` anpassen**: Markenname, `site_url` (`https://<user>.github.io/<repo>`), Kontakt-E-Mail, Quellen.
3. **Secret `ANTHROPIC_API_KEY`** setzen (Settings → Secrets → Actions). Danach läuft der Workflow
   `.github/workflows/newsbot.yml` alle 2 Stunden (oder manuell: Actions → newsbot → Run workflow).
   Ohne Social-Secrets entstehen zunächst nur die Website-Beiträge.
4. **Impressum und Datenschutz ausfüllen** (`newsbot/templates/impressum.html`, `datenschutz.html`).
   Das sind Vorlagen, keine Rechtsberatung.
5. **Social-Kanäle anbinden** (je ein Secret-Satz, siehe `.env.example`), siehe unten.
   Das kann parallel zum Website-Betrieb laufen; die Freigaben der Plattformen dauern Tage bis Wochen.

## Social-Kanäle

| Plattform | Was du brauchst | Hürden |
|---|---|---|
| **Facebook** | Facebook-Seite, Meta-Developer-App, Seiten-Token mit `pages_manage_posts` | Für Posts auf eigene Seite oft schon im Dev-Modus mit eigenem Konto möglich |
| **Instagram** | Business-/Creator-Konto, mit der Facebook-Seite verknüpft, Berechtigung `instagram_content_publish` | Meta **App Review** für den Live-Modus; Reels brauchen öffentlich erreichbare Video-URL (kommt von der Website) |
| **TikTok** | TikTok-Developer-App mit *Content Posting API* | Bis zum **TikTok-Audit** sind Posts nur privat sichtbar (`tiktok_privacy: SELF_ONLY`). Erst nach Freigabe auf `PUBLIC_TO_EVERYONE` stellen |

Die Adapter in `newsbot/social.py` folgen den offiziellen API-Dokus, wurden aber **nicht gegen echte Konten
getestet**. Teste jeden Kanal zuerst mit einem Testkonto und prüfe die Felder gegen die aktuelle
Plattform-Doku (Versionsnummer der Graph API: `social.graph_version`).

## Was die Automatik absichert (auch ohne manuelle Freigabe)

- **Nur Fakten aus der Quelle**: Die KI bekommt Titel + Teaser und darf nichts dazuerfinden. Jede Meldung nennt und verlinkt ihre Quelle.
- **Risiko-Sperre**: Die KI stuft jeden Beitrag ein. Themen wie Straftaten, Vorwürfe gegen Personen, Gesundheit,
  Wahlen oder Gerüchte (`risk: high`) werden **nie automatisch veröffentlicht** (Status `held` in `data/articles/`).
- **KI-Kennzeichnung** auf jeder Seite, in der Instagram-Caption und per `is_aigc`-Flag bei TikTok.
  In der Meta-App zusätzlich die Kennzeichnung „KI-Info“ nutzen, wo sie angeboten wird.
- **Keine fremden Bilder**: Grafiken sind eigenes Typografie-Design, keine Quellfotos (Urheberrecht).
- **Kein Doppelposten, kein Spam**: gesehene Quellen werden gemerkt, pro Lauf und Plattform gibt es ein Limit
  (`publish_per_run`), fehlgeschlagene Posts werden höchstens 3-mal wiederholt.
- **Kill-Switch**: Workflow in GitHub deaktivieren, oder `max_auto_risk: low` setzen.

## Rechtliches und Risiken, die du kennen solltest

- **Impressum / Verantwortlicher**: Als redaktionelles Angebot in Deutschland brauchst du ein vollständiges Impressum
  und eine inhaltlich verantwortliche Person (§ 5 DDG, § 18 MStV). Du haftest für die automatisch erzeugten Inhalte wie für eigene.
- **Fehlmeldungen**: Auch mit Absicherung kann die KI Meldungen verkürzt oder falsch wiedergeben. Plane ein, Beiträge schnell
  zu korrigieren; die Kontaktadresse steht im Footer.
- **Quellen-Bedingungen**: Prüfe die Nutzungsbedingungen der RSS-Feeds in `config.yaml`; manche Verlage untersagen
  eine kommerzielle Weiterverwendung. Im Zweifel um Erlaubnis fragen oder Quellen mit freier Lizenz wählen.
- **Plattform-Regeln**: Meta und TikTok drosseln oder sperren Konten, die reinen automatisierten, unoriginellen Content
  posten. Kennzeichne KI-Inhalte, poste nicht übermäßig oft und beobachte die Reichweite in den ersten Wochen.
- **Kosten**: Pro Beitrag ca. 1–3 Cent API-Kosten (bei `claude-opus-5-5`; Modell in `config.yaml` änderbar). GitHub Actions/Pages sind für kleine Projekte kostenlos.

## Ausbauideen

- Eigene KI-Bilder (Bildgenerator-Anbindung in `media.render_card`) und Sprecher-Stimme per TTS im Video
- Zusammenfassung mehrerer Quellen zu einem Thema, Themen-Rubriken und Newsletter
- Freigabe per Klick (Entwürfe in `held` prüfen) für sensible Themen
- Eigene Domain statt `github.io`

## Projektstruktur

| Datei | Aufgabe |
|---|---|
| `newsbot/ingest.py` | RSS lesen, bereinigen, Dubletten filtern |
| `newsbot/writer.py` | Claude-Redaktion (Beitrag, Risiko, Social-Texte) |
| `newsbot/media.py` | Bildkarten (Pillow) und 9:16-Video (ffmpeg) |
| `newsbot/site.py` + `templates/` | statische Website, RSS-Feed, Sitemap |
| `newsbot/social.py` | Facebook-, Instagram-, TikTok-Adapter |
| `newsbot/pipeline.py`, `cli.py` | Ablauf: `generate`, `build`, `publish`, `run`, `demo` |
| `data/` | Beiträge als JSON und Merkliste (wird vom Workflow committet) |
