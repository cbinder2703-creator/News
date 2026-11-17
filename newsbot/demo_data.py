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


def fake_synth(text: str, voice_id: str = "", model_id: str = "") -> bytes:
    """Platzhalter-Stimme für Demo und Tests: Stille mit der ungefähren Länge gesprochenen Textes (kein API-Key nötig)."""
    import subprocess
    import tempfile
    from pathlib import Path

    seconds = max(len(text) / 15.0, 1.0)  # ca. 15 Zeichen pro Sekunde Sprechtempo
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "a.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
             "anullsrc=channel_layout=mono:sample_rate=44100", "-t", f"{seconds:.2f}",
             "-c:a", "libmp3lame", "-b:a", "64k", str(out)],
            check=True, capture_output=True)
        return out.read_bytes()
