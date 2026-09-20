import json
from app_config import get_app_config_value

TRANSLATIONS = {
    "en": {
        "SYSTEM SETTINGS": "SYSTEM SETTINGS",
        "SETTINGS": "SETTINGS",
        "DEBUG": "DEBUG",
        "API SETTINGS": "API SETTINGS",
        "SFX ON": "SFX ON",
        "SFX OFF": "SFX OFF",
        "FX LEVEL": "FX LEVEL",
        "VOICE": "VOICE",
        "LANGUAGE": "LANGUAGE",
        "TIME": "TIME",
        "WEATHER": "WEATHER",
        "SYSTEM STATUS": "SYSTEM STATUS",
        "HEALTH SUMMARY": "HEALTH SUMMARY",
        "UPTIME": "UPTIME",
        "CPU": "CPU",
        "RAM": "RAM",
        "DISK": "DISK",
        "BATTERY": "BATTERY",
        "CONVERSATION": "CONVERSATION",
        "ONLINE": "ONLINE",
        "OFFLINE": "OFFLINE",
        "LISTENING": "LISTENING",
        "THINKING": "THINKING",
        "SPEAKING": "SPEAKING",
        "PAUSED": "PAUSED",
        "IDLE": "IDLE",
        "Just A Rather Very Intelligent System": "Just A Rather Very Intelligent System",
        "MUTE": "MUTE",
        "MUTED": "MUTED",
        "PAUSE": "PAUSE",
        "RESUME": "RESUME",
"SHUTDOWN": "SHUTDOWN",
        "LIVE": "LIVE",
        "SEND": "SEND",
        "SFX": "SFX",
        "ERROR": "ERROR",
        "CONNECTING": "CONNECTING",
        "EXIT": "EXIT",
        "TRAY": "BACKGROUND",
        "INTERNET": "INTERNET",
        "EXPERT MODEL": "MODEL",
        "MODEL": "MODEL",
        "GEMINI READY": "Gemini Ready",
        "GEMINI MISSING": "Gemini API Missing",
        "OPENROUTER READY": "OpenRouter Ready",
        "OPENROUTER MISSING": "OpenRouter API Missing",
        "ACTIVE ENGINE": "Active Engine",
        "GEMINI API KEY": "GEMINI API KEY (For Native Audio)",
        "OPENROUTER API KEY": "OPENROUTER API KEY (For LLM Routing)",
        "UPDATE SETTINGS": "Update your engine and API settings.",
        "ENTER KEY": "Please enter your Gemini or OpenRouter API key.",
        "API SETTINGS TITLE": "API SETTINGS",
        "FIRST SETUP REQUIRED": "FIRST SETUP REQUIRED",
        "WEATHER CITY": "WEATHER CITY",
        "LIVE DATA READY": "Live data ready.",
        "HEALTH DATA UNAVAILABLE": "Health data unavailable.",
        "HEALTH SUMMARY NOT READY": "Health summary not ready yet.",
        "AUTO MODEL": "Auto",
        "WEBCAM": "Webcam",
        "CLOSE": "CLOSE",
        "SAVE": "SAVE",
        "CHATS": "CHATS",
        "NEW CHAT": "New Chat",
        "RENAME": "Rename",
        "DELETE": "Delete"
    },
    "tr": {
        "SYSTEM SETTINGS": "SISTEM AYARLARI",
        "SETTINGS": "AYARLAR",
        "DEBUG": "HATA AYIKLAMA",
        "API SETTINGS": "API AYARLARI",
        "SFX ON": "SES EFEKTI: ACIK",
        "SFX OFF": "SES EFEKTI: KAPALI",
        "FX LEVEL": "EFEKT SEVIYESI",
        "VOICE": "SES (VOICE)",
        "LANGUAGE": "DIL (LANGUAGE)",
        "TIME": "SAAT",
        "WEATHER": "HAVA DURUMU",
        "SYSTEM STATUS": "SISTEM DURUMU",
        "HEALTH SUMMARY": "SAGLIK OZETI",
        "UPTIME": "CALISMA SURESI",
        "CPU": "ISLEMCII",
        "RAM": "BELLEK",
        "DISK": "DEPOLAMA",
        "BATTERY": "BATARYA",
        "CONVERSATION": "SOHBET GECMISI",
        "ONLINE": "CEVIRIMICI",
        "OFFLINE": "CEVRIMDISI",
        "LISTENING": "DINLIYOR...",
        "THINKING": "DUSUNUYOR...",
        "SPEAKING": "KONUSUYOR...",
        "PAUSED": "DURAKLATILDI",
        "IDLE": "BOSHTA",
        "Just A Rather Very Intelligent System": "Sadece Oldukca Zeki Bir Sistem",
        "MUTE": "SESSIZ",
        "MUTED": "SESSIZE ALINDI",
        "PAUSE": "DURDUR",
        "RESUME": "DEVAM ET",
"SHUTDOWN": "KAPAT",
        "LIVE": "CANLI",
        "SEND": "GONDER",
        "SFX": "SES EFEKTI",
        "ERROR": "HATA",
        "CONNECTING": "BAGLANIYOR",
        "EXIT": "CIKIS",
        "TRAY": "ARKA PLAN",
        "INTERNET": "INTERNET",
        "EXPERT MODEL": "MODEL",
        "MODEL": "MODEL",
        "GEMINI READY": "Gemini Hazir",
        "GEMINI MISSING": "Gemini API Eksik",
        "OPENROUTER READY": "OpenRouter Hazir",
        "OPENROUTER MISSING": "OpenRouter API Eksik",
        "ACTIVE ENGINE": "Aktif Motor",
        "GEMINI API KEY": "GEMINI API KEY (Native Audio Icin)",
        "OPENROUTER API KEY": "OPENROUTER API KEY (LLM Yonlendirme Icin)",
        "UPDATE SETTINGS": "Zeka Motoru ve API ayarlarinizi guncelleyin.",
        "ENTER KEY": "Lutfen Gemini veya OpenRouter API anahtarinizi girin.",
        "API SETTINGS TITLE": "API AYARLARI",
        "FIRST SETUP REQUIRED": "ILK KURULUM GEREKLI",
        "WEATHER CITY": "HAVA DURUMU SEHIRI",
        "LIVE DATA READY": "Anlik veri hazir.",
        "HEALTH DATA UNAVAILABLE": "Saglik verisi alinamadi.",
        "HEALTH SUMMARY NOT READY": "Saglik ozeti hazir degil.",
        "AUTO MODEL": "Otomatik",
        "WEBCAM": "Kamera",
        "CLOSE": "KAPAT",
        "SAVE": "KAYDET",
        "CHATS": "SOHBETLER",
        "NEW CHAT": "Yeni Sohbet",
        "RENAME": "Yeniden Adlandir",
        "DELETE": "Sil"
    }
}

# Language cache: avoids repeated config reads during animation loop (~30fps)
_cached_lang: str | None = None

def _get_lang() -> str:
    global _cached_lang
    if _cached_lang is None:
        _cached_lang = str(get_app_config_value("ui_language", "tr")).lower()
    return _cached_lang if _cached_lang in TRANSLATIONS else "en"

def invalidate_lang_cache():
    global _cached_lang
    _cached_lang = None

def T(key: str) -> str:
    lang = _get_lang()
    return TRANSLATIONS[lang].get(key, key)

_DATE_REPLACEMENTS = {
    "JANUARY": "OCAK", "FEBRUARY": "SUBAT", "MARCH": "MART",
    "APRIL": "NISAN", "MAY": "MAYIS", "JUNE": "HAZIRAN",
    "JULY": "TEMMUZ", "AUGUST": "AGUSTOS", "SEPTEMBER": "EYLUL",
    "OCTOBER": "EKIM", "NOVEMBER": "KASIM", "DECEMBER": "ARALIK",
    "MONDAY": "PAZARTESI", "TUESDAY": "SALI", "WEDNESDAY": "CARSAMBA",
    "THURSDAY": "PERSEMBE", "FRIDAY": "CUMA", "SATURDAY": "CUMARTESI", "SUNDAY": "PAZAR"
}

def T_DATE(eng_text: str) -> str:
    if _get_lang() == "en":
        return eng_text
    res = eng_text
    for en, tr in _DATE_REPLACEMENTS.items():
        res = res.replace(en, tr)
    return res
