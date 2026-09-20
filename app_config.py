# muhammet emin tarafindan yapilmistir
from __future__ import annotations

import json
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "api_keys.json"


DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "openrouter_api_key": "",
    "ai_engine": "gemini",
    "voice": "Charon",
    "ui_language": "tr",
    "weather_location": "",
}

# In-memory cache: avoids ~450-750 disk reads/sec from T() calls in animation loop
_config_cache: dict | None = None
_config_cache_time: float = 0.0
_CACHE_TTL: float = 2.0


def load_app_config() -> dict:
    global _config_cache, _config_cache_time
    now = time.monotonic()
    if _config_cache is not None and (now - _config_cache_time) < _CACHE_TTL:
        return _config_cache
    config = dict(DEFAULT_CONFIG)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            config.update(raw)
    except Exception:
        pass
    _config_cache = config
    _config_cache_time = now
    return config


def save_app_config(updates: dict) -> dict:
    global _config_cache, _config_cache_time
    config = load_app_config()
    for key, value in (updates or {}).items():
        if value is None:
            continue
        config[key] = value
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, indent=4, ensure_ascii=False),
        encoding="utf-8",
    )
    _config_cache = config
    _config_cache_time = time.monotonic()
    # Dil degisirse i18n cache'ini de temizle
    if "ui_language" in (updates or {}):
        try:
            from core.i18n import invalidate_lang_cache
            invalidate_lang_cache()
        except ImportError:
            pass
    return config


def get_app_config_value(key: str, default=None):
    return load_app_config().get(key, default)


def has_gemini_api_key() -> bool:
    value = str(get_app_config_value("gemini_api_key", "") or "").strip()
    return bool(value)

def has_openrouter_api_key() -> bool:
    value = str(get_app_config_value("openrouter_api_key", "") or "").strip()
    return bool(value)
