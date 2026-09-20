"""
Mini Menü — Küçük, minimal bir pencere.
Yazı yazma + dosya ekleme + sohbet geçmişi.
Wake word ile tetiklenir, Ana Menüye geçiş butonu içerir.
"""

import tkinter as tk
from tkinter import filedialog
import os
import threading


# Renkler (ana UI ile uyumlu)
C_BG    = "#050f10"
C_PRI   = "#00e6c3"
C_TEXT  = "#c0f0e8"
C_PANEL = "#0a1a1c"
C_DIM   = "#1a3a3a"
C_ORG   = "#ff6600"


class MiniMenu:
    """Küçük, ekranın sağ altında açılan mini pencere."""

    def __init__(self, on_text_submit: callable, on_expand: callable, on_close: callable, tk_root=None):
        """
        on_text_submit(text, files): Mesaj gönderildiğinde çağrılır
        on_expand(): Ana menüye geçiş
        on_close(): Mini menü kapatılınca
        tk_root: Ana Tkinter root penceresi (Toplevel için gerekli)
        """
        self.on_text_submit = on_text_submit
        self.on_expand = on_expand
        self.on_close = on_close
        self.attached_files = []
        self.root = None
        self._tk_root = tk_root
        self._visible = False
        self._chat_history = []  # Sohbet geçmişi
        self._chat_text = None   # Sohbet metin alanı

    def show(self):
        """Mini menüyü göster (zaten açıksa öne getir)."""
        if self._visible and self.root:
            try:
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
                self._input_entry.focus_set()
                return
            except Exception:
                pass

        self._build_window()

    def hide(self):
        """Mini menüyü gizle."""
        if self.root:
            try:
                self.root.withdraw()
            except Exception:
                pass
        self._visible = False

    def destroy(self):
        """Mini menüyü tamamen kapat."""
        if self.root:
            try:
                self.root.destroy()
            except Exception:
                pass
        self.root = None
        self._visible = False

    def show_response(self, text: str):
        """Jarvis'in cevabını sohbet geçmişine ekle."""
        if self._chat_text and self.root:
            try:
                # "Düşünüyorum..." mesajını kaldır
                self._chat_text.configure(state="normal")
                content = self._chat_text.get("1.0", tk.END)
                if "⏳ Düşünüyorum..." in content:
                    # Son satırı bul ve kaldır
                    lines = content.split("\n")
                    new_lines = [l for l in lines if "⏳ Düşünüyorum..." not in l]
                    self._chat_text.delete("1.0", tk.END)
                    self._chat_text.insert("1.0", "\n".join(new_lines))
                self._chat_text.configure(state="disabled")
                
                # Gerçek cevabı ekle
                short = text[:200] + "..." if len(text) > 200 else text
                self._add_chat_message("JARVIS", short)
            except Exception:
                pass

    def _add_chat_message(self, sender: str, text: str):
        """Sohbet geçmişine mesaj ekle."""
        self._chat_history.append({"sender": sender, "text": text})
        if self._chat_text:
            try:
                self._chat_text.configure(state="normal")
                # Mesajı ekle
                if sender == "Siz":
                    self._chat_text.insert(tk.END, f"Siz: {text}\n", "user")
                else:
                    self._chat_text.insert(tk.END, f"JARVIS: {text}\n", "jarvis")
                self._chat_text.see(tk.END)
                self._chat_text.configure(state="disabled")
            except Exception:
                pass

    def _build_window(self):
        """Pencereyi oluştur."""
        if self._tk_root:
            self.root = tk.Toplevel(self._tk_root)
        else:
            self.root = tk.Toplevel()
        self.root.title("JARVIS")
        self.root.configure(bg=C_BG)
        self.root.overrideredirect(True)  # Başlık çubuğu yok
        self.root.attributes("-topmost", True)  # Her zaman üstte
        self.root.attributes("-alpha", 0.95)  # Hafif şeffaf

        # Pencere boyutu ve konumu (sağ alt köşe)
        w, h = 420, 280
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = screen_w - w - 20
        y = screen_h - h - 60
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        # ── Başlık Çubuğu ──
        title_frame = tk.Frame(self.root, bg="#0a2020", height=28)
        title_frame.pack(fill="x")
        title_frame.pack_propagate(False)

        tk.Label(title_frame, text="⚡ JARVIS", fg=C_PRI, bg="#0a2020",
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=8)

        tk.Button(title_frame, text="✕", fg="#ff4444", bg="#0a2020",
                  activebackground="#330000", borderwidth=0,
                  font=("Segoe UI", 10, "bold"), cursor="hand2",
                  command=self._on_close).pack(side="right", padx=5)

        # Sürükleme desteği
        title_frame.bind("<Button-1>", self._start_drag)
        title_frame.bind("<B1-Motion>", self._do_drag)

        # ── Sohbet Alanı (sabit yükseklik) ──
        chat_frame = tk.Frame(self.root, bg=C_BG, height=140)
        chat_frame.pack(fill="x", padx=10, pady=(6, 2))
        chat_frame.pack_propagate(False)

        self._chat_text = tk.Text(
            chat_frame, 
            fg=C_TEXT, bg="#041212", 
            insertbackground=C_TEXT,
            borderwidth=0, 
            font=("Segoe UI", 9),
            wrap="word",
            state="disabled",
            highlightthickness=1, 
            highlightbackground=C_DIM,
            highlightcolor=C_PRI
        )
        
        scrollbar = tk.Scrollbar(chat_frame, command=self._chat_text.yview)
        self._chat_text.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        self._chat_text.pack(side="left", fill="both", expand=True)
        
        # Sohbet stilleri
        self._chat_text.tag_config("user", foreground="#00ff88")
        self._chat_text.tag_config("jarvis", foreground=C_PRI)
        self._chat_text.tag_config("system", foreground=C_ORG)
        
        # Başlangıç mesajı
        self._chat_text.configure(state="normal")
        self._chat_text.insert(tk.END, "JARVIS: Merhaba! Nasil yardimci olabilirim?\n", "jarvis")
        self._chat_text.configure(state="disabled")

        # ── Dosya Bilgisi ──
        self._file_label = tk.Label(
            self.root, text="", fg=C_ORG, bg=C_BG, font=("Segoe UI", 8))
        self._file_label.pack(fill="x", padx=10)

        # ── Input Satırı ──
        input_frame = tk.Frame(self.root, bg=C_BG)
        input_frame.pack(fill="x", padx=10, pady=(2, 4))

        # 📎 Dosya Ekle
        tk.Button(input_frame, text="📎", fg=C_TEXT, bg=C_PANEL,
                  activebackground=C_DIM, borderwidth=0,
                  font=("Segoe UI", 12), cursor="hand2", width=3,
                  command=self._on_attach).pack(side="left", padx=(0, 4))

        # Yazı kutusu
        self._input_var = tk.StringVar()
        self._input_entry = tk.Entry(
            input_frame, textvariable=self._input_var,
            fg=C_TEXT, bg="#041212", insertbackground=C_TEXT,
            borderwidth=0, font=("Segoe UI", 10),
            highlightthickness=1, highlightbackground=C_DIM,
            highlightcolor=C_PRI)
        self._input_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self._input_entry.bind("<Return>", self._on_submit)

        # Gönder butonu
        tk.Button(input_frame, text="▸", fg=C_ORG, bg=C_PANEL,
                  activebackground=C_ORG, borderwidth=0,
                  font=("Segoe UI", 12, "bold"), cursor="hand2", width=3,
                  command=self._on_submit).pack(side="left", padx=(4, 0))

        # ── Alt Çubuk ──
        bottom_frame = tk.Frame(self.root, bg=C_BG)
        bottom_frame.pack(fill="x", padx=10, pady=(0, 6))

        tk.Button(bottom_frame, text="🎙️ Ana Menüye Geç",
                  fg=C_PRI, bg=C_PANEL,
                  activeforeground=C_BG, activebackground=C_PRI,
                  borderwidth=0, font=("Segoe UI", 9, "bold"),
                  cursor="hand2", command=self._on_expand).pack(side="right")

        self._visible = True
        self._input_entry.focus_set()

        # ESC ile kapat
        self.root.bind("<Escape>", lambda e: self._on_close())

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _do_drag(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _on_attach(self):
        filepath = filedialog.askopenfilename(title="Dosya Seç")
        if filepath:
            self.attached_files.append(filepath)
            names = ", ".join(os.path.basename(f) for f in self.attached_files)
            self._file_label.config(text=f"📎 {names}")

    def _on_submit(self, event=None):
        text = self._input_var.get().strip()
        if not text and not self.attached_files:
            return
        self._input_var.set("")
        
        # Kullanıcı mesajını sohbet geçmişine ekle
        if text:
            self._add_chat_message("Siz", text)
        
        # Düşünüyorum mesajı
        self._add_chat_message("JARVIS", "⏳ Düşünüyorum...")

        files = list(self.attached_files)
        self.attached_files.clear()
        self._file_label.config(text="")

        # Arka planda gönder
        threading.Thread(target=self.on_text_submit, args=(text, files), daemon=True).start()

    def _on_expand(self):
        self.hide()
        self.on_expand()

    def _on_close(self):
        self.hide()
        self.on_close()
