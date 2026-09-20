"""
Ekran görüntüsü analizi — Windows için mss + ctypes kullanır.
"""

from __future__ import annotations

import ctypes
import io
import mimetypes
import tempfile
import time
from pathlib import Path

from google import genai
from google.genai import errors, types
from PIL import Image, ImageStat

from app_config import get_app_config_value

try:
    import mss
    import mss.tools
    HAS_MSS = True
except ImportError:
    HAS_MSS = False


VISION_MODELS = (
    "models/gemini-3.6-flash",
    "models/gemini-2.5-flash",
    "models/gemini-2.5-flash-lite",
)
VISION_MAX_DIMENSION = 1800
VISION_MAX_INLINE_BYTES = 5_500_000


def _get_active_window_title() -> str:
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value.strip()
    except Exception:
        return ""


def _capture_active_window() -> tuple[bool, str, str]:
    """Ekran görüntüsü al. (ok, file_path, window_title) döndürür."""
    window_title = _get_active_window_title()
    img = None

    # Yöntem 1: mss (hızlı ama bazı GPU sürücülerinde BitBlt hatası verebilir)
    if HAS_MSS:
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[0]  # Tüm ekranları kapsar
                screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        except Exception:
            img = None  # Fallback'e düş

    # Yöntem 2: pyautogui (mss başarısız olursa)
    if img is None:
        try:
            import pyautogui
            img = pyautogui.screenshot()
        except Exception:
            img = None

    # Yöntem 3: Windows GDI (ctypes) — en son çare
    if img is None:
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            
            w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
            h = user32.GetSystemMetrics(1)  # SM_CYSCREEN
            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
            old = gdi32.SelectObject(hdc_mem, hbmp)
            gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, 0, 0, 0x00CC0020)  # SRCCOPY
            
            # BITMAPINFOHEADER
            import struct
            bmi = struct.pack('IiiHHIIiiII', 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
            buf = ctypes.create_string_buffer(w * h * 4)
            gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, bmi, 0)
            
            img = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')
            
            gdi32.SelectObject(hdc_mem, old)
            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(0, hdc_screen)
        except Exception as exc:
            return False, f"Ekran görüntüsü alınamadı: {exc}", ""

    try:
        handle = tempfile.NamedTemporaryFile(
            prefix="jarvis-screen-", suffix=".png", delete=False
        )
        tmp_path = Path(handle.name)
        handle.close()
        img.save(str(tmp_path), format="PNG")
    except Exception as exc:
        return False, f"Ekran görüntüsü kaydedilemedi: {exc}", ""

    return True, str(tmp_path), window_title


def _image_looks_blank(image_path: Path) -> bool:
    try:
        with Image.open(image_path) as img:
            sample = img.convert("RGB")
            stat = ImageStat.Stat(sample)
            means = stat.mean
            extrema = stat.extrema
            max_seen = max(channel[1] for channel in extrema)
            mean_total = sum(means) / max(1, len(means))
            return max_seen <= 8 or mean_total <= 3
    except Exception:
        return False


def _build_image_part(image_path: Path) -> types.Part:
    mime_type, _ = mimetypes.guess_type(str(image_path))
    if not mime_type:
        mime_type = "image/png"

    try:
        with Image.open(image_path) as img:
            work = img.copy()
        if work.mode not in {"RGB", "L"}:
            work = work.convert("RGB")

        if max(work.size) > VISION_MAX_DIMENSION:
            work.thumbnail((VISION_MAX_DIMENSION, VISION_MAX_DIMENSION), Image.Resampling.LANCZOS)

        png_buffer = io.BytesIO()
        work.save(png_buffer, format="PNG", optimize=True)
        png_bytes = png_buffer.getvalue()
        if len(png_bytes) <= VISION_MAX_INLINE_BYTES:
            return types.Part.from_bytes(data=png_bytes, mime_type="image/png")

        jpg_buffer = io.BytesIO()
        rgb = work.convert("RGB") if work.mode != "RGB" else work
        rgb.save(jpg_buffer, format="JPEG", quality=88, optimize=True)
        return types.Part.from_bytes(data=jpg_buffer.getvalue(), mime_type="image/jpeg")
    except Exception:
        return types.Part.from_bytes(
            data=image_path.read_bytes(),
            mime_type=mime_type,
        )


def _vision_prompt(query: str, window_title: str) -> str:
    label = window_title or "aktif pencere"
    user_query = (query or "Ekranda ne var?").strip()
    return (
        f"Görüntülenen pencere: {label}\n"
        "Sen ekranı analiz eden bir AI asistanısın. Lütfen YALNIZCA kullanıcının sorusuna doğrudan cevap ver. "
        "Gereksiz açıklamalar, selamlamalar veya ekranın genel özeti ile VAKİT KAYBETME.\n\n"
        "ÖNEMLİ KOORDİNAT KURALI: Eğer kullanıcı ekrandaki bir şeye tıklamanı/bulmanı istiyorsa veya bir eleman soruyorsa, "
        "o elemanın tahmini merkez piksel koordinatını (x, y) olarak ver. (Sol üst: 0,0). "
        "Örn: 'GO butonu: tahmini koordinat (960, 540)'. \n\n"
        f"Kullanıcı Sorusu/Talebi: {user_query}\n\n"
        "Cevabın çok kısa ve net olsun:"
    )


def _extract_response_text(response) -> str:
    text = str(getattr(response, "text", "") or "").strip()
    if text:
        return text

    candidates = getattr(response, "candidates", None) or []
    chunks: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_text = str(getattr(part, "text", "") or "").strip()
            if part_text:
                chunks.append(part_text)
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def _is_transient_vision_error(exc: Exception) -> bool:
    if isinstance(exc, (errors.ServerError, TimeoutError)):
        return True
    message = str(exc or "").lower()
    transient_markers = (
        "503", "429", "deadline", "timed out", "timeout",
        "unavailable", "service unavailable", "internal error",
        "busy", "overloaded", "resource exhausted", "try again later",
        "backend error", "connection reset",
    )
    return any(marker in message for marker in transient_markers)


def _is_quota_vision_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    quota_markers = (
        "quota", "rate limit", "resource exhausted",
        "too many requests", "quota exceeded", "limit exceeded", "billing",
    )
    return any(marker in message for marker in quota_markers)


def _friendly_vision_error(exc: Exception) -> str:
    if _is_quota_vision_error(exc):
        return "Gemini vision isteği kota veya hız limitine takıldı. Biraz bekleyip tekrar dene ya da API planını kontrol et."
    if _is_transient_vision_error(exc):
        return "Gemini vision servisi şu anda yoğun veya geçici olarak ulaşılamıyor. Biraz sonra tekrar dene."
    return f"Gemini vision isteği başarısız oldu: {exc}"


def _analyze_with_gemini(query: str, image_path: Path, window_title: str) -> str:
    api_key = str(get_app_config_value("gemini_api_key", "") or "").strip()
    if not api_key:
        return "Gemini API anahtarı eksik olduğu için ekran analizi yapılamadı."

    prompt = _vision_prompt(query, window_title)
    client = genai.Client(api_key=api_key)
    image_part = _build_image_part(image_path)
    retry_delays = (0.9, 1.8, 3.0)
    last_error: Exception | None = None

    for model_name in VISION_MODELS:
        for attempt, delay in enumerate(retry_delays, start=1):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_text(text=prompt),
                        image_part,
                    ],
                    config=types.GenerateContentConfig(
                        safety_settings=[
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                        ],
                        temperature=0.2),
                )
                merged = _extract_response_text(response)
                if merged:
                    return merged
                raise RuntimeError("Gemini geçerli bir ekran analizi metni döndürmedi.")
            except Exception as exc:
                last_error = exc
                if attempt < len(retry_delays) and _is_transient_vision_error(exc):
                    time.sleep(delay)
                    continue
                if _is_transient_vision_error(exc):
                    break
                raise RuntimeError(_friendly_vision_error(exc)) from exc

    assert last_error is not None
    raise RuntimeError(_friendly_vision_error(last_error))


def analyze_screen(query: str, target: str = "active_window") -> str:
    if not HAS_MSS:
        return (
            "Ekran analizi için 'mss' kütüphanesi gerekiyor. "
            "Terminalde şunu çalıştır: pip install mss"
        )

    ok, result, window_title = _capture_active_window()
    if not ok:
        return f"Ekran görüntüsü alınamadı: {result}"

    image_path = Path(result)
    try:
        if not image_path.exists():
            return "Ekran görüntüsü dosyası bulunamadı. Tekrar dene."
        if image_path.stat().st_size <= 0:
            return "Ekran görüntüsü boş geldi."
        # Siyah ekran kontrolünü kaldırdık, çünkü Speedtest.net gibi siteler zaten siyah arka planlı.
        # Gemini Vision zaten ekran karanlıksa bunu yorumlayacaktır.

        try:
            analysis = _analyze_with_gemini(query, image_path, window_title)
        except Exception as exc:
            prefix = window_title.strip()
            if prefix:
                return f"Ekran görüntüsü alındı ({prefix}) ama analiz tamamlanamadı: {exc}"
            return f"Ekran görüntüsü alındı ama analiz tamamlanamadı: {exc}"

        if window_title:
            return f"[Aktif pencere: {window_title}]\n{analysis}"
        return analysis
    finally:
        try:
            if image_path.exists():
                image_path.unlink()
        except Exception:
            pass
