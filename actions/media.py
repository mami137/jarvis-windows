"""
Medya oynatma — Windows için YouTube, Spotify URI scheme.
Apple Music desteği Windows'ta bulunmamaktadır.
"""

from __future__ import annotations

import subprocess
import urllib.parse
import webbrowser

from actions.browser import browser_control

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False


def _copy_to_clipboard(text: str) -> tuple[bool, str]:
    if HAS_PYPERCLIP:
        try:
            pyperclip.copy(text)
            return True, "ok"
        except Exception as exc:
            return False, f"Panoya kopyalanamadı: {exc}"
    # PowerShell fallback
    try:
        subprocess.run(
            ["powershell", "-Command", f"Set-Clipboard -Value '{text.replace(chr(39), chr(96))}'"],
            check=True, timeout=5,
        )
        return True, "ok"
    except Exception as exc:
        return False, f"Panoya kopyalanamadı: {exc}"


def _spotify_installed() -> bool:
    import shutil
    return shutil.which("Spotify") is not None or subprocess.run(
        "where Spotify", shell=True, capture_output=True
    ).returncode == 0


def _play_youtube(query: str) -> str:
    return browser_control("play_youtube", query=query)


def _play_spotify(query: str, autoplay: bool = True) -> str:
    encoded_query = urllib.parse.quote(query.strip())
    search_url = f"spotify:search:{encoded_query}"
    try:
        subprocess.run(["start", "", search_url], shell=True, timeout=10)
    except Exception as exc:
        return f"Spotify açılamadı: {exc}"
    return f"Spotify'da '{query}' araması açıldı."


def play_media(query: str, provider: str = "auto", autoplay: bool = True) -> str:
    if not query or not query.strip():
        return "Çalınacak içerik belirtilmedi."

    normalized_provider = (provider or "auto").strip().lower()
    if normalized_provider in {"yt", "youtube music"}:
        normalized_provider = "youtube"
    elif normalized_provider in {"apple music", "music", "apple_music"}:
        # Apple Music Windows'ta yok, YouTube'a yönlendir
        return _play_youtube(query)

    if normalized_provider == "spotify":
        return _play_spotify(query, autoplay=autoplay)
    if normalized_provider == "youtube":
        return _play_youtube(query)

    # auto: Spotify URI dene, yoksa YouTube
    result = _play_spotify(query, autoplay=autoplay)
    if "açılamadı" not in result:
        return result
    return _play_youtube(query)
