"""
Basit hava durumu ozeti — uzaktaki bir servis uzerinden calisir.
Alp Ünlü tarafından yapılmıştır — @alppunlu

Dil: get_weather_summary, uygulamanın seçili arayüz diline (ui_language)
göre Türkçe veya İngilizce özet döndürür.

Konum: IP tabanlı otomatik konum tespiti kullanılır.
"""

from __future__ import annotations

import os

import requests

from app_config import get_app_config_value
from net_usage import add_sent, add_recv


def _get_lang() -> str:
    lang = str(get_app_config_value("ui_language", "tr")).lower()
    return "tr" if lang == "tr" else "en"


def _get_auto_location() -> str:
    """Windows konum ayarlarından ve timezone'dan otomatik konum tespiti."""
    try:
        # Önce timezone'dan konum tespiti yap
        from tzlocal import get_localzone
        tz = get_localzone()
        tz_str = str(tz)
        
        # Timezone -> Şehir eşleme
        TZ_CITY_MAP = {
            "Europe/Istanbul": "Istanbul",
            "Europe/Ankara": "Ankara",
            "Europe/Izmir": "Izmir",
            "America/New_York": "New York",
            "America/Los_Angeles": "Los Angeles",
            "America/Chicago": "Chicago",
            "Europe/London": "London",
            "Europe/Paris": "Paris",
            "Europe/Berlin": "Berlin",
            "Asia/Tokyo": "Tokyo",
            "Asia/Shanghai": "Shanghai",
            "Asia/Dubai": "Dubai",
            "Australia/Sydney": "Sydney",
            "America/Toronto": "Toronto",
            "Europe/Rome": "Rome",
            "Europe/Madrid": "Madrid",
            "Europe/Amsterdam": "Amsterdam",
            "Europe/Moscow": "Moscow",
            "Asia/Kolkata": "Mumbai",
            "Asia/Seoul": "Seoul",
            "Asia/Singapore": "Singapore",
            "Pacific/Auckland": "Auckland",
        }
        
        if tz_str in TZ_CITY_MAP:
            return TZ_CITY_MAP[tz_str]
        
        # Timezone'dan şehir adını çıkarmaya çalış
        if "/" in tz_str:
            city_part = tz_str.split("/")[-1].replace("_", " ")
            if city_part:
                return city_part
    
    except Exception:
        pass
    
    # Tümservisler başarısızsa İstanbul'a dön
    return "Istanbul"


# Türkçe Hava Durumu Sözlüğü (wttr.in İngilizce döndürse de yerelde çevrilir)
WEATHER_TR_DICT = {
    "sunny": "Güneşli", "clear": "Açık", "clear sky": "Açık",
    "cloudy": "Bulutlu", "cloudy sky": "Bulutlu", "overcast": "Çok Bulutlu",
    "sunny intervals": "Aralıklı Güneşli", "partly cloudy": "Parçalı Bulutlu",
    "mist": "Sisli", "fog": "Sis", "freezing fog": "Dondurucu Sis",
    "rain": "Yağmur", "patchy rain nearby": "Bölgesel Yağmur", "patchy rain possible": "Bölgesel Yağmur",
    "patchy snow nearby": "Bölgesel Kar", "patchy snow possible": "Bölgesel Karlı",
    "patchy sleet nearby": "Bölgesel Sulu Kar", "patchy sleet possible": "Sulu Kar İhtimali",
    "patchy freezing drizzle possible": "Dondurucu Çiseleme İhtimali",
    "thundery outbreaks possible": "Gök Gürültülü Fırtına İhtimali", "blowing snow": "Kar Fırtınası",
    "blizzard": "Tipi",
    "patchy light drizzle": "Bölgesel Hafif Çiseleme", "light drizzle": "Hafif Çiseleme",
    "freezing drizzle": "Dondurucu Çiseleme", "heavy freezing drizzle": "Şiddetli Dondurucu Çiseleme",
    "patchy light rain": "Bölgesel Hafif Yağmur", "light rain": "Hafif Yağmur",
    "moderate rain at times": "Zaman Zaman Orta Şiddette Yağmur", "moderate rain": "Orta Şiddette Yağmur",
    "heavy rain at times": "Zaman Zaman Şiddetli Yağmur", "heavy rain": "Şiddetli Yağmur",
    "light freezing rain": "Hafif Dondurucu Yağmur", "moderate or heavy freezing rain": "Orta veya Şiddetli Dondurucu Yağmur",
    "light sleet": "Hafif Sulu Kar", "moderate or heavy sleet": "Orta veya Şiddetli Sulu Kar",
    "patchy light snow": "Bölgesel Hafif Kar", "light snow": "Hafif Kar",
    "patchy moderate snow": "Bölgesel Orta Şiddette Kar", "moderate snow": "Orta Şiddette Kar",
    "patchy heavy snow": "Bölgesel Şiddetli Kar", "heavy snow": "Şiddetli Kar",
    "ice pellets": "Dolu", "light rain shower": "Hafif Sağanak Yağmur",
    "moderate or heavy rain shower": "Orta veya Şiddetli Sağanak Yağmur", "torrential rain shower": "Şiddetli Sağanak Yağmur",
    "light sleet showers": "Hafif Sulu Kar Sağanağı", "moderate or heavy sleet showers": "Orta veya Şiddetli Sulu Kar Sağanağı",
    "light snow showers": "Hafif Kar Sağanağı", "moderate or heavy snow showers": "Orta veya Şiddetli Kar Sağanağı",
    "light showers of ice pellets": "Hafif Dolu Sağanağı", "moderate or heavy showers of ice pellets": "Orta veya Şiddetli Dolu Sağanağı",
    "patchy light rain with thunder": "Bölgesel Gök Gürültülü Hafif Yağmur", "moderate or heavy rain with thunder": "Gök Gürültülü Orta veya Şiddetli Yağmur",
    "patchy light snow with thunder": "Bölgesel Gök Gürültülü Hafif Kar", "moderate or heavy snow with thunder": "Gök Gürültülü Orta veya Şiddetli Kar",
}


def _translate_desc(raw: str) -> str:
    low = raw.strip().lower()
    if not low:
        return raw
    exact = WEATHER_TR_DICT.get(low)
    if exact:
        return exact
    # Alt dize fallback'i: en uzun eşleşen anahtarı bul (örn. "Patchy rain nearby")
    best_key, best_tr = "", ""
    for key, tr in WEATHER_TR_DICT.items():
        if key and key in low and len(key) > len(best_key):
            best_key, best_tr = key, tr
    if best_tr:
        # Eşleşen kısmı çevir, kalan kısmı koru
        idx = low.find(best_key)
        rest = raw[idx + len(best_key):]
        return (best_tr + rest).strip()
    return raw


def get_weather_summary(location: str | None = None, lang: str | None = None) -> str:
    # Konum önceliği: (1) parametre, (2) kullanıcının ayarladığı konum, (3) otomatik tespit
    if location:
        target = location.strip()
    else:
        try:
            from app_config import get_app_config_value
            saved = str(get_app_config_value("weather_location", "") or "").strip()
        except Exception:
            saved = ""
        target = saved or _get_auto_location()
    if lang is None:
        lang = _get_lang()
    is_tr = str(lang).lower() == "tr"

    try:
        params = {"format": "j1"}
        # Açıklamalar her zaman İngilizce alınır; Türkçe çeviri yerelde yapılır.
        params["lang"] = "en"

        response = requests.get(
            f"https://wttr.in/{target}",
            params=params,
            timeout=10,
            headers={"User-Agent": "JARVIS Windows"},
        )
        response.raise_for_status()
        add_sent(len(response.request.url or ""))
        add_recv(len(response.content))
        payload = response.json()
        current = (payload.get("current_condition") or [{}])[0]
        temp_c = current.get("temp_C")
        feels_like = current.get("FeelsLikeC")
        humidity = current.get("humidity")

        raw_desc = ((current.get("weatherDesc") or [{}])[0]).get("value", "")
        if is_tr:
            weather_desc = _translate_desc(raw_desc)
        else:
            weather_desc = raw_desc

        parts = []
        if temp_c:
            parts.append(f"{temp_c}°C")
        if weather_desc:
            parts.append(weather_desc)
        if feels_like and feels_like != temp_c:
            if is_tr:
                parts.append(f"Hissedilen {feels_like}°C")
            else:
                parts.append(f"Feels like {feels_like}°C")
        if humidity:
            if is_tr:
                parts.append(f"Nem %{humidity}")
            else:
                parts.append(f"Humidity {humidity}%")

        if not parts:
            return ("Hava durumu bilgisi şu anda alınamadı." if is_tr
                    else "Weather information is currently unavailable.")

        if is_tr:
            return f"{target} için hava durumu: " + ", ".join(parts) + "."
        return f"{target} weather: " + ", ".join(parts) + "."
    except Exception:
        if is_tr:
            return "Hava durumu bilgisi şu anda alınamadı."
        return "Weather information is currently unavailable."