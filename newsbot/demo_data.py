from datetime import datetime, timedelta, timezone

from .ingest import SourceItem


def demo_items() -> list[SourceItem]:
    now = datetime.now(timezone.utc)
    rows = [
        ("Neues Sprachmodell schlägt Konkurrenz in Benchmarks",
         "Ein Entwicklerteam stellt ein neues Sprachmodell vor, das in mehreren Tests besser abschneidet als bisherige Modelle.", "THE DECODER"),
        ("Chiphersteller kündigt Grafikkarten mit mehr Speicher an",
         "Die neue Generation soll deutlich mehr Videospeicher bieten und im Frühjahr in den Handel kommen.", "heise online"),
        ("Sicherheitslücke in beliebtem Router-Betriebssystem geschlossen",
         "Ein Update behebt eine Schwachstelle, die Angreifern Zugriff auf Heimnetzwerke ermöglichen konnte.", "Golem.de"),
        ("Messenger-Dienst führt Kanäle für Unternehmen ein",
         "Unternehmen können künftig Neuigkeiten an Abonnenten verteilen, ohne Telefonnummern zu sammeln.", "t3n"),
    ]
    return [
        SourceItem(t, s, f"https://example.com/demo/{i}", src, now - timedelta(hours=i + 1))
        for i, (t, s, src) in enumerate(rows)
    ]
