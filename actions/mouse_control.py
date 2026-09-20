"""
Fare ve ekran kontrolü — pyautogui ile çalışır.
Jarvis'in ekrandaki düğmelere tıklamasını, fare hareketlerini
ve kaydırma (scroll) işlemlerini yapmasını sağlar.
"""

import pyautogui
import time

# Güvenlik: Fare imlecini köşeye götürünce acil durdurma
pyautogui.FAILSAFE = True
# Hareketler arası bekleme (saniye)
pyautogui.PAUSE = 0.15


def mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    """Belirtilen ekran koordinatına fare ile tıklar."""
    try:
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
        return f"Fare ile tıklandı: ({x}, {y}) [Düğme: {button}, Tıklama: {clicks}]"
    except Exception as e:
        return f"Fare tıklama hatası: {str(e)}"


def mouse_move(x: int, y: int) -> str:
    """Fareyi belirtilen koordinata taşır (tıklamadan)."""
    try:
        pyautogui.moveTo(x=x, y=y, duration=0.3)
        return f"Fare taşındı: ({x}, {y})"
    except Exception as e:
        return f"Fare hareket hatası: {str(e)}"


def mouse_scroll(amount: int, x: int = None, y: int = None) -> str:
    """Ekranı yukarı (pozitif) veya aşağı (negatif) kaydırır."""
    try:
        if x is not None and y is not None:
            pyautogui.scroll(amount, x=x, y=y)
        else:
            pyautogui.scroll(amount)
        direction = "yukarı" if amount > 0 else "aşağı"
        return f"Ekran {direction} kaydırıldı ({abs(amount)} birim)"
    except Exception as e:
        return f"Kaydırma hatası: {str(e)}"


def mouse_drag(start_x: int, start_y: int, end_x: int, end_y: int) -> str:
    """Fareyi başlangıç noktasından bitiş noktasına sürükler (drag)."""
    try:
        pyautogui.moveTo(start_x, start_y, duration=0.2)
        pyautogui.drag(end_x - start_x, end_y - start_y, duration=0.5)
        return f"Sürüklendi: ({start_x},{start_y}) -> ({end_x},{end_y})"
    except Exception as e:
        return f"Sürükleme hatası: {str(e)}"


def get_mouse_position() -> str:
    """Farenin şu anki ekran koordinatlarını döndürür."""
    pos = pyautogui.position()
    return f"Fare konumu: ({pos.x}, {pos.y})"


def get_screen_size() -> str:
    """Ekranın çözünürlüğünü döndürür."""
    size = pyautogui.size()
    return f"Ekran çözünürlüğü: {size.width}x{size.height}"
