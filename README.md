# TechPuls – automatische KI-Nachrichtenmarke

Ein Erklärformat mit klarer Haltung statt Meldungs-Recycling. Täglich liest die Pipeline Tech-/KI-Quellen, eine
KI-Chefredaktion bündelt mehrere Quellen zu den wichtigsten Themen, ein KI-Autor schreibt daraus Erklärbeiträge mit
Einordnung (Rubriken wie *Hype-Check* und *Was steckt dahinter?*), dazu Bilder und ein Video mit Stimme. **Du liest die
Entwürfe (wenige Minuten) und gibst sie frei**, erst dann gehen Website, Instagram, Facebook und TikTok online.
Haltung, Rubriken, Schwerpunkte und Marke stehen in `config.yaml` (Abschnitt `editorial`). Das ist dein Hebel.

```
RSS-Quellen → Chefredaktion bündelt Themen → Autor schreibt Erklärbeitrag mit Einordnung → Entwurf
→ DU gibst frei → Stimme + Video → Website (GitHub Pages) → Facebook / Instagram / TikTok
```

### Dein täglicher Ablauf (ca. 5 Minuten)
1. Der Workflow läuft morgens und legt Entwürfe an. Die Zusammenfassung des Laufs (Actions → Lauf öffnen) zeigt sie lesbar mit ID, Rubrik, Risiko und allen Quellen.
2. Lies sie. Gefällt dir einer, starte Actions → newsbot → **Run workflow** und trage ins Feld `approve` die ID(s) ein (mehrere mit Komma) oder `alle`.
3. Der Workflow gibt frei, erzeugt Stimme und Video, baut die Website und postet. Nicht freigegebene Entwürfe bleiben liegen und gehen nie online.
4. Beiträge mit hohem Risiko (`held`) lassen sich nur mit ausdrücklicher ID freigeben, nie mit `alle`.

Ohne Freigabe laufen lassen: `editorial.mode: auto`. Das empfehle ich nicht, denn gerade die Haltung und die Einordnung sind der Teil, den du prüfen solltest.

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

## Sprecherstimme und Videos

Jedes Video hat eine KI-Sprecherstimme (ElevenLabs) und eingebrannte Untertitel, die zum gesprochenen Text passen.
Claude schreibt dafür pro Beitrag einen kurzen Sprechtext (`narration`, ca. 15–20 Sekunden).

- Secret `ELEVENLABS_API_KEY` setzen. Ohne Key entstehen stumme Folienvideos statt Videos mit Stimme.
- Stimme wählen: in der ElevenLabs-Bibliothek eine deutsche Stimme aussuchen und ihre ID in `config.yaml` unter `voice.voice_id` eintragen.
  Die voreingestellte Standardstimme ist nur ein Platzhalter; Modell und Stimme vorher mit einem deutschen Text anhören.
- Pro Beitrag wird die Aufnahme **einmal** erzeugt und in `data/audio/` gespeichert, damit spätere Läufe nicht erneut bezahlen.
  Aufnahmen älterer Beiträge, die kein Video mehr bekommen, werden automatisch gelöscht.
- Die Untertitel werden nach Zeichenanzahl auf die Sprechdauer verteilt und können deshalb leicht neben dem gesprochenen Wort liegen.
- Das Video ist als „KI-generiert · KI-Stimme“ gekennzeichnet. Nutze nur Standardstimmen, keine Nachbildung echter Personen.

## Bilder

Es werden **keine Fotos aus dem Internet** verwendet, nur selbst erzeugte Typografie-Karten. Quellfotos sind urheberrechtlich geschützt.

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

- **Nur Fakten aus den Quellen**: Die KI bekommt Titel + Teaser und darf nichts dazuerfinden. Wertungen stehen nur im gekennzeichneten Feld „Einordnung“. Jeder Beitrag nennt und verlinkt alle Quellen.
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
- Webrecherche der KI zur Faktenprüfung, Newsletter, Wochenrückblick als eigenes Format
- Eigene Domain statt `github.io`

## Projektstruktur

| Datei | Aufgabe |
|---|---|
| `newsbot/ingest.py` | RSS lesen, bereinigen, Dubletten filtern |
| `newsbot/editor.py` | KI-Chefredaktion: Themen wählen, Quellen bündeln |
| `newsbot/writer.py` | KI-Autor: Erklärbeitrag, Einordnung, Risiko, Social-Texte |
| `newsbot/media.py` | Bildkarten (Pillow) und 9:16-Video (ffmpeg) |
| `newsbot/site.py` + `templates/` | statische Website, RSS-Feed, Sitemap |
| `newsbot/social.py` | Facebook-, Instagram-, TikTok-Adapter |
| `newsbot/pipeline.py`, `cli.py` | Ablauf: `generate`, `approve`, `drafts`, `build`, `publish`, `run`, `demo` |
| `data/` | Beiträge als JSON und Merkliste (wird vom Workflow committet) |
