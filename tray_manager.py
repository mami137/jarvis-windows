"""
Sistem Tepsisi (System Tray) Yöneticisi — pystray ile Windows tray ikonu.
"""

import threading
from PIL import Image, ImageDraw


def _create_tray_icon_image():
    """Basit bir Jarvis tray ikonu oluşturur (turkuaz daire)."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Dış halka
    draw.ellipse([4, 4, size - 4, size - 4], fill=(0, 200, 220, 255))
    # İç daire
    draw.ellipse([16, 16, size - 16, size - 16], fill=(0, 40, 50, 255))
    # Merkez nokta
    draw.ellipse([26, 26, size - 26, size - 26], fill=(0, 255, 200, 255))
    return img


class TrayManager:
    """Windows sistem tepsisi ikonu yöneticisi."""

    def __init__(self, on_mini_menu: callable, on_main_menu: callable, on_quit: callable):
        self.on_mini_menu = on_mini_menu
        self.on_main_menu = on_main_menu
        self.on_quit = on_quit
        self._icon = None
        self._thread = None

    def start(self):
        import pystray
        from pystray import MenuItem, Menu

        icon_image = _create_tray_icon_image()

        menu = Menu(
            MenuItem("📝 Mini Menü", lambda: self.on_mini_menu()),
            MenuItem("🎙️ Ana Menü", lambda: self.on_main_menu()),
            MenuItem(pystray.Menu.SEPARATOR, None),
            MenuItem("❌ Çıkış", lambda: self._do_quit()),
        )

        self._icon = pystray.Icon(
            name="JARVIS",
            icon=icon_image,
            title="JARVIS — Arka Planda Çalışıyor",
            menu=menu,
        )

        # Çift tıkla = mini menü
        self._icon.on_activate = lambda: self.on_mini_menu()

        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        print("[TRAY] Sistem tepsisi ikonu aktif.")

    def _do_quit(self):
        if self._icon:
            self._icon.stop()
        self.on_quit()

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
