"""Sprecherstimme über die ElevenLabs-API (Text -> MP3)."""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("newsbot.voice")
API = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


class VoiceError(RuntimeError):
    pass


def available() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


def synthesize(text: str, voice_id: str, model_id: str, api_key: str | None = None) -> bytes:
    """Gibt MP3-Bytes zurück. Ein kleiner Bitratenwert reicht für Sprache und hält das Repo schlank."""
    key = api_key or os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise VoiceError("ELEVENLABS_API_KEY fehlt")
    resp = requests.post(
        API.format(voice_id=voice_id),
        params={"output_format": "mp3_44100_64"},
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        json={"text": text, "model_id": model_id},
        timeout=90,
    )
    if not resp.ok:
        raise VoiceError(f"ElevenLabs HTTP {resp.status_code}: {resp.text[:200]}")
    if not resp.content:
        raise VoiceError("Leere Audio-Antwort")
    return resp.content
