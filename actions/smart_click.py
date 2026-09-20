import re
import pyautogui
from pathlib import Path
from actions.screen_vision import _capture_active_window, _build_image_part
from google import genai
from google.genai import types
from app_config import get_app_config_value

def smart_click(target: str) -> str:
    """Ekranı analiz edip hedeflenen düğmeye/öğeye doğrudan tıklar (Hızlandırılmış yöntem)."""
    # 1. Ekranı yakala
    ok, img_path_str, window_title = _capture_active_window()
    if not ok:
        return f"Hata: Ekran alınamadı. {img_path_str}"
        
    image_path = Path(img_path_str)
    if not image_path.exists() or image_path.stat().st_size <= 0:
        return "Hata: Ekran görüntüsü boş."

    # 2. Vision API ile sadece o düğmenin koordinatını sor (Çok kısa prompt = Çok hızlı yanıt)
    api_key = str(get_app_config_value("gemini_api_key", "") or "").strip()
    if not api_key:
        return "Gemini API anahtarı eksik."

    client = genai.Client(api_key=api_key)
    image_part = _build_image_part(image_path)
    
    prompt = (
        f"Kullanıcı şu elemana tıklamak istiyor: '{target}'. "
        "Bu ekranda o eleman neredeyse, sadece onun merkez piksel koordinatını X, Y formatında yaz. "
        "Başka HİÇBİR kelime, açıklama veya noktalama işareti KULLANMA. "
        "Sadece sayılar, örneğin: 960, 540"
    )

    try:
        # En hızlı modellerden birini (flash-lite) kullanalım koordinat tahmini için
        response = client.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=[types.Part.from_text(text=prompt), image_part],
            config=types.GenerateContentConfig(
                        safety_settings=[
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                        ],
                        temperature=0.0),
        )
        
        reply = str(getattr(response, "text", "") or "").strip()
        
        # 3. Gelen yanıttan koordinatları çıkar (Örn: "450, 320" veya "(450, 320)")
        coords = re.findall(r'\d+', reply)
        if len(coords) >= 2:
            x, y = int(coords[0]), int(coords[1])
            pyautogui.FAILSAFE = False
            pyautogui.click(x, y)
            result = f"'{target}' başarıyla bulundu ve tıklandı ({x}, {y})."
        else:
            result = f"'{target}' bulunamadı veya koordinat anlaşılamadı. Gelen cevap: {reply}"
            
    except Exception as e:
        result = f"Akıllı tıklama hatası: {str(e)}"
    finally:
        try:
            if image_path.exists():
                image_path.unlink()
        except Exception:
            pass

    return result
