# DealPuls – Deals und Kaufberatung mit KI

Ein Erklärformat mit klarer Haltung statt Meldungs-Recycling. Täglich liest die Pipeline Tech-/KI-Quellen, eine
KI-Chefredaktion bündelt mehrere Quellen zu den wichtigsten Themen, ein KI-Autor schreibt daraus Erklärbeiträge mit
Einordnung (Rubriken wie *Deal-Check* und *Neuheiten-Check*), dazu Bilder und ein Video mit Stimme. **Du liest die
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

**Admin-Seite zum Freigeben (empfohlen):** Unter `https://dealpuls.de/admin/` meldest du dich mit einem Passwort an, liest die Entwürfe
und klickst auf **Freigeben** oder **Ablehnen**. Die Seite ist nicht verlinkt, nicht in der Sitemap und für Suchmaschinen gesperrt (`noindex`).
Ein kleiner Cloudflare-Worker (kostenlos) prüft das Passwort und hält den GitHub-Zugang geheim; die Admin-Seite im Browser bekommt nur eine
Sitzung, die nach 12 Stunden abläuft. Ein Klick legt eine Entscheidung in `data/decisions/` ab und startet den Workflow (Website, Video, Posts, ca. 4 Minuten).
Einrichten (einmalig, ca. 20 Minuten):
1. **GitHub-Token nur für dieses Repo:** github.com → Settings → Developer settings → Personal access tokens → *Fine-grained tokens* → Repository access: nur `News`;
   Berechtigungen **Contents: Read and write** und **Actions: Read and write**. Den Token kopierst du direkt in Schritt 2 und teilst ihn mit niemandem.
2. **Cloudflare-Worker:** Kostenloses Konto auf cloudflare.com → Workers & Pages → *Create* → neuen Worker `dealpuls-admin` anlegen, den Code aus `worker/admin.js` einfügen und deployen.
   Unter *Settings → Variables and Secrets* eintragen: als **Secret** `ADMIN_PASSWORD` (lang und zufällig, mindestens 20 Zeichen), `SESSION_SECRET` (anderer langer Zufallstext) und `GITHUB_TOKEN`;
   als normalen Text `GITHUB_REPO` (`cbinder2703-creator/News`), `GITHUB_BRANCH` (Standard-Branch des Repos) und `ALLOWED_ORIGIN` (`https://dealpuls.de`).
3. In `config.yaml` bei `admin.api_url` die Adresse des Workers eintragen (z. B. `https://dealpuls-admin.DEIN-NAME.workers.dev`), committen und pushen.
4. Einmal Actions → newsbot → *Run workflow* mit `only_decisions` = `ja` starten (erzeugt die Entwurfsliste, ohne neue Entwürfe zu schreiben). Danach erscheint `/admin/`.
Sicherheit: Alle KI-Texte werden auf der Admin-Seite nur als Text angezeigt, nie als HTML; eine Inhaltssicherheits-Regel erlaubt Verbindungen nur zum eigenen Worker.
Falsche Passwörter werden um 1,5 Sekunden verzögert; ein langes Zufallspasswort ist der eigentliche Schutz. Beiträge mit hohem Risiko (`held`) sind rot markiert und fragen vor der Freigabe nach.

**Freigabe per WhatsApp (optional, derzeit nicht nutzbar, solange Meta das Konto sperrt):** Nach jedem Lauf bekommst du pro Entwurf eine WhatsApp-Nachricht mit Titel, Teaser, Einordnung,
Quellen und Risiko und den Buttons **Freigeben** / **Ablehnen**. Ein Klick legt eine Entscheidung ab und startet den Workflow
(Website, Video und Posts, nach ca. 4 Minuten). Ohne die Einrichtung unten bleibt alles beim Freigeben über Actions.
Das ist **nicht gegen ein echtes WhatsApp-Konto getestet**; die Plattform-Angaben unten sind nach meinem Wissen (bitte gegen die aktuelle Meta-Doku prüfen).

Einrichten (einmalig, ca. 1 Stunde, plus Wartezeit auf die Genehmigung der Vorlage):
1. **Meta-App:** developers.facebook.com → App erstellen (Typ „Business“) → Produkt **WhatsApp** hinzufügen. Meta stellt eine Test-Telefonnummer bereit.
   Trage dort deine eigene Handynummer als Empfänger ein und bestätige sie per Code. Notiere die **Telefonnummer-ID** und den **App-Geheimcode** (App-Einstellungen → Allgemein).
2. **Dauerhafter Token:** Der Test-Token läuft nach 24 Stunden ab. Lege im Business-Manager (Einstellungen → Systemnutzer) einen Systemnutzer an und erzeuge einen Token
   mit `whatsapp_business_messaging` und `whatsapp_business_management`.
3. **Nachrichtenvorlage** im WhatsApp-Manager anlegen und genehmigen lassen: Name `entwurf_freigabe`, Sprache Deutsch, Kategorie Dienstprogramm, Text wie `TEMPLATE_BODY` in
   `newsbot/notify.py` (mit Beispielwerten für {{1}} bis {{5}}), dazu zwei Schaltflächen vom Typ **Schnellantwort**: „Freigeben“ und „Ablehnen“.
4. **Webhook-Empfänger:** Kostenloses Cloudflare-Konto → Workers → neuen Worker mit dem Code aus `worker/whatsapp_webhook.js` anlegen (oder `npx wrangler deploy` im Ordner `worker/`).
   Die Variablen stehen als Kommentar am Dateianfang. Sie gehören in Cloudflare als **Secret**, nicht ins Repo. Der GitHub-Token dafür ist ein *fine-grained Token nur für dieses Repo*
   mit „Contents“ und „Actions“ jeweils auf Read and write.
5. **Webhook bei Meta eintragen:** App → WhatsApp → Konfiguration → Webhook: Callback-URL = Adresse des Workers, Verifizierungs-Token = dein `VERIFY_TOKEN`, Feld **messages** abonnieren.
6. **GitHub-Secrets** setzen: `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TO` (deine Nummer mit Ländervorwahl, z. B. `49151…`).

Sicherheit: Der Worker prüft die Meta-Signatur und nimmt nur Klicks von deiner Nummer an. Entscheidungen liegen als Dateien in `data/decisions/`, so geht bei mehreren schnellen Klicks nichts verloren.
Beiträge mit hohem Risiko (`held`) sind in der Nachricht markiert; ein Klick auf „Freigeben“ gibt sie mit ausdrücklicher ID frei. Bitte lies sie vorher.
Nachrichten außerhalb des 24-Stunden-Fensters laufen über die Vorlage und können bei Meta Gebühren pro Nachricht kosten; prüfe die aktuelle Preisliste.

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

## Affiliate (Amazon, OTTO)

Standardmäßig **aus** (`affiliate.enabled: false`). Wenn aktiv, erscheint unter passenden Beiträgen ein Kasten
„Passende Produkte · Anzeige“ mit Suchlinks. Die KI liefert dafür nur neutrale Suchbegriffe (z. B. „WLAN Router“), keine Marken, Preise
oder Empfehlungen. Die Chefredaktion bevorzugt Themen mit Kaufbezug (`editorial.kaufbezug`), aber Text und Einordnung hängen nie davon ab, ob es passende Produkte gibt. Bei reinen Branchenmeldungen bleibt der Kasten leer.
Die Links entstehen erst beim Bauen der Seite; eine geänderte ID wirkt sofort überall. In den Social-Posts stehen keine Affiliate-Links.
In der Entwurfs-Zusammenfassung siehst du die Produktideen samt fertigen Links vor der Freigabe.

**Einrichten:**
1. **Amazon:** Bei PartnerNet (partnernet.amazon.de) mit deiner fertigen Website bewerben. Danach in `config.yaml` bei `programs → Amazon` deine Tracking-ID als `tag` eintragen und `enabled: true` setzen.
   Nach meinem Wissen (nicht geprüft, bitte in den Teilnahmebedingungen nachlesen): Das Konto kann geschlossen werden, wenn in den ersten 180 Tagen nicht genug qualifizierte Verkäufe zusammenkommen; Preise dürfen nur mit aktuellen Daten angezeigt werden (deshalb zeigen wir keine); der Pflichthinweis muss sichtbar sein.
2. **OTTO:** Das Partnerprogramm läuft laut OTTO über **Awin**. In Awin bei OTTO bewerben, dann `awinmid` (OTTO-Programm-ID) und `awinaffid` (deine Publisher-ID) in `link_template` eintragen und `enabled: true` setzen. Nach meinem Wissen sind das die richtigen Parameter, prüfe es mit einem Testklick im Awin-Konto. Die Suchadresse `search_url` ist ebenfalls zu prüfen.
3. Programme mit Platzhaltern (`DEINE_…`) oder fehlender ID bleiben automatisch aus, es gehen keine kaputten Links online.
4. Zuletzt `affiliate.enabled: true`.

**Rechtliches (Vorlage, keine Rechtsberatung):** Affiliate-Links müssen in Deutschland als Werbung erkennbar sein. Das Projekt setzt „Anzeige“ am Kasten und an jedem Link,
`rel="sponsored"`, den Amazon-Pflichthinweis und einen Absatz im Datenschutz. Prüfe Wortlaut und Datenschutztext rechtlich, bevor du live gehst.
Ein Kasten mit gekennzeichneten Links ist nicht dasselbe wie eine Kaufempfehlung. Wir testen keine Produkte, deshalb gibt es keine Rankings und keine „Testsieger“.
Das schützt auch deine Glaubwürdigkeit als kritisches Erklärformat.

## Kaufberater und Suchmaschinen (SEO)

- **Kaufberater** (`/kaufberater/<slug>/`): zeitlose Ratgeberseiten mit Kaufkriterien, typischen Fehlkäufen und häufigen Fragen.
  Themen und Suchbegriffe stehen in `config.yaml` unter `guides.topics`. Mit `guides.enabled: true` schreibt jeder Lauf
  höchstens `per_run` fehlende Kaufberater, immer als Entwurf (ID `kb-<slug>`), Freigabe wie bei News.
  Neue Fassung: `python -m newsbot guide <slug>`; die alte bleibt bis zur Freigabe online.
  Ohne Testsieger und Rankings, denn wir testen nichts selbst.
- **News** bekommen SEO-Titel, Meta-Beschreibung, Suchbegriff (auch in der Adresse), häufige Fragen und, wenn passend,
  einen Verweis auf den Kaufberater. Der Kaufberater listet umgekehrt die aktuellen Meldungen dazu.
- `editorial.kaufbezug: true`: Die Chefredaktion bevorzugt Themen, die Kaufentscheidungen betreffen.
- Website: Themen-Seiten (`/thema/…`), Brotkrumen-Navigation, strukturierte Daten (NewsArticle, Article, BreadcrumbList,
  WebSite), Sitemap mit Änderungsdatum, Seite „So arbeiten wir“.
- Was das nicht ersetzt: eine eigene Domain, die Google Search Console (Sitemap einreichen) und Zeit. Ein Platz ganz oben
  ist nie garantiert, und Google stuft massenhaft erzeugte Texte ohne eigenen Mehrwert ab. Deshalb die Freigabe durch dich.

## Sprecherstimme und Videos

**Derzeit aus** (`pipeline.videos_for_recent: 0`): Ohne ElevenLabs-Schlüssel wären die Videos stumm und ohne Nutzen. Zum Einschalten `videos_for_recent` z. B. auf 20 setzen und `ELEVENLABS_API_KEY` eintragen. Auf der Beitragsseite werden Videos nicht eingebettet (`editorial.show_video`).

Jedes Video hat eine KI-Sprecherstimme (ElevenLabs) und eingebrannte Untertitel, die zum gesprochenen Text passen.
Claude schreibt dafür pro Beitrag einen kurzen Sprechtext (`narration`, ca. 15–20 Sekunden).

- Secret `ELEVENLABS_API_KEY` setzen. Ohne Key entstehen stumme Folienvideos statt Videos mit Stimme.
- Stimme wählen: in der ElevenLabs-Bibliothek eine deutsche Stimme aussuchen und ihre ID in `config.yaml` unter `voice.voice_id` eintragen.
  Die voreingestellte Standardstimme ist nur ein Platzhalter; Modell und Stimme vorher mit einem deutschen Text anhören.
- Pro Beitrag wird die Aufnahme **einmal** erzeugt und in `data/audio/` gespeichert, damit spätere Läufe nicht erneut bezahlen.
  Aufnahmen älterer Beiträge, die kein Video mehr bekommen, werden automatisch gelöscht.
- Die Untertitel werden nach Zeichenanzahl auf die Sprechdauer verteilt und können deshalb leicht neben dem gesprochenen Wort liegen.
- Das Video ist als „Mit KI erstellt · KI-Stimme“ gekennzeichnet. Nutze nur Standardstimmen, keine Nachbildung echter Personen.

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
- **Kosten**: Pro Beitrag ca. 1–3 Cent API-Kosten (Schätzwert, vor dem ersten Lauf nicht gemessen; voreingestellt ist `claude-sonnet-5-5`, ein größeres Modell wie `claude-opus-5-5` kostet mehr; Modell in `config.yaml` änderbar). GitHub Actions/Pages sind für kleine Projekte kostenlos.

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
| `newsbot/guides.py` | Kaufberater: Ratgeberseiten mit SEO, als Entwurf zur Freigabe |
| `newsbot/affiliate.py` | Affiliate-Links (Amazon, OTTO/Awin) als gekennzeichneter Kasten |
| `newsbot/media.py` | Bildkarten (Pillow) und 9:16-Video (ffmpeg) |
| `newsbot/site.py` + `templates/` | statische Website, RSS-Feed, Sitemap |
| `newsbot/social.py` | Facebook-, Instagram-, TikTok-Adapter |
| `newsbot/pipeline.py`, `cli.py` | Ablauf: `generate`, `approve`, `drafts`, `build`, `publish`, `run`, `demo` |
| `data/` | Beiträge als JSON und Merkliste (wird vom Workflow committet) |
