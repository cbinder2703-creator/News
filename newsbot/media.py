"""Bilder (Pillow) und Kurzvideos (ffmpeg) aus den Beitragstexten erzeugen.

Bewusst ohne fremde Fotos: Quellbilder sind urheberrechtlich geschützt. Die Karten sind
reines Typografie-Design in Markenfarben. Eigene KI-Bilder lassen sich später an
`render_card` anbinden.
"""
from __future__ import annotations

import logging
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


def make_images(rec: dict, brand: str, accent: str, out_dir: Path) -> dict[str, Path]:
    """card.jpg (Feed), og.jpg (Link-Vorschau). JPEG, weil Instagram nur JPEG akzeptiert."""
    art = rec["article"]
    out_dir.mkdir(parents=True, exist_ok=True)
    footer = f"Quelle: {rec['source']['name']}  ·  KI-generiert"
    paths = {}
    for name, size in (("card", CARD_SIZE), ("og", OG_SIZE)):
        img = render_card(size, art["headline"], art["category"], footer, brand, accent, art["category"])
        paths[name] = out_dir / f"{name}.jpg"
        img.save(paths[name], "JPEG", quality=92)
    return paths


def make_video(rec: dict, brand: str, accent: str, host: str, out_path: Path, seconds: float = 3.5) -> Path | None:
    """Hochkant-Video 1080x1920 (H.264/AAC): Schlagzeile, Kernaussagen, Abbinder."""
    if not shutil.which("ffmpeg"):
        log.warning("ffmpeg fehlt, Video wird übersprungen")
        return None
    art = rec["article"]
    footer = f"Quelle: {rec['source']['name']}  ·  KI-generiert"
    texts = [(art["headline"], art["category"])]
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
