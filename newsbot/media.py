"""Bilder (Pillow) und Kurzvideos (ffmpeg) aus den Beitragstexten erzeugen.

Bewusst ohne fremde Fotos: Quellbilder sind urheberrechtlich geschützt. Die Karten sind
reines Typografie-Design in Markenfarben. Eigene KI-Bilder lassen sich später an
`render_card` anbinden.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("newsbot.media")

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
PALETTES = [  # (oben, unten)
    ("#1b1f3b", "#3a2e8a"),
    ("#0f2a43", "#0e6e6e"),
    ("#2b1030", "#a3245a"),
    ("#1d2b1a", "#3c7a3a"),
    ("#2a1a0f", "#b3541e"),
]

CARD_SIZE = (1080, 1350)   # Instagram 4:5
STORY_SIZE = (1080, 1920)  # Reels / TikTok 9:16
OG_SIZE = (1200, 630)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def palette_for(category: str) -> tuple[str, str]:
    return PALETTES[zlib.crc32(category.encode()) % len(PALETTES)]


def _gradient(size: tuple[int, int], top: str, bottom: str) -> Image.Image:
    w, h = size
    t, b = _hex(top), _hex(bottom)
    img = Image.new("RGB", size)
    px = ImageDraw.Draw(img)
    for y in range(h):
        k = y / max(h - 1, 1)
        px.line([(0, y), (w, y)], fill=tuple(int(t[i] + (b[i] - t[i]) * k) for i in range(3)))
    return img


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def render_card(
    size: tuple[int, int],
    text: str,
    kicker: str,
    footer: str,
    brand: str,
    accent: str,
    category: str,
    big: bool = True,
) -> Image.Image:
    """Eine Textkarte; die Schrift wird so lange verkleinert, bis der Text passt."""
    w, h = size
    img = _gradient(size, *palette_for(category))
    d = ImageDraw.Draw(img)
    margin = int(w * 0.08)
    max_w = w - 2 * margin

    # Markenleiste
    d.rectangle([margin, margin, margin + 14, margin + 64], fill=accent)
    d.text((margin + 34, margin + 6), brand.upper(), font=_font(int(w * 0.04)), fill="white")
    d.text((margin, margin + 110), kicker.upper(), font=_font(int(w * 0.03)), fill=accent)

    # Haupttext: Größe suchen
    area_top, area_bottom = margin + 190, h - margin - 140
    start = int(w * (0.085 if big else 0.07))
    for fsize in range(start, 28, -4):
        font = _font(fsize)
        lines = _wrap(d, text, font, max_w)
        line_h = int(fsize * 1.22)
        if len(lines) * line_h <= area_bottom - area_top:
            break
    y = area_top + (area_bottom - area_top - len(lines) * line_h) // 2
    for ln in lines:
        d.text((margin, y), ln, font=font, fill="white")
        y += line_h

    # Fußzeile
    d.line([(margin, h - margin - 100), (w - margin, h - margin - 100)], fill=(255, 255, 255, 90), width=2)
    d.text((margin, h - margin - 80), footer, font=_font(int(w * 0.028)), fill=(225, 225, 235))
    return img


def source_label(rec: dict) -> str:
    names = list(dict.fromkeys(x["name"] for x in (rec.get("sources") or [rec["source"]])))[:3]
    return ("Quelle: " if len(names) == 1 else "Quellen: ") + ", ".join(names)


def footer_line(rec: dict, show_sources: bool, extra: str = "") -> str:
    """Fußzeile der Bildkarten und Videos; die Quellenangabe nur, wenn die Seite Quellen öffentlich zeigt."""
    parts = ([source_label(rec)] if show_sources else []) + ["Mit KI erstellt"] + ([extra] if extra else [])
    return "  ·  ".join(parts)


def make_cards(headline: str, kicker: str, footer: str, brand: str, accent: str, category: str,
               out_dir: Path) -> dict[str, Path]:
    """card.jpg (Feed), og.jpg (Link-Vorschau). JPEG, weil Instagram nur JPEG akzeptiert."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, size in (("card", CARD_SIZE), ("og", OG_SIZE)):
        img = render_card(size, headline, kicker, footer, brand, accent, category)
        paths[name] = out_dir / f"{name}.jpg"
        img.save(paths[name], "JPEG", quality=92)
    return paths


def make_images(rec: dict, brand: str, accent: str, out_dir: Path, show_sources: bool = True) -> dict[str, Path]:
    art = rec["article"]
    return make_cards(art["headline"], art.get("rubrik") or art["category"], footer_line(rec, show_sources),
                      brand, accent, art["category"], out_dir)


def make_video(rec: dict, brand: str, accent: str, host: str, out_path: Path, seconds: float = 3.5,
               show_sources: bool = True) -> Path | None:
    """Hochkant-Video 1080x1920 (H.264/AAC): Schlagzeile, Kernaussagen, Abbinder."""
    if not shutil.which("ffmpeg"):
        log.warning("ffmpeg fehlt, Video wird übersprungen")
        return None
    art = rec["article"]
    footer = footer_line(rec, show_sources)
    texts = [(art["headline"], art.get("rubrik") or art["category"])]
    texts += [(s, "Kurz erklärt") for s in art["video_slides"]]
    texts += [(f"Mehr auf {host}", brand)]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        filters = []
        for i, (text, kicker) in enumerate(texts):
            png = Path(tmp) / f"s{i}.png"
            render_card(STORY_SIZE, text, kicker, footer, brand, accent, art["category"], big=(i == 0)).save(png)
            cmd += ["-loop", "1", "-t", str(seconds), "-i", str(png)]
            filters.append(
                f"[{i}:v]fade=t=in:st=0:d=0.3,fade=t=out:st={seconds - 0.3}:d=0.3,setsar=1,fps=30[v{i}]"
            )
        n = len(texts)
        concat = "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        cmd += [
            "-filter_complex", ";".join(filters + [concat]),
            "-map", "[v]", "-map", f"{n}:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(out_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=180)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            log.warning("ffmpeg fehlgeschlagen: %s", getattr(exc, "stderr", exc))
            return None
    return out_path


# ---------------------------------------------------------------- Video mit Sprecherstimme

def split_captions(text: str, max_chars: int = 30) -> list[str]:
    """Teilt den gesprochenen Text in kurze, gut lesbare Untertitel (bevorzugt an Satzzeichen)."""
    words = re.sub(r"\s+", " ", text).strip().split(" ")
    chunks: list[str] = []
    cur = ""
    for w in filter(None, words):
        trial = f"{cur} {w}".strip()
        if cur and len(trial) > max_chars:
            chunks.append(cur)
            cur = w
        else:
            cur = trial
        if re.search(r"[.!?:;,]$", cur) and len(cur) >= 14:
            chunks.append(cur)
            cur = ""
    if cur:
        chunks.append(cur)
    return chunks


def caption_durations(chunks: list[str], total: float, min_len: float = 0.7) -> list[float]:
    """Verteilt die Audiolänge nach Zeichenanzahl auf die Untertitel (Näherung ohne Wort-Zeitstempel)."""
    weights = [max(len(c), 1) for c in chunks]
    raw = [total * w / sum(weights) for w in weights]
    durs = [max(d, min_len) for d in raw]
    scale = total / sum(durs)
    return [d * scale for d in durs] if scale < 1 else durs


def audio_duration(path: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            check=True, capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out)
    except (subprocess.SubprocessError, ValueError):
        return None


def render_caption_frame(size, headline: str, caption: str, footer: str, brand: str,
                         accent: str, category: str, kicker: str = "") -> Image.Image:
    """Hintergrund + kleine Schlagzeile oben + großer Untertitel unten (wie bei TikTok/Reels üblich)."""
    w, h = size
    img = _gradient(size, *palette_for(category))
    d = ImageDraw.Draw(img)
    m = int(w * 0.08)
    d.rectangle([m, m, m + 14, m + 64], fill=accent)
    d.text((m + 34, m + 6), brand.upper(), font=_font(int(w * 0.04)), fill="white")
    d.text((m, m + 110), (kicker or category).upper(), font=_font(int(w * 0.03)), fill=accent)

    # Schlagzeile klein (max. 4 Zeilen)
    for fs in range(int(w * 0.055), 24, -2):
        f = _font(fs)
        lines = _wrap(d, headline, f, w - 2 * m)
        if len(lines) <= 4:
            break
    y = m + 190
    for ln in lines:
        d.text((m, y), ln, font=f, fill=(215, 218, 235))
        y += int(fs * 1.25)

    # Untertitel groß, mittig im unteren Drittel, auf halbtransparentem Kasten
    box_top, box_bottom = int(h * 0.55), int(h * 0.80)
    for fs in range(int(w * 0.082), 30, -3):
        f = _font(fs)
        cl = _wrap(d, caption, f, w - 2 * m - 40)
        lh = int(fs * 1.25)
        if len(cl) * lh <= box_bottom - box_top - 40:
            break
    th = len(cl) * lh
    top = box_top + (box_bottom - box_top - th) // 2
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(
        [m - 10, top - 24, w - m + 10, top + th + 24], radius=28, fill=(0, 0, 0, 120))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    d = ImageDraw.Draw(img)
    for ln in cl:
        tw = d.textlength(ln, font=f)
        d.text(((w - tw) / 2, top), ln, font=f, fill="white")
        top += lh

    d.line([(m, h - m - 100), (w - m, h - m - 100)], fill=(255, 255, 255), width=2)
    d.text((m, h - m - 80), footer, font=_font(int(w * 0.028)), fill=(225, 225, 235))
    return img


def make_narrated_video(rec: dict, brand: str, accent: str, host: str, audio: Path,
                        out_path: Path, end_card: float = 1.8, show_sources: bool = True) -> Path | None:
    """9:16-Video: Sprecherstimme + eingebrannte Untertitel, Länge richtet sich nach der Aufnahme."""
    if not shutil.which("ffmpeg"):
        log.warning("ffmpeg fehlt, Video wird übersprungen")
        return None
    art = rec["article"]
    total = audio_duration(audio)
    text = art.get("narration") or ""
    if not total or not text.strip():
        return None
    footer = footer_line(rec, show_sources, "KI-Stimme")
    chunks = split_captions(text)
    durs = caption_durations(chunks, total)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        lines = []
        for i, (chunk, dur) in enumerate(zip(chunks, durs)):
            png = tmp_p / f"c{i}.png"
            render_caption_frame(STORY_SIZE, art["headline"], chunk, footer, brand, accent,
                                 art["category"], art.get("rubrik", "")).save(png)
            lines += [f"file '{png}'", f"duration {dur:.3f}"]
        end = tmp_p / "end.png"
        render_card(STORY_SIZE, f"Mehr auf {host}", brand, footer, brand, accent, art["category"]).save(end)
        lines += [f"file '{end}'", f"duration {end_card:.3f}", f"file '{end}'"]  # letzte Zeile: Konvention des concat-Demuxers
        listing = tmp_p / "frames.txt"
        listing.write_text("\n".join(lines), encoding="utf-8")

        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(audio),
               "-vf", "fps=30,format=yuv420p", "-af", "apad",
               "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-b:a", "128k",
               # -t: feste Länge, weil neuere ffmpeg-Versionen (ab ca. 8) dem letzten concat-Eintrag
               # erneut die Abbinder-Dauer geben und das Video sonst um end_card zu lang wird.
               "-shortest", "-t", f"{total + end_card:.3f}", "-movflags", "+faststart", str(out_path)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=240)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            log.warning("ffmpeg (Sprecher-Video) fehlgeschlagen: %s", getattr(exc, "stderr", exc))
            return None
    return out_path
