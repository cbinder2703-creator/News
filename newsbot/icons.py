"""Symbole für die Titelbilder der Beiträge: eigene, einfache Vektorgrafiken (keine Fotos, keine Lizenzfragen).

Die KI wählt im selben Aufruf, der den Text schreibt, ein Symbol aus ICONS. Fehlt die Angabe oder passt sie nicht,
wählt `pick_icon` eines per Stichwort. Gezeichnet wird als Inline-SVG: scharf auf jedem Bildschirm, kein Bildabruf.
"""
from __future__ import annotations

import re
import zlib

from markupsafe import Markup

# viewBox 0 0 64 64; Linien: weiß, 3 px, runde Enden (siehe .thumb svg in style.css)
ICONS: dict[str, str] = {
    "solar": ('<path d="M9 47 17 25h38l-8 22z"/><path d="m13 36h37M29 25l-4 22M42 25l-3 22"/>'
              '<circle cx="14" cy="13" r="5"/><path d="M14 3v2M4 13h2M7 6l1.5 1.5M21 6l-1.5 1.5"/><path d="M32 47v9M24 56h16"/>'),
    "router": ('<rect x="9" y="38" width="46" height="14" rx="4"/><path d="M19 38V22M45 38V22"/>'
               '<circle cx="19" cy="45" r="1.6"/><circle cx="27" cy="45" r="1.6"/>'
               '<path d="M25 18a10 10 0 0 1 14 0M28.5 22a5 5 0 0 1 7 0"/>'),
    "phone": '<rect x="19" y="6" width="26" height="52" rx="6"/><path d="M28 12h8"/><circle cx="32" cy="50" r="2"/>',
    "tablet": '<rect x="12" y="8" width="40" height="48" rx="5"/><circle cx="32" cy="50" r="2"/><path d="M24 15h16"/>',
    "laptop": '<rect x="13" y="15" width="38" height="26" rx="3"/><path d="M6 49h52l-4-8H10z"/>',
    "speaker": ('<rect x="19" y="6" width="26" height="52" rx="9"/><circle cx="32" cy="42" r="8"/>'
                '<circle cx="32" cy="42" r="2"/><circle cx="32" cy="18" r="3"/>'),
    "vacuum": ('<circle cx="32" cy="32" r="23"/><circle cx="32" cy="32" r="8"/><path d="M32 9v7M15 20l5 4M49 20l-5 4"/>'),
    "powerbank": '<rect x="17" y="6" width="30" height="52" rx="6"/><path d="M34 19 26 34h7l-3 12 10-16h-7z"/>',
    "headphones": ('<path d="M12 38v-6a20 20 0 0 1 40 0v6"/><rect x="8" y="37" width="11" height="17" rx="4"/>'
                   '<rect x="45" y="37" width="11" height="17" rx="4"/>'),
    "tv": '<rect x="6" y="12" width="52" height="34" rx="4"/><path d="M22 56h20M32 46v10"/>',
    "camera": ('<rect x="7" y="20" width="50" height="34" rx="6"/><circle cx="32" cy="37" r="10"/>'
               '<path d="m21 20 3-7h16l3 7"/>'),
    "gamepad": ('<rect x="6" y="20" width="52" height="28" rx="14"/><path d="M20 28v12M14 34h12"/>'
                '<circle cx="42" cy="31" r="2"/><circle cx="48" cy="37" r="2"/>'),
    "watch": ('<rect x="17" y="16" width="30" height="32" rx="9"/><path d="m24 16 2-10h12l2 10M24 48l2 10h12l2-10"/>'
              '<path d="M32 26v7l5 3"/>'),
    "chip": ('<rect x="17" y="17" width="30" height="30" rx="4"/><rect x="25" y="25" width="14" height="14" rx="2"/>'
             '<path d="M25 7v10M32 7v10M39 7v10M25 47v10M32 47v10M39 47v10M7 25h10M7 32h10M7 39h10M47 25h10M47 32h10M47 39h10"/>'),
    "home": ('<path d="M8 31 32 9l24 22"/><path d="M14 27v26h36V27"/><path d="M26 53V40a6 6 0 0 1 12 0v13"/>'),
    "car": ('<path d="M7 40v-7l6-12h38l6 12v7z"/><circle cx="19" cy="44" r="5"/><circle cx="45" cy="44" r="5"/>'
            '<path d="M14 33h36"/>'),
    "coffee": ('<path d="M12 24h32v14a12 12 0 0 1-12 12h-8A12 12 0 0 1 12 38z"/><path d="M44 28h4a6 6 0 0 1 0 12h-4"/>'
               '<path d="M20 8c-3 4 3 6 0 10M30 8c-3 4 3 6 0 10"/>'),
    "bulb": ('<path d="M32 6a16 16 0 0 1 9 29v6H23v-6A16 16 0 0 1 32 6z"/><path d="M25 48h14M28 54h8"/>'),
    "shield": '<path d="M32 6 50 12v18c0 13-8 21-18 27C22 51 14 43 14 30V12z"/><path d="m24 31 6 6 11-13"/>',
    "cloud": '<path d="M20 48a11 11 0 0 1-2-22 15 15 0 0 1 28-3 12 12 0 0 1 2 25z"/>',
    "tag": '<path d="M8 32 32 8h24v24L32 56z"/><circle cx="44" cy="20" r="3.5"/>',
}

# (Symbol, ganze Wörter, Wortanfänge). Reihenfolge = Vorrang: Produkte vor allgemeinen Themen.
_RULES: list[tuple[str, set[str], tuple[str, ...]]] = [
    ("solar", set(), ("balkonkraft", "solar", "photovolt", "wechselricht")),
    ("vacuum", set(), ("saugrobot", "staubsaug", "wischrobot", "mähroboter", "roboter")),
    ("powerbank", {"usb", "akku"}, ("powerbank", "ladegerät", "ladekabel", "netzteil", "akkupack")),
    ("headphones", set(), ("kopfhör", "earbud", "airpod", "headset", "in-ear")),
    ("speaker", set(), ("lautsprech", "speaker", "assistant", "alexa", "soundbar", "sprachassist", "homepod")),
    ("tv", {"tv"}, ("fernseh", "oled", "monitor", "bildschirm", "beamer")),
    ("camera", set(), ("kamera", "webcam", "dashcam", "gopro", "fotograf")),
    ("gamepad", {"ps5", "xbox"}, ("gaming", "konsole", "playstation", "nintendo", "controller", "spiele")),
    ("watch", set(), ("smartwatch", "fitness", "tracker", "garmin", "uhr")),
    ("tablet", {"ipad"}, ("tablet", "e-reader", "kindle")),
    ("phone", set(), ("smartphone", "handy", "iphone", "galaxy", "pixel", "telefon")),
    ("laptop", {"pc"}, ("laptop", "notebook", "macbook", "computer", "chromebook")),
    ("chip", {"gpu", "cpu", "ssd", "ram"}, ("grafikkarte", "prozessor", "speicher", "nvidia", "mainboard", "chip")),
    ("router", {"lan", "wlan", "wifi"}, ("router", "mesh", "repeater", "netzwerk", "fritz", "internet", "glasfaser")),
    ("home", set(), ("smart-home", "smarthome", "heizung", "thermostat", "steckdose", "zuhause", "wohnung")),
    ("car", set(), ("elektroauto", "e-auto", "e-bike", "ebike", "wallbox", "fahrrad", "scooter", "mobilität")),
    ("coffee", set(), ("kaffee", "küche", "haushalt", "airfryer", "heißluft", "mixer", "kochen")),
    ("bulb", {"led"}, ("lampe", "licht", "beleucht", "strompreis", "stromkosten")),
    ("shield", {"vpn"}, ("sicherheit", "schwachstelle", "passwort", "datenschutz", "malware", "hack", "schutz")),
    ("cloud", {"ki", "app"}, ("software", "cloud", "update", "chatgpt", "sprachmodell", "windows", "künstliche")),
    ("tag", set(), ("angebot", "rabatt", "deal", "sale", "gutschein", "preis")),
]

ICON_QUERIES = {  # Suchanfrage für das Stockfoto, wenn die KI keine eigene geliefert hat
    "solar": "solar panels", "router": "wifi router", "phone": "smartphone", "tablet": "tablet computer",
    "laptop": "laptop desk", "speaker": "smart speaker", "vacuum": "robot vacuum cleaner", "powerbank": "power bank charging",
    "headphones": "headphones", "tv": "television living room", "camera": "camera", "gamepad": "video game controller",
    "watch": "smartwatch", "chip": "computer chip", "home": "smart home", "car": "electric car charging",
    "coffee": "coffee machine kitchen", "bulb": "light bulb", "shield": "cyber security", "cloud": "cloud computing",
    "tag": "online shopping",
}

DEFAULT_ICON = "tag"
PALETTES = [  # (oben, unten): kräftige, freundliche Verläufe
    ("#ff7a45", "#d9254a"),
    ("#3b82f6", "#6d28d9"),
    ("#10b981", "#0e7490"),
    ("#f59e0b", "#ea580c"),
    ("#ec4899", "#7c3aed"),
    ("#06b6d4", "#2563eb"),
]


def icon_names() -> list[str]:
    return list(ICONS)


def pick_icon(text: str, preferred: str = "") -> str:
    """Symbol-Name: das von der KI gewählte, sonst per Stichwort aus `text`, sonst das Angebots-Etikett."""
    if preferred in ICONS:
        return preferred
    low = (text or "").lower()
    tokens = re.findall(r"[a-zäöüß0-9]+", low)  # "WLAN-Router" zählt als "wlan" und "router"
    for name, words, prefixes in _RULES:
        plain = tuple(p for p in prefixes if "-" not in p)
        hyphenated = [p for p in prefixes if "-" in p]  # z. B. "e-auto", "smart-home": im Rohtext suchen
        if any(t in words or (plain and t.startswith(plain)) for t in tokens) or any(h in low for h in hyphenated):
            return name
    return DEFAULT_ICON


def palette_for(key: str) -> tuple[str, str]:
    return PALETTES[zlib.crc32((key or "").encode()) % len(PALETTES)]


def thumb(text: str, key: str, preferred: str = "", css_class: str = "thumb") -> Markup:
    """Titelbild als HTML: Farbverlauf (je Rubrik) mit großem Symbol. Kein Bildabruf, immer im richtigen Format."""
    name = pick_icon(text, preferred)
    c1, c2 = palette_for(key)
    svg = (f'<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" '
           f'stroke-linejoin="round" aria-hidden="true" focusable="false">{ICONS[name]}</svg>')
    from .store import slugify
    return Markup(f'<div class="{css_class}" style="--c1:{c1};--c2:{c2}" data-r="{slugify(key or "", 30)}" data-icon="{name}">{svg}</div>')
