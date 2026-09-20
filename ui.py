"""
JARVIS Windows — UI v3
Concentric teal rings · Segmented arcs
Alp Ünlü tarafından yapılmıştır — @alppunlu
"""

import os, time, math, random, threading
import subprocess
import ctypes
import tkinter as tk
from tkinter import filedialog
from collections import deque
from pathlib import Path
import psutil
from PIL import Image, ImageTk

from app_config import has_gemini_api_key, load_app_config, save_app_config
from actions.weather import get_weather_summary
from core.i18n import T, T_DATE
from speed_meter import SpeedMeter
from webcam import WebcamManager
from core.chat_manager import ChatManager

BASE_DIR = Path(__file__).resolve().parent

SYSTEM_NAME = "J.A.R.V.I.S"
MODEL_BADGE = "VOICE CORE · Windows"

# -- Renk paleti --------------------------------------------------------------
C_BG      = "#020c0c"
C_PRI     = "#00d4c0"
C_ORG     = "#ff6600"
C_ORG2    = "#ff9900"
C_MID     = "#006a62"
C_DIM     = "#0a2a28"
C_DIMMER  = "#061414"
C_TEXT    = "#7dfff6"
C_PANEL   = "#030f0f"
C_GREEN   = "#00ff88"
C_RED     = "#ff3344"
C_MUTED   = "#cc2255"
C_BLUE    = "#4488ff"
C_GOLD    = "#ffcc00"

# Orb durum renkleri
ORB_COLORS = {
    "LISTENING":    (0, 255, 136),
    "SPEAKING":     (68, 136, 255),
    "THINKING":     (255, 204, 0),
    "MUTED":        (200, 30, 80),
    "PAUSED":       (30, 60, 55),
    "ERROR":        (255, 51, 68),
    "INITIALISING": (255, 51, 68),
}

# -- Boyutlar -----------------------------------------------------------------
W_TARGET = 2200
H_TARGET = 1320
LEFT_W_T = 360
RIGHT_W_T = 410
HDR_H    = 72
FOOTER_H = 26
INPUT_H  = 34
CONTROL_H = 146

VOICES = ["Charon", "Puck", "Aoede", "Kore", "Fenrir", "Leda", "Orus", "Zephyr"]
LANG_VOICE_MAP = {
    "tr": "Charon",
    "en": "Puck",
}

# -- Font sistemi -------------------------------------------------------------
# Orbitron gibi özel fontlar sistemde yoksa Tkinter'de metinler bozulabilir;
# Windows'ta Türkçe/Latin karakterler için güvenli varsayılan olarak Segoe UI
# kullanıyoruz. Bu, arayüz metinlerinin kararlı görünmesini sağlar.
FONT_BODY_FAMILY = "Segoe UI"
FONT_DISPLAY_FAMILY = "Segoe UI"


def font_body(size: int):
    return (FONT_BODY_FAMILY, size)


def font_body_bold(size: int):
    return (FONT_BODY_FAMILY, size, "bold")


def font_display(size: int):
    return (FONT_DISPLAY_FAMILY, size)


STATE_HEX_COLORS = {
    "LISTENING": C_GREEN,
    "SPEAKING": C_BLUE,
    "THINKING": C_GOLD,
    "INITIALISING": C_RED,
    "ERROR": C_RED,
}


# -- SoundManager -------------------------------------------------------------

def _resolve_sfx_dir() -> Path:
    return BASE_DIR / "SFX"


_SFX_DIR = _resolve_sfx_dir()
_HUD_FILE = _SFX_DIR / "HUD.mp3"
_START_FILE = _SFX_DIR / "Start.mp3"
_THINK_FILE = _SFX_DIR / "Think.mp3"
_DONE_FILE = _SFX_DIR / "Done.mp3"
_ERROR_FILE = _SFX_DIR / "Error.mp3"
_CLICK_FILE = _SFX_DIR / "Click.mp3"

# Windows MCI (winmm) — MP3 çalmada subprocess'e göre çok daha hızlı ve kararlı.
_MCI = ctypes.windll.winmm.mciSendStringW
_MCI_ERR = ctypes.windll.winmm.mciGetErrorStringW

def _mci_cmd(command: str) -> int:
    return int(_MCI(command, None, 0, 0))

def _mci_status(alias: str) -> str:
    buf = ctypes.create_unicode_buffer(256)
    if int(_MCI(f"status {alias} mode", buf, ctypes.sizeof(buf), 0)) != 0:
        return ""
    return buf.value.strip()

class _MCISound:
    """MCI (winmm) ses oynatıcısını subprocess.Popen benzeri bir sarmalar.."""

    __slots__ = ("_alias", "_started", "_closed")

    def __init__(self, alias: str, started: bool = True):
        self._alias = alias
        self._started = started
        self._closed = False

    def poll(self):
        if self._closed or not self._started:
            return 0
        mode = _mci_status(self._alias)
        if mode in ("playing", "paused", "seeking", "not ready", "open"):
            return None
        self.close()
        return 0

    def terminate(self):
        self.close()

    def kill(self):
        self.close()

    def wait(self, timeout=None):
        self.close()
        return 0

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._started:
            _mci_cmd(f"stop {self._alias}")
            _mci_cmd(f"close {self._alias}")


class SoundManager:
    def __init__(self):
        self._enabled = True
        self._ambient_proc = None
        self._volume = 0.20
        self._ambient_stop = None
        self._ambient_thread = None
        self._foreground_proc = None
        self._foreground_stop = None
        self._foreground_thread = None
        self._foreground_tag = ""
        self._all_sound_procs = set()
        self._lock = threading.RLock()
        self._fg_gen = 0  # Bayat foreground worker'ları öldürmek için nesil sayacı
        self._last_vol_restart = 0.0
        self._vol_trailing_timer = None
        self._seq = 0  # MCI alias üretici
        self._ambient_blocked = False  # LISTENING iken ambient drone çalmasın
        self._last_click_ts = 0.0
        self._click_aliases = []
        self._sfx_check = None

    @staticmethod
    def _terminate_process(proc):
        if not proc:
            return
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=0.6)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=0.3)
            except Exception:
                pass

    def _start_sound_proc(self, path: Path, volume: float, loop: bool = False):
        # MP3 çalma: Windows MCI (winmm) — anında başlar, subprocess yok, yarım kesilme olmaz.
        with self._lock:
            self._seq += 1
            alias = f"jk{self._seq}"
        path_str = str(path).replace("\\", "/")
        err = _mci_cmd(f'open "{path_str}" type mpegvideo alias {alias}')
        if err != 0:
            return _MCISound(alias, started=False)
        vol = max(0, min(1000, int(volume * 1000)))
        _mci_cmd(f"setaudio {alias} volume to {vol}")
        _mci_cmd(f"play {alias}{' repeat' if loop else ''}")
        ps = _MCISound(alias)
        with self._lock:
            self._all_sound_procs.add(ps)
        return ps

    def _forget_process(self, proc):
        if not proc:
            return
        with self._lock:
            self._all_sound_procs.discard(proc)

    def start_ambient(self):
        if not _HUD_FILE.exists():
            return
        with self._lock:
            if self._ambient_blocked or not self._enabled:
                return
            if self._foreground_proc and self._foreground_proc.poll() is None:
                return
            if self._ambient_thread and self._ambient_thread.is_alive():
                return
            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._loop_ambient,
                args=(stop_event,),
                daemon=True,
            )
            self._ambient_stop = stop_event
            self._ambient_thread = worker
        worker.start()

    def _loop_ambient(self, stop_event: threading.Event):
        while not stop_event.is_set():
            with self._lock:
                if not self._enabled or self._ambient_stop is not stop_event:
                    break
                volume = self._volume
            try:
                proc = self._start_sound_proc(_HUD_FILE, volume, loop=True)
            except Exception:
                break

            with self._lock:
                if self._ambient_stop is not stop_event or not self._enabled:
                    self._terminate_process(proc)
                    self._forget_process(proc)
                    break
                self._ambient_proc = proc

            while proc.poll() is None and not stop_event.wait(0.2):
                pass

            if stop_event.is_set():
                self._terminate_process(proc)

            with self._lock:
                if self._ambient_proc is proc:
                    self._ambient_proc = None
            if proc.poll() is not None:
                self._forget_process(proc)

            if stop_event.is_set():
                break
            time.sleep(0.2)

        with self._lock:
            if self._ambient_stop is stop_event:
                self._ambient_stop = None
            if self._ambient_thread and self._ambient_thread.ident == threading.get_ident():
                self._ambient_thread = None

    def stop_ambient(self):
        self._stop_ambient()

    def set_ambient_blocked(self, blocked: bool):
        self._ambient_blocked = bool(blocked)

    def _stop_ambient(self):
        with self._lock:
            stop_event = self._ambient_stop
            proc = self._ambient_proc
            self._ambient_stop = None
            self._ambient_thread = None
            self._ambient_proc = None
        if stop_event:
            stop_event.set()
        self._terminate_process(proc)
        self._forget_process(proc)

    def _stop_foreground(self):
        with self._lock:
            stop_event = self._foreground_stop
            proc = self._foreground_proc
            self._foreground_stop = None
            self._foreground_thread = None
            self._foreground_proc = None
            self._foreground_tag = ""
            self._fg_gen += 1
        if stop_event:
            stop_event.set()
        self._terminate_process(proc)
        self._forget_process(proc)

    def silence_all_loops(self):
        with self._lock:
            procs = list(self._all_sound_procs)
        for proc in procs:
            if isinstance(proc, _MCISound) and proc.poll() is None:
                proc.terminate()
                self._forget_process(proc)

    def _play_foreground(
        self,
        path: Path,
        tag: str,
        loop: bool = False,
        volume_factor: float = 1.0,
        pause_ambient: bool = True,
    ):
        if not path.exists():
            return
        with self._lock:
            if not self._enabled:
                return
            if loop and self._foreground_tag == tag and self._foreground_thread and self._foreground_thread.is_alive():
                return
            base_volume = self._volume
        if pause_ambient:
            self._stop_ambient()
        self._stop_foreground()

        stop_event = threading.Event()
        with self._lock:
            self._fg_gen += 1
            gen = self._fg_gen
        worker = threading.Thread(
            target=self._foreground_worker,
            args=(
                path,
                tag,
                stop_event,
                loop,
                max(0.0, min(1.0, base_volume * volume_factor)),
                pause_ambient,
                gen,
            ),
            daemon=True,
        )
        with self._lock:
            self._foreground_stop = stop_event
            self._foreground_thread = worker
            self._foreground_tag = tag
        worker.start()

    def _foreground_worker(
        self,
        path: Path,
        tag: str,
        stop_event: threading.Event,
        loop: bool,
        volume: float,
        resume_ambient: bool,
        gen: int = 0,
    ):
        def _stale() -> bool:
            with self._lock:
                return gen != self._fg_gen

        while not stop_event.is_set():
            if _stale():
                break
            try:
                proc = self._start_sound_proc(path, volume, loop=loop)
            except Exception:
                break

            with self._lock:
                if gen != self._fg_gen:
                    self._terminate_process(proc)
                    self._forget_process(proc)
                    break
                if self._foreground_stop is not stop_event or not self._enabled:
                    self._terminate_process(proc)
                    self._forget_process(proc)
                    break
                self._foreground_proc = proc

            while proc.poll() is None and not stop_event.wait(0.12):
                pass

            if stop_event.is_set():
                self._terminate_process(proc)

            with self._lock:
                if self._foreground_proc is proc:
                    self._foreground_proc = None
            if proc.poll() is not None:
                self._forget_process(proc)

            if not loop or stop_event.is_set() or _stale():
                break
            time.sleep(0.08)

        with self._lock:
            if self._foreground_stop is stop_event:
                self._foreground_stop = None
                self._foreground_thread = None
                self._foreground_tag = ""
            should_restart = resume_ambient and self._enabled and self._foreground_stop is None
        if should_restart:
            self.start_ambient()

    def play_startup(self):
        self._play_foreground(_START_FILE, tag="start", loop=False, volume_factor=0.95)

    def play_success(self):
        self._play_foreground(
            _DONE_FILE,
            tag="done",
            loop=False,
            volume_factor=0.68,
            pause_ambient=False,
        )

    def play_error(self):
        self._play_foreground(_ERROR_FILE, tag="error", loop=False, volume_factor=0.95)

    def play_click(self):
        now = time.monotonic()
        with self._lock:
            if self._sfx_check and not self._sfx_check():
                return
            if now - self._last_click_ts < 0.12:
                return
            self._last_click_ts = now
            self._seq += 1
            alias = f"jk{self._seq}"
            volume = self._volume
            self._click_aliases.append(alias)
        if not _CLICK_FILE.exists():
            return
        err = _mci_cmd(f'open "{str(_CLICK_FILE).replace(chr(92), "/")}" type mpegvideo alias {alias}')
        if err != 0:
            return
        vol = max(0, min(1000, int(volume * 0.9 * 1000)))
        _mci_cmd(f"setaudio {alias} volume to {vol}")
        _mci_cmd(f"play {alias}")
        def _close():
            _mci_cmd(f"close {alias}")
            with self._lock:
                if alias in self._click_aliases:
                    self._click_aliases.remove(alias)
        closer = threading.Timer(0.8, _close)
        closer.daemon = True
        closer.start()

    def stop_all_clicks(self):
        with self._lock:
            aliases = list(self._click_aliases)
        for alias in aliases:
            _mci_cmd(f"stop {alias}")
            _mci_cmd(f"close {alias}")
        with self._lock:
            self._click_aliases.clear()

    def start_thinking(self, current_state: str = ""):
        pass

    def stop_thinking(self):
        with self._lock:
            is_thinking = self._foreground_tag == "think"
        if is_thinking:
            self._stop_foreground()

    def toggle(self) -> bool:
        self.set_enabled(not self._enabled)
        return self._enabled

    def set_enabled(self, enabled: bool):
        enabled = bool(enabled)
        with self._lock:
            self._enabled = enabled
        if enabled:
            self.start_ambient()
        else:
            self._stop_ambient()
            self._stop_foreground()

    def set_volume(self, volume: float):
        with self._lock:
            self._volume = max(0.0, min(1.0, float(volume)))
            procs = list(self._all_sound_procs)
        v = max(0, min(1000, int(self._volume * 1000)))
        # MCI her sesin sesini anında değiştirebildiği için restart gerekmez;
        # çalan tüm oynatıcılara yeni seviye uygula.
        for ps in procs:
            if isinstance(ps, _MCISound):
                _mci_cmd(f"setaudio {ps._alias} volume to {v}")

    def stop_all(self):
        self.stop_all_clicks()
        with self._lock:
            self._enabled = False
            ambient_stop = self._ambient_stop
            foreground_stop = self._foreground_stop
            procs = {
                proc
                for proc in (
                    self._ambient_proc,
                    self._foreground_proc,
                    *self._all_sound_procs,
                )
                if proc
            }
            self._ambient_stop = None
            self._ambient_thread = None
            self._ambient_proc = None
            self._foreground_stop = None
            self._foreground_thread = None
            self._foreground_proc = None
            self._foreground_tag = ""
            self._fg_gen += 1
            self._all_sound_procs.clear()
        if ambient_stop:
            ambient_stop.set()
        if foreground_stop:
            foreground_stop.set()
        for proc in procs:
            self._terminate_process(proc)

    def get_volume(self) -> float:
        return self._volume


# -----------------------------------------------------------------------------

class JarvisUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S")
        self.root.update_idletasks()

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        margin_x = max(24, int(sw * 0.025))
        margin_y = max(54, int(sh * 0.055))
        self.W = min(max(640, sw - margin_x), sw, W_TARGET)
        self.H = min(max(520, sh - margin_y), sh, H_TARGET)
        _geo = f"{self.W}x{self.H}+{(sw-self.W)//2}+{max(0, (sh-self.H)//2 - 8)}"
        self.root.geometry(_geo)
        self.root.minsize(min(self.W, sw), min(self.H, sh))
        self.root.resizable(True, True)
        self.root.configure(bg=C_BG)
        self.root.attributes('-topmost', True)
        self.root.lift()
        self.root.focus_force()
        # macOS window manager bazen geometry'yi override eder, tekrar zorla.
        for delay in (80, 220, 600, 1200):
            self.root.after(delay, self._force_startup_size)
        # Birkaç saniye sonra topmost'u kapat (normal davranış)
        self.root.after(3000, lambda: self.root.attributes('-topmost', False))

        self._window_geometry = _geo
        self._normal_size = (self.W, self.H)
        self._fullscreen = True

        self._set_layout_metrics(self.W, self.H)

        # -- State ------------------------------------------------------------
        self.speaking        = False
        self.user_speaking   = False
        self.muted           = False
        self.paused          = False
        self._last_toggle_ts = 0.0
        self.scale           = 1.0
        self.target_scale    = 1.0
        self.halo_a          = 55.0
        self.target_halo     = 55.0
        self.last_t          = time.time()
        self.tick            = 0
        self.rings_spin      = [0.0, 45.0, 90.0, 200.0]  # 4 ayrı halka
        self.pulse_r         = []
        self.status_blink    = True
        self._jarvis_state   = "INITIALISING"
        self._user_speaking_until = 0.0

        # -- Health overlay ---------------------------------------------------
        self._health_visible  = False
        self._health_query    = "all"
        self._health_display  = ""
        self._health_hide_job = None
        self._weather_card = {
            "city": "Istanbul",
            "primary": "--",
            "details": ["Hava durumu yükleniyor..."],
        }
        self._health_card_lines = ["Sağlık özeti yükleniyor..."]
        self._panel_focus = ""
        self._panel_focus_until = 0.0
        self._brief_refresh_busy = False
        self._weather_req_id = 0
        self._started_at = time.time()
        self._error_hold_until = 0.0
        self._settings_open = False
        self._settings_tab = "settings"
        self._debug_entries = deque(maxlen=160)
        self._startup_sfx_played = False
        self._settings_geometry = {
            "btn_x": 14,
            "btn_y": 12,
            "btn_w": 300,
            "btn_h": 46,
            "panel_x": 14,
            "panel_y": HDR_H + 10,
            "panel_w": 380,
            "panel_h": 420,
        }
        self.setup_frame = None
        self.api_entry = None
        self.openrouter_api_entry = None

        # -- Callbacks --------------------------------------------------------
        self.on_text_command = None
        self.on_pause_toggle = None
        self.on_stop_command = None
        self.on_minimize_to_tray = None
        self.on_voice_change = None
        self.on_effects_state_change = None
        self.on_send_media = None
        self.on_main_menu_show = None

        # -- Voice ------------------------------------------------------------
        self._current_voice = self._load_voice()

        # -- Sound ------------------------------------------------------------
        self.sound = SoundManager()
        self.sound._sfx_check = lambda: self._sfx_on

        # -- Webcam ----------------------------------------------------------
        self.webcam = WebcamManager()
        self._webcam_window = None
        self._webcam_canvas = None
        self._webcam_photo = None
        self._webcam_feed_active = False
        self._media_queue = []
        self.chat_mgr = ChatManager()

        # -- Stats ------------------------------------------------------------
        self._stats        = {'cpu': 0.0, 'ram': 0.0, 'disk': 0.0,
                              'battery': 100.0,
                              'speed_down': 0.0, 'speed_up': 0.0}
        self._cpu_hist     = [0.0] * 24
        self._speed_meter  = SpeedMeter(interval=1)
        self._speed_meter.start()
        self._stats_running = True
        # Görev Yöneticisi gibi sürekli (1 sn aralıklı) ölçüm yapan daemon thread
        threading.Thread(target=self._stats_probe, daemon=True).start()
        self._wave_jarvis = [random.randint(4, 26) for _ in range(18)]
        self._wave_user   = [random.randint(2, 10) for _ in range(18)]

        # -- Typing -----------------------------------------------------------
        self.typing_queue = deque()
        self.is_typing    = False
        # -- Uzman model akışı (streaming) ------------------------------------
        self._stream_buffer         = deque()
        self._stream_flush_scheduled = False
        self._stream_active         = False

        # -- Partiküller (arka plan, az sayıda) -------------------------------
        self.particles = [
            {
                'x':  random.uniform(0, self.W),
                'y':  random.uniform(0, self.H),
                'vx': random.uniform(-0.15, 0.15),
                'vy': random.uniform(-0.15, 0.15),
                'r':  random.uniform(0.5, 1.8),
                'a':  random.randint(15, 70),
            }
            for _ in range(24)
        ]

        self.orb_particles = [
            {
                'angle': random.uniform(0, math.tau),
                'orbit': random.uniform(0.06, 0.98),
                'speed': random.uniform(-0.030, 0.030),
                'size': random.uniform(0.8, 2.8),
                'phase': random.uniform(0, math.tau),
                'wobble': random.uniform(0.010, 0.040),
                'depth': random.uniform(0.30, 1.00),
            }
            for _ in range(160)
        ]
        self.orb_shell_particles = [
            {
                'angle': random.uniform(0, math.tau),
                'speed': random.uniform(-0.020, 0.020),
                'size': random.uniform(1.4, 3.8),
                'phase': random.uniform(0, math.tau),
                'glow': random.uniform(0.4, 1.0),
            }
            for _ in range(84)
        ]

        # -- Canvas -----------------------------------------------------------
        self.bg = tk.Canvas(self.root, width=self.W, height=self.H,
                            bg=C_BG, highlightthickness=0)
        self.bg.place(x=0, y=0)

        # -- Log --------------------------------------------------------------
        self.log_frame = tk.Frame(self.root, bg="#030e0e",
                                  highlightbackground=C_MID,
                                  highlightthickness=1)
        self.log_frame.place(x=self.CHAT_X, y=self.CHAT_Y,
                             width=self.CHAT_W, height=self.CHAT_H)
        self.log_text = tk.Text(
            self.log_frame, fg=C_TEXT, bg="#030e0e",
            insertbackground=C_TEXT, borderwidth=0,
            wrap="word", font=font_body(12), padx=12, pady=8)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        self.log_text.tag_config("you", foreground="#d0f0ee")
        self.log_text.tag_config("ai",  foreground=C_PRI)
        self.log_text.tag_config("sys", foreground=C_GOLD)
        self.log_text.tag_config("err", foreground=C_RED)
        self.log_text.tag_config("expert", foreground="#ffcc88")

        # -- Chat Sidebar --------------------------------------------------
        self._sidebar_open = False
        self._sidebar_w = 200
        self._sidebar_frame = tk.Frame(self.root, bg="#020a0a",
                                       highlightbackground=C_DIM,
                                       highlightthickness=1)

        self._sidebar_new_btn = tk.Button(
            self._sidebar_frame, text=f"+ {T('NEW CHAT')}",
            fg=C_BG, bg=C_PRI, activeforeground=C_BG, activebackground=C_MID,
            font=font_body_bold(10), bd=0, cursor="hand2",
            command=self._new_chat)
        self._sidebar_new_btn.pack(fill="x", padx=0, pady=0)

        self._sidebar_conv_frame = tk.Frame(self._sidebar_frame, bg="#020a0a")
        self._sidebar_conv_frame.pack(fill="both", expand=True, padx=0, pady=0)

        self._sidebar_canvas = tk.Canvas(self._sidebar_conv_frame, bg="#020a0a", highlightthickness=0)
        self._sidebar_scrollbar = tk.Scrollbar(self._sidebar_conv_frame, orient="vertical", command=self._sidebar_canvas.yview)
        self._sidebar_inner = tk.Frame(self._sidebar_canvas, bg="#020a0a")
        self._sidebar_inner.bind("<Configure>", lambda e: self._sidebar_canvas.configure(scrollregion=self._sidebar_canvas.bbox("all")))
        self._sidebar_canvas.create_window((0, 0), window=self._sidebar_inner, anchor="nw")
        self._sidebar_canvas.configure(yscrollcommand=self._sidebar_scrollbar.set)
        self._sidebar_scrollbar.pack(side="right", fill="y")
        self._sidebar_canvas.pack(side="left", fill="both", expand=True)
        self._sidebar_canvas.bind_all("<MouseWheel>", lambda e: self._sidebar_canvas.yview_scroll(-1 * (e.delta // 120), "units") if self._sidebar_open else None)

        # Sidebar toggle butonu — sol panelde, system kartının altında
        btn_y = int(HDR_H + (self.H - HDR_H - FOOTER_H) * 0.78)
        self._sidebar_toggle_btn = tk.Button(
            self.root, text=T("CHATS"), fg=C_PRI, bg="#041111",
            activeforeground=C_BG, activebackground=C_MID,
            font=font_body_bold(9), bd=0, cursor="hand2",
            command=self.toggle_sidebar)
        self._sidebar_toggle_btn.place(x=10, y=btn_y, width=self.LEFT_W - 18, height=22)

        self._build_input_bar(self.CHAT_W)
        self._build_mute_button()
        self._build_pause_button()
        self._build_webcam_button()
        self._build_shutdown_button()
        self._build_tray_button()
        self._build_settings_panel()
        self._build_voice_selector(self._settings_body)
        self._build_lang_selector(self._settings_body)
        self._build_model_selector(self._settings_body)
        self._build_sfx_button(self._settings_body)
        self._build_api_button(self._settings_body)
        self._build_fx_slider(self._settings_body)
        self._layout_settings_controls()
        self._place_layout_widgets()

        # Orb tıklama = pause/resume
        self.bg.bind("<Button-1>", self._on_canvas_click)

        self.root.bind("<F4>",        lambda e: self._toggle_mute())
        self.root.bind("<Control-m>", lambda e: self._toggle_mute())
        self.root.bind("<Escape>",    lambda e: self._shutdown())
        self.root.bind("<F5>",        lambda e: self._toggle_pause())
        self.root.bind("<F11>",       lambda e: self._toggle_fullscreen())
        self.root.bind("<Control-f>", lambda e: self._toggle_fullscreen())

        self._api_key_ready = has_gemini_api_key()
        if not self._api_key_ready:
            self._show_setup_ui()

        self._effects_active = None
        self._sync_sound_state()
        self.root.after(180, self._play_startup_sfx_once)
        self._kick_brief_refresh()
        self._build_social_bar()
        self.root.after(120, self._enter_fullscreen)
        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", self._shutdown)

    def _force_startup_size(self):
        if self._fullscreen:
            self._enter_fullscreen()
            return
        self.root.geometry(self._window_geometry)
        self._resize_surface(*self._normal_size)
        self.root.update_idletasks()

    def _enter_fullscreen(self):
        sw = max(self.root.winfo_screenwidth(), self.root.winfo_width(), self.W)
        sh = max(self.root.winfo_screenheight(), self.root.winfo_height(), self.H)
        self.root.attributes("-fullscreen", True)
        self.root.geometry(f"{sw}x{sh}+0+0")
        self._resize_surface(sw, sh)

    def _set_layout_metrics(self, width: int, height: int):
        self.W = int(width)
        self.H = int(height)
        self.LEFT_W = min(LEFT_W_T, int(self.W * 0.23))
        self.RIGHT_W = min(RIGHT_W_T, int(self.W * 0.25))
        center_w = self.W - self.LEFT_W - self.RIGHT_W
        orb_area_h = self.H - HDR_H - CONTROL_H - FOOTER_H - 24
        self.FCX = self.LEFT_W + center_w // 2
        self.FCY = HDR_H + orb_area_h // 2 + 6
        self.FACE = min(int(orb_area_h * 0.90), int(center_w * 0.86), 860)

        self.CENTER_X0 = self.LEFT_W
        self.CENTER_X1 = self.W - self.RIGHT_W
        self.CTRL_X = self.LEFT_W + 18
        self.CTRL_Y = HDR_H + orb_area_h + 2
        self.CTRL_W = center_w - 36
        self.CHAT_PANEL_X = self.W - self.RIGHT_W + 8
        self.CHAT_PANEL_Y = HDR_H + 8
        self.CHAT_PANEL_W = self.RIGHT_W - 14
        self.CHAT_PANEL_H = self.H - HDR_H - FOOTER_H - 16
        self.CHAT_X = self.CHAT_PANEL_X + 10
        self.CHAT_Y = self.CHAT_PANEL_Y + 34
        self.CHAT_W = self.CHAT_PANEL_W - 20
        self.CHAT_H = self.CHAT_PANEL_H - 90
        self.CHAT_INPUT_Y = self.CHAT_PANEL_Y + self.CHAT_PANEL_H - INPUT_H - 10

    # -- Social bar -----------------------------------------------------------
    def _build_social_bar(self):
        pass

    # -- Voice -----------------------------------------------------------------
    def _load_voice(self) -> str:
        try:
            return str(load_app_config().get("voice", "Charon") or "Charon")
        except Exception:
            return "Charon"

    # -- Shutdown button (sağ alt, büyük) ------------------------------------
    
    def _build_tray_button(self):
        BW, BH = 140, 36
        self._tray_canvas = tk.Canvas(
            self.root, width=BW, height=BH,
            bg="#050f10", highlightthickness=0, cursor="hand2")
        self._tray_canvas.bind("<Button-1>", self._on_tray_click)
        self._draw_tray_button()

    def _on_tray_click(self, event):
        self.sound.play_click()
        if self.on_minimize_to_tray:
            self.on_minimize_to_tray()

    def _draw_tray_button(self):
        c = self._tray_canvas
        BW, BH = 140, 36
        c.delete("all")
        bl = 8
        for bx, by, sx, sy in [(0, 0, 1, 1), (BW, 0, -1, 1), (0, BH, 1, -1), (BW, BH, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill="#00e6c3", width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill="#00e6c3", width=2)
        c.create_text(BW//2, BH//2, text=T('TRAY'), fill="#00e6c3", font=("Segoe UI", 11, "bold"))

    def _build_shutdown_button(self):
        BW, BH = 160, 36
        self._shutdown_canvas = tk.Canvas(
            self.root, width=BW, height=BH,
            bg=C_BG, highlightthickness=0, cursor="hand2")
        self._shutdown_canvas.bind("<Button-1>", lambda e: self._shutdown())
        self._draw_shutdown_button()

    def _draw_shutdown_button(self):
        c = self._shutdown_canvas
        BW, BH = 160, 36
        c.delete("all")
        # Köşe braket stili
        bl = 8
        for bx, by, sx, sy in [(0, 0, 1, 1), (BW, 0, -1, 1),
                                (0, BH, 1, -1), (BW, BH, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=C_RED, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=C_RED, width=2)
        c.create_text(BW//2, BH//2, text=f"\u23fb  {T('SHUTDOWN')}",
                      fill=C_RED, font=font_display(11))

    def _build_settings_panel(self):
        geo = self._settings_geometry
        self._settings_btn_canvas = tk.Canvas(
            self.root,
            width=geo["btn_w"],
            height=geo["btn_h"],
            bg=C_BG,
            highlightthickness=0,
            cursor="hand2",
        )
        self._settings_btn_canvas.place(x=geo["btn_x"], y=geo["btn_y"])
        self._settings_btn_canvas.bind("<Button-1>", lambda e: self._toggle_settings_panel())
        self._draw_settings_button()

        self._settings_panel = tk.Frame(
            self.root,
            bg="#041111",
            highlightbackground=C_MID,
            highlightthickness=1,
        )
        self._settings_panel.place_forget()

        self._settings_title = tk.Label(
            self._settings_panel,
            text=T("SETTINGS"),
            fg=C_PRI,
            bg="#041111",
            font=font_display(11),
        )
        self._settings_tab_settings = tk.Canvas(
            self._settings_panel,
            width=108,
            height=28,
            bg="#041111",
            highlightthickness=0,
            cursor="hand2",
        )
        self._settings_tab_settings.bind("<Button-1>", lambda e: self._set_settings_tab("settings"))
        self._settings_tab_debug = tk.Canvas(
            self._settings_panel,
            width=195,
            height=28,
            bg="#041111",
            highlightthickness=0,
            cursor="hand2",
        )
        self._settings_tab_debug.bind("<Button-1>", lambda e: self._set_settings_tab("debug"))
        self._settings_body = tk.Frame(self._settings_panel, bg="#041111")
        self._debug_body = tk.Frame(self._settings_panel, bg="#041111")
        self._settings_sfx_label = tk.Label(
            self._settings_body,
            text=T("SFX"),
            fg=C_MID,
            bg="#041111",
            font=font_body_bold(8),
        )
        self._settings_status_primary = tk.Label(
            self._settings_body,
            text="",
            fg=C_TEXT,
            bg="#041111",
            font=font_body_bold(9),
            anchor="w",
            justify="left",
        )
        self._settings_status_secondary = tk.Label(
            self._settings_body,
            text="",
            fg=C_MID,
            bg="#041111",
            font=font_body(9),
            anchor="w",
            justify="left",
        )
        self._debug_text = tk.Text(
            self._debug_body,
            fg=C_TEXT,
            bg="#020a0a",
            insertbackground=C_TEXT,
            borderwidth=0,
            wrap="word",
            font=font_body(10),
            padx=10,
            pady=10,
            highlightthickness=1,
            highlightbackground=C_DIM,
        )
        self._debug_text.tag_config("info", foreground=C_TEXT)
        self._debug_text.tag_config("warn", foreground=C_GOLD)
        self._debug_text.tag_config("err", foreground=C_RED)
        self._debug_text.configure(state="disabled")
        self._draw_settings_tabs()
        self._render_debug_logs()
        self._refresh_settings_status()

    def _draw_settings_button(self):
        c = self._settings_btn_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        accent = C_BLUE if self._settings_open else C_MID
        inner = "#062020" if self._settings_open else "#021010"
        c.create_rectangle(0, 0, bw, bh, fill=inner, outline="")
        bl = 9
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1), (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx + sx * bl, by, fill=accent, width=2)
            c.create_line(bx, by, bx, by + sy * bl, fill=accent, width=2)
        c.create_text(14, 15, text=T("SYSTEM SETTINGS"), fill=C_PRI, font=font_display(10), anchor="w")
        c.create_text(14, 33, text=MODEL_BADGE, fill="#4f7b78", font=font_body(9), anchor="w")
        c.create_text(bw - 14, bh // 2, text="\u25be" if self._settings_open else "\u25b8",
                      fill=accent, font=font_display(14), anchor="e")

    def _toggle_settings_panel(self):
        self.sound.play_click()
        self._settings_open = not self._settings_open
        self._draw_settings_button()
        self._place_layout_widgets()

    def _draw_settings_tabs(self):
        for key, canvas, label in (
            ("settings", self._settings_tab_settings, T("SETTINGS")),
            ("debug", self._settings_tab_debug, T("DEBUG")),
        ):
            active = self._settings_tab == key
            bw = int(canvas["width"])
            bh = int(canvas["height"])
            canvas.delete("all")
            outline = C_PRI if active else C_DIM
            fill = "#082020" if active else "#041111"
            text_col = C_PRI if active else "#5ea7a0"
            canvas.create_rectangle(0, 0, bw, bh, fill=fill, outline="")
            bl = 7
            for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1), (0, bh, 1, -1), (bw, bh, -1, -1)]:
                canvas.create_line(bx, by, bx + sx * bl, by, fill=outline, width=1)
                canvas.create_line(bx, by, bx, by + sy * bl, fill=outline, width=1)
            canvas.create_text(bw // 2, bh // 2, text=label, fill=text_col, font=font_body_bold(9))

    def _set_settings_tab(self, tab: str):
        self.sound.play_click()
        self._settings_tab = "debug" if tab == "debug" else "settings"
        self._draw_settings_tabs()
        self._place_layout_widgets()

    def _layout_settings_controls(self):
        inner_w = self._settings_geometry["panel_w"] - 24
        api_w = int(self._api_canvas["width"])
        sfx_w = int(self._sfx_canvas["width"])
        self._api_canvas.place(x=0, y=0)
        self._sfx_canvas.place(x=api_w + 8, y=0)
        self._settings_status_primary.place(x=0, y=38, width=inner_w)
        self._settings_status_secondary.place(x=0, y=58, width=inner_w)
        self._settings_sfx_label.place(x=0, y=92)
        self._volume_label.place(x=0, y=116)
        self._volume_scale.place(x=0, y=136, width=inner_w, height=26)
        self._voice_label.place(x=0, y=168)
        self._voice_menu.place(x=88, y=162, width=inner_w - 88, height=28)
        self._lang_label.place(x=0, y=208)
        self._lang_menu.place(x=88, y=202, width=inner_w - 88, height=28)
        self._model_label.place(x=0, y=244)
        self._model_menu.place(x=88, y=238, width=inner_w - 88, height=30)

    def _refresh_settings_status(self):
        if not hasattr(self, "_settings_status_primary"):
            return
        cfg = load_app_config()
        gemini_ready = bool(str(cfg.get("gemini_api_key", "") or "").strip())
        or_ready = bool(str(cfg.get("openrouter_api_key", "") or "").strip())

        primary = [
            f"{T('GEMINI READY')}" if gemini_ready else f"{T('GEMINI MISSING')}",
            f"{T('OPENROUTER READY')}" if or_ready else f"{T('OPENROUTER MISSING')}",
        ]
        
        current_engine = str(cfg.get("ai_engine", "gemini"))
        secondary = f"{T('ACTIVE ENGINE')}: {current_engine.upper()}"

        self._settings_status_primary.configure(text="  ·  ".join(primary))
        self._settings_status_secondary.configure(text=secondary)

    def write_debug(self, text: str, level: str = "INFO"):
        clean = " ".join(str(text or "").split())
        if not clean:
            return
        self.root.after(0, self._append_debug_entry, clean, level)

    def _append_debug_entry(self, text: str, level: str = "INFO"):
        stamp = time.strftime("%H:%M:%S")
        lvl = (level or "INFO").upper()
        self._debug_entries.append((lvl, f"[{stamp}] {lvl}: {text}"))
        self._render_debug_logs()

    def _render_debug_logs(self):
        if not hasattr(self, "_debug_text"):
            return
        self._debug_text.configure(state="normal")
        self._debug_text.delete("1.0", tk.END)
        if not self._debug_entries:
            self._debug_text.insert(tk.END, "Henüz not edilebilir hata yok.\n", "info")
        else:
            for level, line in self._debug_entries:
                tag = "err" if level == "ERROR" else "warn" if level == "WARN" else "info"
                self._debug_text.insert(tk.END, line + "\n", tag)
        self._debug_text.see(tk.END)
        self._debug_text.configure(state="disabled")

    def _build_api_button(self, parent=None):
        parent = parent or self.root
        bw, bh = 154, 28
        self._api_canvas = tk.Canvas(
            parent, width=bw, height=bh,
            bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self._api_canvas.bind("<Button-1>", self._on_api_click)
        self._draw_api_button()

    def _on_api_click(self, event):
        self.sound.play_click()
        self._open_api_settings()

    def _draw_api_button(self):
        c = self._api_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1), (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx + sx * bl, by, fill=C_BLUE, width=1)
            c.create_line(bx, by, bx, by + sy * bl, fill=C_BLUE, width=1)
        c.create_text(bw // 2, bh // 2, text=f"\u2699 {T('API SETTINGS')}",
                      fill=C_BLUE, font=font_body_bold(10))

    def _build_fx_slider(self, parent=None):
        parent = parent or self.root
        slider_w = 280
        self._volume_label = tk.Label(
            parent,
            text=f"{T('FX LEVEL')} {int(self.sound.get_volume() * 100)}%",
            fg=C_PRI,
            bg=parent.cget("bg"),
            font=font_body_bold(10),
        )
        self._volume_scale = tk.Scale(
            parent,
            from_=0,
            to=100,
            orient="horizontal",
            length=slider_w,
            showvalue=False,
            resolution=1,
            troughcolor="#071818",
            bg=parent.cget("bg"),
            fg=C_TEXT,
            activebackground=C_PRI,
            highlightthickness=0,
            borderwidth=0,
            sliderlength=18,
            width=10,
            command=self._on_volume_change,
        )
        self._volume_scale.set(int(self.sound.get_volume() * 100))

    def _on_volume_change(self, value):
        try:
            volume = max(0, min(100, int(float(value))))
        except (TypeError, ValueError):
            return
        self._volume_label.configure(text=f"{T('FX LEVEL')} {volume}%")
        self.sound.set_volume(volume / 100.0)

    def _play_startup_sfx_once(self):
        if self._startup_sfx_played or not self._sfx_on:
            return
        self._startup_sfx_played = True
        self.sound.play_startup()

    def _sync_sound_state(self):
        enabled = self._sfx_on and not self.paused
        self.sound.set_enabled(enabled)
        if enabled and self._jarvis_state == "THINKING":
            self.sound.start_thinking(self._jarvis_state)
        if enabled != self._effects_active:
            self._effects_active = enabled
            if self.on_effects_state_change:
                threading.Thread(
                    target=self.on_effects_state_change,
                    args=(enabled,),
                    daemon=True,
                ).start()

    def _open_api_settings(self):
        self._show_setup_ui(edit_mode=self._api_key_ready)

    def _close_setup_ui(self):
        if self.setup_frame and self.setup_frame.winfo_exists():
            self.setup_frame.destroy()
        self.setup_frame = None
        self.api_entry = None
        self.openrouter_api_entry = None

    # -- SFX toggle -----------------------------------------------------------
    def _build_sfx_button(self, parent=None):
        parent = parent or self.root
        BW, BH = 98, 36
        self._sfx_canvas = tk.Canvas(parent, width=BW, height=BH,
                                     bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self._sfx_canvas.bind("<Button-1>", lambda e: self._toggle_sfx())
        self._sfx_on = True
        self._draw_sfx_button()

    def _draw_sfx_button(self):
        c = self._sfx_canvas
        BW = int(c["width"])
        BH = int(c["height"])
        c.delete("all")
        col  = C_PRI if self._sfx_on else C_MID
        text = "\u266a SFX ON"  if self._sfx_on else "\u266a SFX OFF"
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (BW, 0, -1, 1),
                                (0, BH, 1, -1), (BW, BH, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=col, width=1)
            c.create_line(bx, by, bx, by+sy*bl, fill=col, width=1)
        c.create_text(BW//2, BH//2, text=text, fill=col, font=font_body_bold(9))

    def _toggle_sfx(self):
        now = time.monotonic()
        if now - self._last_toggle_ts < 0.35:
            return
        self._last_toggle_ts = now
        self.sound.play_click()
        self._sfx_on = not self._sfx_on
        self._draw_sfx_button()
        self._sync_sound_state()

    # -- Voice selector -------------------------------------------------------
    def _build_voice_selector(self, parent=None):
        parent = parent or self.root
        self._voice_var = tk.StringVar(value=self._current_voice)
        self._voice_label = tk.Label(parent, text=T("VOICE"), fg=C_MID, bg=parent.cget("bg"),
                                     font=font_body_bold(8))

        self._voice_menu = tk.OptionMenu(parent, self._voice_var, *VOICES,
                                         command=self._on_voice_select)
        self._voice_menu.config(
            fg=C_PRI, bg=C_PANEL, activeforeground=C_BG,
            activebackground=C_PRI, font=font_body(10),
            borderwidth=0, highlightthickness=1,
            highlightbackground=C_MID, width=12)
        self._voice_menu["menu"].config(
            fg=C_PRI, bg=C_PANEL, font=font_body(10),
            activeforeground=C_BG, activebackground=C_PRI)

    def _on_voice_select(self, voice: str):
        self.sound.play_click()
        self._current_voice = voice
        save_app_config({"voice": voice})
        self.write_log(f"SYS: Ses '{voice}' olarak ayarlandi. Yeni ses icin uygulamayi yeniden baslatin.")

    # -- Language selector ---------------------------------------------------------
    def _build_lang_selector(self, parent=None):
        parent = parent or self.root
        cfg = load_app_config()
        self._current_lang = str(cfg.get("ui_language", "tr")).upper()
        self._lang_var = tk.StringVar(value=self._current_lang)
        self._lang_label = tk.Label(parent, text=T("LANGUAGE"), fg=C_MID, bg=parent.cget("bg"), font=font_body_bold(8))

        langs = ["EN", "TR"]
        self._lang_menu = tk.OptionMenu(parent, self._lang_var, *langs, command=self._on_lang_select)
        self._lang_menu.config(
            fg=C_PRI, bg=C_PANEL, activeforeground=C_BG,
            activebackground=C_PRI, font=font_body(10),
            borderwidth=0, highlightthickness=1,
            highlightbackground=C_MID, width=12)
        self._lang_menu["menu"].config(
            fg=C_PRI, bg=C_PANEL, font=font_body(10),
            activeforeground=C_BG, activebackground=C_PRI)

    def _on_lang_select(self, lang: str):
        self.sound.play_click()
        lang = lang.lower()
        self._current_lang = lang
        save_app_config({"ui_language": lang})
        self.write_log(f"SYS: Dil {lang.upper()} olarak ayarlandi.")
        self._apply_language_widgets()
        self._kick_brief_refresh()
        # Dile gore sesi otomatik degistir (sadece config, reconnect yok)
        auto_voice = LANG_VOICE_MAP.get(lang)
        if auto_voice and auto_voice != self._current_voice:
            self._current_voice = auto_voice
            save_app_config({"voice": auto_voice})
            self.write_log(f"SYS: Ses '{auto_voice}' olarak degistirildi ({lang.upper()}). Yeni ses icin uygulamayi yeniden baslatin.")

    def _apply_language_widgets(self):
        # Dil secici guncelle
        try:
            self._lang_var.set(self._current_lang.upper())
        except Exception:
            pass
        try:
            self._settings_title.config(text=T("SETTINGS"))
        except Exception:
            pass
        try:
            self._settings_sfx_label.config(text=T("SFX"))
        except Exception:
            pass
        try:
            self._voice_label.config(text=T("VOICE"))
            self._lang_label.config(text=T("LANGUAGE"))
        except Exception:
            pass
        for draw in (
            self._draw_tray_button,
            self._draw_shutdown_button,
            self._draw_mute_button,
            self._draw_pause_button,
            self._draw_webcam_button,
            self._draw_settings_button,
            self._draw_settings_tabs,
        ):
            try:
                draw()
            except Exception:
                pass
        try:
            self._settings_status_primary.config(text="")
            self._settings_status_secondary.config(text="")
            self._refresh_settings_status()
        except Exception:
            pass
        try:
            self._model_label.config(text=T("MODEL"), width=10, anchor="w")
        except Exception:
            pass
        try:
            self._model_menu["menu"].entryconfigure(0, label=T("AUTO MODEL"))
            # Auto model seçiliyse label'ı güncelle
            current_model = getattr(self, '_current_model_key', 'auto')
            if current_model == "auto":
                self._model_var.set(T("AUTO MODEL"))
        except Exception:
            pass
        try:
            self._weather_loc_label.config(text=T("WEATHER CITY"))
        except Exception:
            pass
        try:
            self._sidebar_toggle_btn.config(text=T("CHATS"))
            self._sidebar_new_btn.config(text=f"+ {T('NEW CHAT')}")
        except Exception:
            pass
        try:
            self._refresh_settings_status()
        except Exception:
            pass

    # -- Weather Location selector -----------------------------------------------
    def _build_weather_location_selector(self, parent=None):
        parent = parent or self.root
        cfg = load_app_config()
        self._current_weather_loc = str(cfg.get("weather_location", "Istanbul"))
        self._weather_loc_var = tk.StringVar(value=self._current_weather_loc)
        self._weather_loc_label = tk.Label(parent, text=T("WEATHER CITY"), fg=C_MID, bg=parent.cget("bg"), font=font_body_bold(8))

        locations = ["Istanbul", "Ankara", "Izmir", "Bursa", "Antalya", "New York", "London", "Tokyo", "Berlin", "Paris"]
        self._weather_loc_menu = tk.OptionMenu(parent, self._weather_loc_var, *locations, command=self._on_weather_loc_select)
        self._weather_loc_menu.config(
            fg=C_PRI, bg=C_PANEL, activeforeground=C_BG,
            activebackground=C_PRI, font=font_body(10),
            borderwidth=0, highlightthickness=1,
            highlightbackground=C_MID, width=12)
        self._weather_loc_menu["menu"].config(
            fg=C_PRI, bg=C_PANEL, font=font_body(10),
            activeforeground=C_BG, activebackground=C_PRI)

    def _on_weather_loc_select(self, location: str):
        self._current_weather_loc = location
        save_app_config({"weather_location": location})
        self.write_log(f"SYS: Hava durumu konumu '{location}' olarak ayarlandi.")
        self._kick_brief_refresh(force=True)

    # -- Model selector (Uzman modeller arasi manuel gecis) ----------------
    def _build_model_selector(self, parent=None):
        from core.auto_router import MODEL_SELECT_OPTIONS
        parent = parent or self.root
        self.model_select_options = MODEL_SELECT_OPTIONS

        cfg = load_app_config()
        current_key = str(cfg.get("expert_model", "auto") or "auto")
        labels = [opt["label"] for opt in MODEL_SELECT_OPTIONS]
        # "auto" etiketini dile göre çevir
        labels[0] = T("AUTO MODEL")
        current_label = next(
            (opt["label"] for opt in MODEL_SELECT_OPTIONS if opt["key"] == current_key),
            labels[0],
        )
        if current_key == "auto":
            current_label = T("AUTO MODEL")

        self._model_var = tk.StringVar(value=current_label)
        self._model_label = tk.Label(
            parent,
            text=T("MODEL"),
            fg=C_MID,
            bg=parent.cget("bg"),
            font=font_body_bold(8),
            width=10,
            anchor="w",
        )
        self._model_menu = tk.OptionMenu(
            parent,
            self._model_var,
            *labels,
            command=self._on_model_select,
        )
        self._model_menu.config(
            fg=C_PRI, bg=C_PANEL, activeforeground=C_BG,
            activebackground=C_PRI, font=font_body(9),
            borderwidth=0, highlightthickness=1,
            highlightbackground=C_MID, width=18)
        self._model_menu["menu"].config(
            fg=C_PRI, bg=C_PANEL, font=font_body(9),
            activeforeground=C_BG, activebackground=C_PRI)

    def _on_model_select(self, label: str):
        self.sound.play_click()
        key = next(
            (opt["key"] for opt in self.model_select_options if opt["label"] == label),
            "auto",
        )
        save_app_config({"expert_model": key})
        if getattr(self, "_current_lang", "tr") == "en":
            self.write_log(f"SYS: Expert model set to '{label}' (takes effect on next expert task).")
        else:
            self.write_log(f"SYS: Uzman model '{label}' olarak ayarlandi. Siraki uzman gorevde gecerli olacak.")


    # -- Mute button ----------------------------------------------------------
    def _build_mute_button(self):
        self._mute_canvas = tk.Canvas(self.root, width=126, height=36,
                                      bg=C_BG, highlightthickness=0, cursor="hand2")
        self._mute_canvas.bind("<Button-1>", lambda e: self._toggle_mute())
        self._draw_mute_button()

    def _draw_mute_button(self):
        c = self._mute_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        if self.muted:
            col, icon, lbl = C_MUTED, "\U0001f507", f" {T('MUTE')}"
        else:
            col, icon, lbl = C_GREEN, "\U0001f399", f" {T('LIVE')}"
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1),
                                (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=col, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=col, width=2)
        c.create_text(bw//2, bh//2, text=f"{icon}{lbl}",
                      fill=col, font=font_body_bold(11))

    def _build_pause_button(self):
        self._pause_canvas = tk.Canvas(self.root, width=150, height=36,
                                       bg=C_BG, highlightthickness=0, cursor="hand2")
        self._pause_canvas.bind("<Button-1>", lambda e: self._toggle_pause())
        self._draw_pause_button()

    def _draw_pause_button(self):
        c = self._pause_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        if self.paused:
            col, text = C_GOLD, f"\u25b6 {T('RESUME')}"
        else:
            col, text = C_BLUE, f"\u23f8 {T('PAUSE')}"
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1),
                               (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=col, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=col, width=2)
        c.create_text(bw//2, bh//2, text=text, fill=col, font=font_body_bold(11))

    def _build_webcam_button(self):
        self._webcam_btn_canvas = tk.Canvas(self.root, width=140, height=36,
                                            bg=C_BG, highlightthickness=0, cursor="hand2")
        self._webcam_btn_canvas.bind("<Button-1>", lambda e: self._on_webcam_click())
        self._draw_webcam_button()

    def _on_webcam_click(self):
        self.sound.play_click()
        self.toggle_webcam()

    def _draw_webcam_button(self):
        c = self._webcam_btn_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        if self._webcam_feed_active:
            col, text = C_GREEN, f"\U0001f4f7 {T('WEBCAM')}"
        else:
            col, text = C_MID, f"\U0001f4f7 {T('WEBCAM')}"
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1),
                                (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=col, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=col, width=2)
        c.create_text(bw//2, bh//2, text=text, fill=col, font=font_body_bold(11))

    def _toggle_mute(self):
        # Tuş basılı tutma (key repeat) / çift tıklama fırtınasında ses motorunu boğmamak için
        now = time.monotonic()
        if now - self._last_toggle_ts < 0.35:
            return
        self._last_toggle_ts = now
        self.sound.play_click()
        self.muted = not self.muted
        self._draw_mute_button()
        if self.muted:
            self.write_log("SYS: Mikrofon kapatıldı.")
        else:
            self.write_log("SYS: Mikrofon açık.")
        self._sync_sound_state()

    # -- Orb tıklama = pause --------------------------------------------------
    def _on_canvas_click(self, event):
        dx = event.x - self.FCX
        dy = event.y - self.FCY
        if dx*dx + dy*dy <= (self.FACE * 0.40)**2:
            self._toggle_pause()

    def _toggle_pause(self):
        # Tuş basılı tutma (key repeat) / çift tıklama fırtınasında ses motorunu boğmamak için
        now = time.monotonic()
        if now - self._last_toggle_ts < 0.35:
            return
        self._last_toggle_ts = now
        self.sound.play_click()
        self.paused = not self.paused
        self._draw_pause_button()
        if self.paused:
            self.set_state("PAUSED")
            self.write_log("SYS: JARVIS duraklatıldı.")
        else:
            # Resume'da THINKING'e geçmek düşünme loop'unu yeniden başlatıyor;
            # doğrudan LISTENING'e dön, ses yalnızca gerçek işleme başlayınca
            # (main tarafından THINKING set edilince) çalsın.
            self.set_state("LISTENING")
            self.write_log("SYS: JARVIS devam ediyor...")
        self._sync_sound_state()
        if self.on_pause_toggle:
            threading.Thread(target=self.on_pause_toggle, args=(self.paused,), daemon=True).start()

    def _shutdown(self):
        self.sound.play_click()
        self.stop_stats()
        self.sound.stop_all()
        if hasattr(self, 'chat_mgr') and self.chat_mgr:
            self.chat_mgr.flush()
        self.write_log("SYS: JARVIS kapatılıyor...")
        def _exit_app():
            try:
                self.root.destroy()
            except Exception:
                pass
            os._exit(0)
        self.root.after(380, _exit_app)

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self._enter_fullscreen()
        else:
            self.root.attributes("-fullscreen", False)
            self.root.geometry(self._window_geometry)
            self._resize_surface(*self._normal_size)

    def _resize_surface(self, width: int, height: int):
        self._set_layout_metrics(width, height)
        self.bg.configure(width=self.W, height=self.H)
        self.bg.place(x=0, y=0)
        self._place_layout_widgets()
        if hasattr(self, "_social_bar"):
            self._social_bar.place(x=14, y=self.H - FOOTER_H - 52)
        for p in self.particles:
            p["x"] %= self.W
            p["y"] %= self.H

    # -- Input bar ------------------------------------------------------------
    def _build_input_bar(self, lw: int):
        x0 = self.CHAT_X
        btn_w = 76
        gap = 8
        inp_w = lw - btn_w - 40 - gap * 2

        self._input_var   = tk.StringVar()
        self.attached_files = []
        self._input_entry = tk.Entry(
            self.root, textvariable=self._input_var,
            fg=C_TEXT, bg="#041212", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(11),
            highlightthickness=1, highlightbackground=C_DIM,
            highlightcolor=C_PRI)
        
        self._attach_btn = tk.Button(
            self.root, text="\U0001f4ce",
            command=self._on_attach_file,
            fg=C_TEXT, bg=C_PANEL,
            activeforeground=C_BG, activebackground=C_TEXT,
            font=font_body(12),
            borderwidth=0, cursor="hand2",
            highlightthickness=1, highlightbackground=C_DIM)
        self._attach_btn.place(x=x0, y=self.CHAT_INPUT_Y, width=40, height=INPUT_H)

        self._input_entry.place(
            x=x0 + 40 + gap, y=self.CHAT_INPUT_Y, width=inp_w, height=INPUT_H)
        self._input_entry.bind("<Return>",   self._on_input_submit)
        self._input_entry.bind("<KP_Enter>", self._on_input_submit)

        self._send_btn = tk.Button(
            self.root, text=f"{T('SEND')} \u25b6",
            command=self._on_input_submit,
            fg=C_ORG, bg=C_PANEL,
            activeforeground=C_BG, activebackground=C_ORG,
            font=font_body_bold(10),
            borderwidth=0, cursor="hand2",
            highlightthickness=1, highlightbackground=C_ORG)
        self._send_btn.place(
            x=x0+inp_w+gap, y=self.CHAT_INPUT_Y,
            width=btn_w, height=INPUT_H)

    def _place_layout_widgets(self):
        self.log_frame.place(x=self.CHAT_X, y=self.CHAT_Y, width=self.CHAT_W, height=self.CHAT_H)
        gap = 12
        mute_w = int(self._mute_canvas["width"])
        pause_w = int(self._pause_canvas["width"])
        webcam_w = int(self._webcam_btn_canvas["width"])
        shutdown_w = int(self._shutdown_canvas["width"])
        tray_w = int(self._tray_canvas["width"])
        total = mute_w + pause_w + webcam_w + shutdown_w + tray_w + gap * 4
        start_x = self.FCX - total // 2
        row1_y = self.CTRL_Y + 20

        self._mute_canvas.place(x=start_x, y=row1_y)
        self._pause_canvas.place(x=start_x + mute_w + gap, y=row1_y)
        self._webcam_btn_canvas.place(x=start_x + mute_w + pause_w + gap * 2, y=row1_y)
        self._shutdown_canvas.place(x=start_x + mute_w + pause_w + webcam_w + gap * 3, y=row1_y)
        self._tray_canvas.place(x=start_x + mute_w + pause_w + webcam_w + shutdown_w + gap * 4, y=row1_y)

        geo = self._settings_geometry
        panel_x = geo["panel_x"]
        panel_y = geo["panel_y"]
        panel_w = geo["panel_w"]
        panel_h = geo["panel_h"]
        if self._settings_open:
            self._settings_panel.place(x=panel_x, y=panel_y, width=panel_w, height=panel_h)
            self._settings_panel.lift()
            self._settings_title.place(x=14, y=12)
            self._settings_tab_settings.place(x=14, y=40)
            self._settings_tab_debug.place(x=130, y=40)
            if self._settings_tab == "debug":
                self._settings_body.place_forget()
                self._debug_body.place(x=12, y=76, width=panel_w - 24, height=panel_h - 88)
                self._debug_text.place(x=0, y=0, width=panel_w - 24, height=panel_h - 88)
                self._debug_body.lift()
            else:
                self._debug_body.place_forget()
                self._settings_body.place(x=12, y=76, width=panel_w - 24, height=panel_h - 88)
                self._settings_body.lift()
        else:
            self._settings_panel.place_forget()
            self._settings_title.place_forget()
            self._settings_tab_settings.place_forget()
            self._settings_tab_debug.place_forget()
            self._settings_body.place_forget()
            self._debug_body.place_forget()

        inp_w = self.CHAT_W - 84 - 48
        self._attach_btn.place(x=self.CHAT_X, y=self.CHAT_INPUT_Y, width=40, height=INPUT_H)
        self._input_entry.place(x=self.CHAT_X + 48, y=self.CHAT_INPUT_Y, width=inp_w, height=INPUT_H)
        self._send_btn.place(x=self.CHAT_X + 48 + inp_w + 8, y=self.CHAT_INPUT_Y, width=76, height=INPUT_H)

    
    def _on_attach_file(self):
        self.sound.play_click()
        import os
        filepath = filedialog.askopenfilename(title="Dosya Seç (PDF, TXT, Resim, vb.)")
        if filepath:
            self.attached_files.append(filepath)
            filename = os.path.basename(filepath)
            self.write_log(f"SYS: \U0001f4ce [{filename}] eklendi. Mesajinla birlikte gonderilecek.")

    def _on_input_submit(self, event=None):
        self.sound.play_click()
        text = self._input_var.get().strip()
        if not text:
            return
        if self.paused:
            self.write_log("SYS: JARVIS duraklatılmış durumda. Devam etmek için pause'u kapat.")
            return
        self._input_var.set("")
        if text.lower() in ("sus", "dur", "stop", "sessiz", "kes"):
            self.write_log("SYS: \u23f9 Ses kesildi.")
            if self.on_stop_command:
                threading.Thread(target=self.on_stop_command, daemon=True).start()
            return
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(text,), daemon=True).start()

    # -- State & callbacks ----------------------------------------------------
    def set_state(self, state: str):
        previous = getattr(self, "_jarvis_state", "")
        self._jarvis_state = state
        self.speaking = (state == "SPEAKING")
        if state == "THINKING" and previous != "THINKING":
            self.sound.start_thinking(state)
        elif previous == "THINKING" and state != "THINKING":
            self.sound.stop_thinking()
        if state == "ERROR" and previous != "ERROR":
            self.sound.play_error()
        if state == "LISTENING":
            self.sound.set_ambient_blocked(True)
            self.sound.stop_thinking()
            self.sound.stop_ambient()
            self.sound.silence_all_loops()
        elif state == "PAUSED":
            self.sound.set_ambient_blocked(True)
            self.sound.stop_thinking()
            self.sound.stop_ambient()
            self.sound.silence_all_loops()
        elif state in ("SPEAKING", "INITIALISING"):
            self.sound.set_ambient_blocked(False)
            self.sound.stop_thinking()
        else:
            self.sound.set_ambient_blocked(False)

    def set_user_speaking(self, value: bool):
        self.mark_user_activity(value)

    def mark_user_activity(self, active: bool = True):
        self.user_speaking = active
        self._user_speaking_until = time.time() + (0.9 if active else 0.0)

    def get_effects_volume(self) -> float:
        return self.sound.get_volume()

    def effects_enabled(self) -> bool:
        return bool(self._effects_active)

    def play_success_sfx(self):
        self.root.after(0, self.sound.play_success)

    def play_error_sfx(self):
        self.root.after(0, self.sound.play_error)

    def wake_up(self):
        """Çift alkışla tetiklenir — pencereyi öne getirir."""
        def _do():
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()
            self.root.after(3000, lambda: self.root.attributes("-topmost", False))
            if self.on_main_menu_show:
                self.on_main_menu_show()
        self.root.after(0, _do)

    def focus_panel(self, section: str, duration_ms: int = 4200):
        section = (section or "").strip().lower()
        if not section:
            return

        def _apply():
            self._panel_focus = section
            self._panel_focus_until = time.time() + max(0.8, duration_ms / 1000.0)

        self.root.after(0, _apply)

    def _state_color(self, state: str | None = None) -> str:
        effective = state or self._jarvis_state
        if effective == "PAUSED":
            return C_MID
        return STATE_HEX_COLORS.get(effective, C_PRI)

    @staticmethod
    def _state_badge_text(state: str) -> str:
        if state == "INITIALISING":
            return T("CONNECTING")
        if state == "ERROR":
            return T("ERROR")
        return T("ONLINE")

    # -- Log ------------------------------------------------------------------
    def write_log(self, text: str):
        self.typing_queue.append(text)
        tl = text.lower()
        if tl.startswith("siz:") or tl.startswith("you:"):
            self.mark_user_activity(True)
            self.set_state("THINKING")
        elif tl.startswith("err:") or "error" in tl:
            self._error_hold_until = time.time() + 8.0
            self.set_state("ERROR")
            self.write_debug(text, level="ERROR")
        if not self.is_typing:
            self._start_typing()

    def _start_typing(self):
        if not self.typing_queue:
            self.is_typing = False
            if self._jarvis_state == "ERROR" and time.time() < self._error_hold_until:
                return
            if not self.speaking:
                self.set_state("LISTENING")
            return
        self.is_typing = True
        text = self.typing_queue.popleft()
        tl   = text.lower()
        if   tl.startswith("siz:") or tl.startswith("you:"):   tag = "you"
        elif tl.startswith("jarvis:") or tl.startswith("ai:"): tag = "ai"
        elif tl.startswith("err:") or "error" in tl:           tag = "err"
        else:                                                    tag = "sys"
        self.log_text.configure(state="normal")
        self._type_char(text, 0, tag)

    def _type_char(self, text, i, tag):
        if i < len(text):
            self.log_text.insert(tk.END, text[i], tag)
            self.log_text.see(tk.END)
            self.root.after(7, self._type_char, text, i+1, tag)
        else:
            self.log_text.insert(tk.END, "\n")
            self.log_text.configure(state="disabled")
            self.root.after(20, self._start_typing)

    # -- Uzman model akışı (streaming) --------------------------------------
    # Tkinter yalnızca ana thread'de güvenli olduğundan tüm çağrılar
    # root.after ile ana thread'e zamanlanır (thread-safe).
    def begin_expert_stream(self, model_hint: str = ""):
        def _do():
            self._stream_active = True
            self.log_text.configure(state="normal")
            header = f"[UZMAN MODEL · {model_hint}]" if model_hint else "[UZMAN MODEL]"
            self.log_text.insert(tk.END, f"SYS: {header}\n\n", "sys")
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")
            self._schedule_stream_flush()
        self.root.after(0, _do)

    def stream_expert_chunk(self, text: str):
        if text:
            self._stream_buffer.append(text)
            self._schedule_stream_flush()

    def end_expert_stream(self):
        def _do():
            self._stream_active = False
            self.log_text.configure(state="normal")
            while self._stream_buffer:
                self.log_text.insert(tk.END, self._stream_buffer.popleft(), "expert")
            self.log_text.insert(tk.END, "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")
            self._stream_flush_scheduled = False
        self.root.after(0, _do)

    def _schedule_stream_flush(self):
        if self._stream_flush_scheduled:
            return
        self._stream_flush_scheduled = True
        self.root.after(40, self._flush_stream_buffer)

    def _flush_stream_buffer(self):
        self._stream_flush_scheduled = False
        if not self._stream_active and not self._stream_buffer:
            return
        self.log_text.configure(state="normal")
        while self._stream_buffer:
            self.log_text.insert(tk.END, self._stream_buffer.popleft(), "expert")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")
        if self._stream_active:
            self._schedule_stream_flush()

    # -- Stats ----------------------------------------------------------------
    def _stats_probe(self):
        # İlk çağrıda psutil.cpu_percent() 0.0 döner; bu yüzden referans almak
        # için önce intervalı saplama yaparız, sonra sürekli 1 sn'lik aralıklarla
        # (Görev Yöneticisi ile uyumlu) gerçek CPU kullanımını ölçeriz.
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        # Yorum: 0.5 sn'de bir çalış, böylece internet hızı yarım saniyede
        # bir güncellenir (1.0 sn engel, anlık gösterimi yavaşlatırdı).
        while self._stats_running:
            try:
                self._stats['cpu']  = psutil.cpu_percent(interval=0.5)
                self._stats['ram']  = psutil.virtual_memory().percent
                self._stats['disk'] = psutil.disk_usage('C:\\').percent
                batt = psutil.sensors_battery()
                self._stats['battery'] = batt.percent if batt else 100.0
                self._stats['speed_down'] = self._speed_meter.down_mbps
                self._stats['speed_up']   = self._speed_meter.up_mbps
                self._cpu_hist.pop(0)
                self._cpu_hist.append(self._stats['cpu'])
            except Exception:
                pass
            time.sleep(0.1)

    def stop_stats(self):
        self._stats_running = False
        self._speed_meter.stop()

    # -- Animation loop -------------------------------------------------------
    def _animate(self):
        self.tick += 1
        t   = self.tick
        now = time.time()

        if self.user_speaking and now > self._user_speaking_until:
            self.user_speaking = False

        if t % 1800 == 1:
            self._kick_brief_refresh()

        if self.speaking and t % 3 == 0:
            self._wave_jarvis = [random.randint(6, 30) for _ in range(18)]
        if self.user_speaking and t % 3 == 0:
            self._wave_user = [random.randint(5, 24) for _ in range(18)]

        if now - self.last_t > (0.12 if self.speaking else 0.50):
            if self.paused:
                self.target_scale = random.uniform(0.58, 0.64)
                self.target_halo  = random.uniform(5, 10)
            elif self.speaking:
                self.target_scale = random.uniform(0.98, 1.10)
                self.target_halo  = random.uniform(180, 250)
            elif self.user_speaking:
                self.target_scale = random.uniform(0.88, 0.98)
                self.target_halo  = random.uniform(120, 175)
            elif self._jarvis_state in ("THINKING", "INITIALISING"):
                self.target_scale = random.uniform(0.80, 0.88)
                self.target_halo  = random.uniform(95, 145)
            else:
                self.target_scale = random.uniform(0.72, 0.80)
                self.target_halo  = random.uniform(34, 58)
            self.last_t = now

        sp          = 0.34 if self.speaking else 0.18
        self.scale  += (self.target_scale - self.scale) * sp
        self.halo_a += (self.target_halo   - self.halo_a) * sp

        if self.paused:
            spds = [0.0, 0.0, 0.0, 0.0]
        elif self.speaking:
            spds = [1.6, -1.1, 2.4, -0.7]
        else:
            spds = [0.55, -0.35, 0.90, -0.28]
        for i, spd in enumerate(spds):
            self.rings_spin[i] = (self.rings_spin[i] + spd) % 360

        # Pulse rings
        pspd  = 4.2 if self.speaking else 1.8
        limit = self.FACE * 0.68
        self.pulse_r = [r + pspd for r in self.pulse_r if r + pspd < limit]
        if len(self.pulse_r) < 3 and random.random() < (0.07 if self.speaking else 0.02):
            self.pulse_r.append(0.0)

        for p in self.particles:
            p['x'] = (p['x'] + p['vx']) % self.W
            p['y'] = (p['y'] + p['vy']) % self.H

        if t % 38 == 0:
            self.status_blink = not self.status_blink

        self._draw()
        self.root.after(33, self._animate)

    # -- Yardımcı -------------------------------------------------------------
    @staticmethod
    def _ac(r, g, b, a):
        f = max(0, min(255, int(a))) / 255.0
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

    def _orb_rgb(self):
        state = "PAUSED" if self.paused else self._jarvis_state
        return ORB_COLORS.get(state, ORB_COLORS["LISTENING"])

    @staticmethod
    def _split_summary_lines(text: str, limit: int = 4) -> list[str]:
        raw = (text or "").strip()
        if not raw:
            return []
        raw = raw.replace(" ve ", ", ")
        parts = [part.strip(" .") for part in raw.split(",") if part.strip()]
        return parts[:limit]

    def _parse_weather_card(self, text: str) -> dict:
        low = (text or "").lower()
        unavailable = (
            "alınamadı" in low or "alınamadi" in low
            or "unavailable" in low or "could not" in low
        )
        if not text or unavailable:
            return {
                "city": "Istanbul",
                "primary": "--",
                "details": ["Hava durumu alınamadı."],
            }

        prefix, _, body = text.partition(":")
        city = "Istanbul"
        for marker in (" için", " weather", " havadurumu"):
            if marker in prefix.lower():
                city = prefix.split(marker, 1)[0].strip().title()
                break

        details = [part.strip(" .") for part in body.split(",") if part.strip()]
        primary = "--"
        if details:
            primary = details[0].replace(" derece", "°C")
        return {
            "city": city,
            "primary": primary,
            "details": details[1:4] or [T("LIVE DATA READY")],
        }

    def _parse_health_card(self, text: str) -> list[str]:
        if not text or "alınamadı" in text.lower() or "alınamadi" in text.lower():
            return [T("HEALTH DATA UNAVAILABLE")]
        lines = self._split_summary_lines(text, limit=4)
        return lines or [T("HEALTH SUMMARY NOT READY")]

    def _kick_brief_refresh(self, force=False):
        threading.Thread(target=self._refresh_brief_cards, daemon=True).start()

    def _refresh_brief_cards(self):
        is_tr = str(getattr(self, "_current_lang", "tr")).lower() == "tr"
        try:
            # Otomatik konum tespiti kullan
            req_id = time.time()
            self._weather_req_id = req_id
            weather = get_weather_summary()  # Konum belirtilmezse otomatik tespit edilir
            # Bu hala en güncel istek mi?
            if getattr(self, "_weather_req_id", None) != req_id:
                return  # Daha yeni bir istek var, bunu yoksay
            parsed = self._parse_weather_card(weather)
            self._weather_card = parsed
        except Exception:
            self._weather_card = {
                "city": "Konum",
                "primary": "--",
                "details": [("Hava durumu alınamadı." if is_tr else "Weather unavailable.")],
            }

    def _bar(self, c, x, y, w, h, pct, color):
        c.create_rectangle(x, y, x+w, y+h, fill="#061212", outline=C_DIM, width=1)
        fw = max(1, int(w * pct / 100))
        c.create_rectangle(x+1, y+1, x+fw, y+h-1, fill=color, outline="")

    def _sparkline(self, c, x, y, w, h, data):
        c.create_rectangle(x, y, x+w, y+h, fill="#050e0e", outline=C_DIM, width=1)
        n = len(data)
        if n < 2:
            return
        step = (w - 2) / (n - 1)
        h2   = h - 2
        coords = []
        for i, v in enumerate(data):
            coords.append(x + 1 + i * step)
            coords.append(y + h - 1 - int(h2 * v / 100))
        c.create_line(*coords, fill=C_PRI, width=1, smooth=True)

    def _bracket(self, c, x0, y0, pw, ph, col=None, bl=12):
        col = col or C_PRI
        for bx, by, sx, sy in [(x0, y0, 1, 1), (x0+pw, y0, -1, 1),
                                (x0, y0+ph, 1, -1), (x0+pw, y0+ph, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=col, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=col, width=2)

    def _draw_info_card(self, c, x0, y0, pw, ph, title, accent=C_PRI):
        focus = max(0.0, min(1.0, getattr(self, "_card_focus_boost", 0.0)))
        dimmed = bool(getattr(self, "_card_dimmed", False))
        glow = int(55 + 120 * focus)
        border = accent if focus > 0.08 else ("#35504d" if dimmed else self._ac(0, 120, 112, 190))
        fill = "#071111" if dimmed else "#030d0d"
        c.create_rectangle(x0, y0, x0+pw, y0+ph, fill=fill, outline="")
        if focus > 0.08:
            for inset in range(3):
                c.create_rectangle(
                    x0-inset, y0-inset, x0+pw+inset, y0+ph+inset,
                    outline=self._ac(*ORB_COLORS["LISTENING"], max(12, glow - inset * 28)),
                    width=1,
                )
        self._bracket(c, x0, y0, pw, ph, col=border, bl=10)
        title_fill = "#6f7d7b" if dimmed else accent
        line_fill = "#173130" if dimmed else C_DIM
        c.create_text(x0+14, y0+14, text=title, fill=title_fill,
                      font=font_display(10), anchor="w")
        c.create_line(x0+12, y0+28, x0+pw-12, y0+28, fill=line_fill)

    def _focus_boost_for(self, section: str) -> float:
        if self._panel_focus != section:
            return 0.0
        remaining = self._panel_focus_until - time.time()
        if remaining <= 0:
            return 0.0
        pulse = 0.65 + 0.35 * math.sin(self.tick * 0.12)
        return min(1.0, remaining / 4.0) * pulse

    # -- Health overlay (sol panel) --------------------------------------------
    def show_health_hologram(self, query: str, data_str: str):
        def _show():
            self._health_visible = True
            self._health_query   = query.lower()
            self._health_display = data_str
            self._panel_focus = "health"
            self._panel_focus_until = time.time() + 5.0
            if self._health_hide_job:
                self.root.after_cancel(self._health_hide_job)
            self._health_hide_job = self.root.after(14000, self._hide_health_hologram)
        self.root.after(0, _show)

    def _hide_health_hologram(self):
        self._health_visible  = False
        self._health_hide_job = None

    def _draw_health_overlay(self, c):
        x0, y0 = 4, HDR_H + 4
        pw = self.LEFT_W - 8
        ph = self.H - HDR_H - FOOTER_H - 90
        pulse = 0.5 + 0.5 * math.sin(self.tick * 0.08)

        c.create_rectangle(x0, y0, x0+pw, y0+ph,
                           fill="#011510", outline=C_PRI, width=1)
        self._bracket(c, x0, y0, pw, ph, col=C_ORG, bl=10)

        title_col = self._ac(0, 212, 192, int(200 + 55*pulse))
        c.create_text(x0+pw//2, y0+18, text="\u2665 HEALTH \u2665",
                      fill=title_col, font=font_display(11))
        c.create_line(x0+8, y0+30, x0+pw-8, y0+30, fill=C_MID)

        lines = [l for l in self._health_display.split('\n') if l.strip()]
        ly = y0 + 44
        for line in lines:
            if ly > y0 + ph - 14:
                break
            if line.startswith("--"):
                c.create_line(x0+8, ly, x0+pw-8, ly, fill=C_DIM)
                ly += 10
            elif ":" in line:
                parts = line.split(":", 1)
                lbl   = parts[0].strip()
                val   = parts[1].strip() if len(parts) > 1 else ""
                c.create_text(x0+10, ly, text=lbl+":", fill=C_MID,
                              font=font_body(10), anchor="w")
                c.create_text(x0+pw-10, ly, text=val, fill=C_ORG,
                              font=font_body_bold(10), anchor="e")
                ly += 20
            else:
                c.create_text(x0+10, ly, text=line, fill=C_TEXT,
                              font=font_body(9), anchor="w")
                ly += 17

    # -- Sol panel -------------------------------------------------------------
    def _draw_left_panel(self, c):
        if self._health_visible:
            self._draw_health_overlay(c)
            return

        x0 = 10
        y0 = HDR_H + 10
        pw = self.LEFT_W - 18
        gap = 14
        total_h = self.H - HDR_H - FOOTER_H - 20
        card_area_h = total_h - gap * 3
        pad = 14
        bw = pw - 2 * pad

        cards = [
            ("time", 0.20, T("TIME"), C_ORG),
            ("weather", 0.28, f"{T('WEATHER')} · {self._weather_card.get('city', 'Istanbul').upper()}", C_ORG),
            ("system", 0.52, T("SYSTEM STATUS"), C_ORG),
        ]
        any_focus_active = bool(self._panel_focus) and (self._panel_focus_until > time.time())
        weights = []
        for section, weight, _, _ in cards:
            weights.append(weight + (0.12 if self._focus_boost_for(section) > 0.08 else 0.0))
        total_weight = sum(weights)
        heights = [int(card_area_h * (weight / total_weight)) for weight in weights]
        heights[-1] += card_area_h - sum(heights)

        current_y = y0
        for (section, _, title, accent), ph in zip(cards, heights):
            focus_boost = self._focus_boost_for(section)
            dimmed = any_focus_active and focus_boost <= 0.08
            shift_x = int(14 * focus_boost)
            extra_w = int(22 * focus_boost)
            section_x = x0 + shift_x
            section_pw = pw + extra_w
            section_pad = pad + int(2 * focus_boost)
            section_bw = section_pw - 2 * section_pad
            muted_label = "#647270" if dimmed else C_MID
            muted_text = "#7e8a88" if dimmed else C_TEXT
            muted_primary = "#8ea19d" if dimmed else C_PRI
            muted_blue = "#829594" if dimmed else C_BLUE
            muted_green = "#85a393" if dimmed else C_GREEN
            muted_gold = "#a1997e" if dimmed else C_GOLD
            muted_warn = "#8d7f77" if dimmed else C_ORG2
            muted_red = "#8a7779" if dimmed else C_RED
            self._card_focus_boost = focus_boost
            self._card_dimmed = dimmed
            self._draw_info_card(c, section_x, current_y, section_pw, ph, title, accent=accent if not dimmed else "#72807f")

            if section == "time":
                c.create_text(section_x+section_pad, current_y+64, text=time.strftime("%H:%M"),
                              fill=muted_primary, font=font_display(36 if focus_boost > 0.08 else 34), anchor="w")
                c.create_text(section_x+section_pad, current_y+92, text=time.strftime(":%S"),
                              fill=muted_label, font=font_body_bold(13), anchor="w")
                c.create_text(section_x+section_pad, current_y+118, text=T_DATE(time.strftime("%d %B %Y").upper()),
                              fill=muted_gold, font=font_body_bold(11), anchor="w")
                c.create_text(section_x+section_pad, current_y+138, text=T_DATE(time.strftime("%A").upper()),
                              fill=muted_text, font=font_body(10), anchor="w")

            elif section == "weather":
                c.create_text(section_x+section_pad, current_y+58, text=self._weather_card["primary"],
                              fill=muted_primary, font=font_display(30 if focus_boost > 0.08 else 28), anchor="w")
                c.create_text(section_x+section_pad, current_y+84, text=self._weather_card["city"].upper(),
                              fill=muted_label, font=font_body_bold(10), anchor="w")
                wy = current_y + 108
                for line in self._weather_card["details"][:3]:
                    c.create_text(section_x+section_pad, wy, text=f"• {line}", fill=muted_text,
                                  font=font_body(10), anchor="w")
                    wy += 17

            elif section == "system":
                cy = current_y + 44
                uptime = int(time.time() - self._started_at)
                up_min, up_sec = divmod(uptime, 60)
                up_hr, up_min = divmod(up_min, 60)
                c.create_text(section_x+section_pad, cy, text=f"{T('UPTIME')}  {up_hr:02d}:{up_min:02d}:{up_sec:02d}",
                              fill=muted_label, font=font_body_bold(9), anchor="w")
                cy += 22
                for label, key, unit in [(T("CPU"), "cpu", "%"), (T("RAM"), "ram", "%"), (T("DISK"), "disk", "%"), (T("BATTERY"), "battery", "%")]:
                    val = self._stats[key]
                    col = C_RED if val > 80 and key != "battery" else C_ORG if val > 55 and key != "battery" else (C_RED if key == "battery" and val < 20 else C_GREEN if key == "battery" else C_PRI)
                    if dimmed:
                        col = muted_red if col == C_RED else muted_warn if col == C_ORG else muted_green if col == C_GREEN else muted_primary
                    c.create_text(section_x+section_pad, cy, text=label, fill=muted_label, font=font_body(10), anchor="w")
                    c.create_text(section_x+section_pw-section_pad, cy, text=f"{val:.0f}{unit}", fill=col, font=font_body_bold(10), anchor="e")
                    cy += 14
                    self._bar(c, section_x+section_pad, cy, section_bw, 7, val, col)
                    cy += 16
                # Gerçek ölçülen hız (Cloudflare); tek ölçüm kaynağı bu.
                sd = self._stats.get("speed_down", 0.0)
                su = self._stats.get("speed_up", 0.0)
                spd_s = f"{T('INTERNET')}  \u2193{sd:.1f}  \u2191{su:.1f} Mbps"
                c.create_line(section_x+section_pad, cy-4, section_x+section_pw-section_pad, cy-4, fill="#173130" if dimmed else C_DIM)
                net_col = muted_red if dimmed else C_RED
                c.create_text(section_x+section_pad, cy+10, text=spd_s, fill=net_col, font=font_body(10), anchor="w")

            current_y += ph + gap

        self._card_focus_boost = 0.0
        self._card_dimmed = False

    # -- Sağ panel -------------------------------------------------------------
    def _draw_right_panel(self, c):
        x0  = self.CHAT_PANEL_X
        y0  = self.CHAT_PANEL_Y
        pw  = self.CHAT_PANEL_W
        ph  = self.CHAT_PANEL_H
        pad = 10

        c.create_rectangle(x0, y0, x0+pw, y0+ph, fill="#030d0d", outline="")
        self._bracket(c, x0, y0, pw, ph, col=C_MID)

        if self.paused:
            sc, st = C_MID, T("PAUSED")
        else:
            sc, st = self._state_color(self._jarvis_state), T(self._jarvis_state)

        c.create_text(x0+14, y0+16, text=T("CONVERSATION"), fill=C_PRI,
                      font=font_display(11), anchor="w")
        c.create_text(x0+pw-pad, y0+16, text=st, fill=sc,
                      font=font_body_bold(10), anchor="e")
        c.create_line(x0+pad, y0+28, x0+pw-pad, y0+28, fill=C_DIM)

    # -- ORB (ana çizim) -------------------------------------------------------
    def _draw_orb(self, c):
        state = "PAUSED" if self.paused else self._jarvis_state
        t    = self.tick
        speak_pulse = 1.0
        if self.speaking:
            speak_pulse = 1.0 + 0.12 * math.sin(t * 0.23) + 0.05 * math.sin(t * 0.11 + 1.2)
        elif self.user_speaking:
            speak_pulse = 1.0 + 0.06 * math.sin(t * 0.18 + 0.7)
        elif state in ("THINKING", "INITIALISING"):
            speak_pulse = 1.0 + 0.03 * math.sin(t * 0.10)
        else:
            speak_pulse = 1.0 + 0.01 * math.sin(t * 0.07)

        move_x = 0
        move_y = 0
        if self.user_speaking:
            move_x = int(6 * math.sin(t * 0.06))
            move_y = int(4 * math.cos(t * 0.09 + 0.5))
        elif state in ("THINKING", "INITIALISING"):
            move_x = int(3 * math.sin(t * 0.045))
            move_y = int(2 * math.cos(t * 0.05 + 0.4))

        FCX  = self.FCX + move_x
        FCY  = self.FCY + move_y
        FW   = int(self.FACE * self.scale * speak_pulse)
        R, G, B = self._orb_rgb()
        ha   = self.halo_a
        field_r = int(FW * 0.49)
        inner_r = int(FW * 0.34)
        activity = (
            0.10 if self.paused else
            1.00 if self.speaking else
            0.78 if self.user_speaking else
            0.62 if state in ("THINKING", "INITIALISING") else
            0.26
        )
        if state in ("THINKING", "INITIALISING"):
            accent_rgb = (255, 210, 72)
        elif self.speaking:
            accent_rgb = (170, 220, 255)
        elif self.user_speaking:
            accent_rgb = (118, 200, 255)
        else:
            accent_rgb = (120, 255, 185)

        # Pulse rings
        for pr in self.pulse_r:
            alpha = max(0, int(160 * (1.0 - pr / (FW * 0.70))))
            rr = int(pr + field_r * 0.96)
            c.create_oval(
                FCX-rr, FCY-rr, FCX+rr, FCY+rr,
                outline=self._ac(R, G, B, alpha),
                width=1,
            )

        # Large outer glow
        if not self.paused:
            for i in range(10, 0, -1):
                frac = i / 10
                rr = int(field_r * (1.02 + 0.045 * frac))
                alpha = int(ha * 0.10 * frac)
                if self.speaking:
                    ox = 0
                    oy = 0
                else:
                    ox = int(3 * math.sin(t * 0.010 + i))
                    oy = int(3 * math.cos(t * 0.009 + i * 1.3))
                c.create_oval(
                    FCX-rr+ox, FCY-rr+oy, FCX+rr+ox, FCY+rr+oy,
                    outline=self._ac(R, G, B, alpha),
                    width=3,
                )

        # Structural circles
        for frac, width, alpha_mult in (
            (1.00, 2, 0.34),
            (0.90, 2, 0.24),
            (0.76, 1, 0.18),
            (0.62, 1, 0.12),
        ):
            rr = int(field_r * frac)
            c.create_oval(
                FCX-rr, FCY-rr, FCX+rr, FCY+rr,
                outline=self._ac(R, G, B, int(ha * alpha_mult * (0.4 if self.paused else 1.0))),
                width=width,
            )

        speak_shell_push = 1.16 if self.speaking else 1.07 if self.user_speaking else 1.0
        # Orb shell particles
        shell_r = field_r * 0.93 * speak_shell_push
        for idx, sp in enumerate(self.orb_shell_particles):
            angle = sp['angle'] + t * sp['speed'] * (2.8 if self.speaking else 1.6 if self.user_speaking else 1.1)
            wobble = 1.0 + (0.07 if self.speaking else 0.035) * math.sin(t * 0.08 + sp['phase'])
            x = FCX + math.cos(angle) * shell_r * wobble
            y = FCY + math.sin(angle) * shell_r * wobble
            alpha = int((70 + 120 * sp['glow']) * (0.26 if self.paused else 0.52 + activity * 0.45))
            if idx % 9 == 0 and not self.paused:
                col = self._ac(accent_rgb[0], accent_rgb[1], accent_rgb[2], min(255, alpha + 30))
            else:
                col = self._ac(R, G, B, alpha)
            pr = sp['size'] * (1.0 + 0.24 * math.sin(t * 0.05 + sp['phase']))
            c.create_oval(x-pr, y-pr, x+pr, y+pr, fill=col, outline="")

        # Rotating segmented arcs
        arc_r1 = int(field_r * 0.96)
        arc_r2 = int(field_r * 0.78)
        for start, extent, width, accent in (
            (self.rings_spin[0], 52 if self.speaking else 34, 3, False),
            ((self.rings_spin[0] + 148) % 360, 26, 2, True),
            ((self.rings_spin[2] + 28) % 360, 64 if self.user_speaking else 40, 3, False),
            ((self.rings_spin[2] + 212) % 360, 18, 2, True),
        ):
            rr = arc_r1 if width == 3 else arc_r2
            if accent and not self.paused:
                col = self._ac(accent_rgb[0], accent_rgb[1], accent_rgb[2], int(120 + 80 * activity))
            else:
                col = self._ac(R, G, B, int(ha * (1.2 if width == 3 else 0.7)))
            c.create_arc(
                FCX-rr, FCY-rr, FCX+rr, FCY+rr,
                start=start, extent=extent,
                outline=col, width=width, style="arc",
            )

        # Particle orb field
        field_limit = inner_r * (
            0.82 if self.paused else
            1.36 if self.speaking else
            1.16 if self.user_speaking else
            1.0
        )
        for idx, p in enumerate(self.orb_particles):
            speed_mult = (
                0.10 if self.paused else
                3.10 if self.speaking else
                2.00 if self.user_speaking else
                1.10
            )
            angle = p['angle'] + t * p['speed'] * speed_mult
            wobble = 1.0 + (0.30 if self.speaking else 0.18) * math.sin(t * p['wobble'] + p['phase'])
            orbit = field_limit * p['orbit'] * wobble
            depth = 0.5 + 0.5 * math.sin(angle * 2.0 + t * 0.013 + p['phase'])
            y_squash = 0.62 + depth * 0.38
            drift = (8.0 if self.speaking else 5.0 if self.user_speaking else 4.0) * p['depth']
            x = FCX + math.cos(angle) * orbit + math.sin(t * 0.011 + p['phase']) * drift
            y = FCY + math.sin(angle) * orbit * y_squash + math.cos(t * 0.010 + p['phase']) * drift
            base_alpha = int((18 + 155 * p['depth']) * (0.24 + activity * 0.86) * (0.45 + depth * 0.75))
            if self.paused:
                base_alpha = int(base_alpha * 0.40)
            if idx % 11 == 0 and not self.paused:
                col = self._ac(accent_rgb[0], accent_rgb[1], accent_rgb[2], min(255, base_alpha + 25))
            elif self.user_speaking and idx % 7 == 0:
                col = self._ac(120, 205, 255, min(255, base_alpha + 20))
            else:
                col = self._ac(R, G, B, base_alpha)
            pr = p['size'] * (0.70 if self.paused else 0.90 + depth * 0.65 + 0.30 * activity * p['depth'])
            c.create_oval(x-pr, y-pr, x+pr, y+pr, fill=col, outline="")
            if idx % 18 == 0 and not self.paused:
                c.create_line(
                    FCX + (x-FCX) * 0.18,
                    FCY + (y-FCY) * 0.18,
                    x, y,
                    fill=self._ac(R, G, B, int(18 + 35 * p['depth'] * activity)),
                    width=1,
                )

        # Center void keeps the orb airy instead of lens-like.
        void_r = int(inner_r * (0.18 if self.paused else 0.12))
        if void_r > 0:
            c.create_oval(
                FCX-void_r, FCY-void_r, FCX+void_r, FCY+void_r,
                fill=C_BG,
                outline="",
            )

    # -- Ana çizim -------------------------------------------------------------
    def _draw(self):
        c  = self.bg
        W  = self.W
        H  = self.H
        t  = self.tick
        c.delete("all")

        # -- Arka plan --------------------------------------------------------
        # Nokta ızgarası — çok ince
        step = 48
        for x in range(0, W, step):
            for y in range(0, H, step):
                c.create_rectangle(x, y, x+1, y+1, fill=C_DIMMER, outline="")

        # Tarama çizgisi (yavaş, çok soluk)
        scan_y = (t * 0.7) % (H + 60) - 30
        for i in range(2):
            ly = (scan_y + i * 20) % H
            c.create_line(0, ly, W, ly+35, fill="#081818", width=1)

        # Partiküller
        R, G, B = self._orb_rgb()
        for p in self.particles:
            if self.speaking:
                col = self._ac(255, 110, 0, p['a'])
            else:
                col = self._ac(R, G, B, p['a'])
            r = p['r']
            c.create_oval(p['x']-r, p['y']-r, p['x']+r, p['y']+r,
                          fill=col, outline="")

        # -- Bölücü çizgiler (ince, soluk) ------------------------------------
        c.create_line(self.LEFT_W, HDR_H, self.LEFT_W, H-FOOTER_H,
                      fill=C_DIM, width=1)
        c.create_line(W-self.RIGHT_W, HDR_H, W-self.RIGHT_W, H-FOOTER_H,
                      fill=C_DIM, width=1)

        # -- Yan paneller ------------------------------------------------------
        self._draw_left_panel(c)
        self._draw_right_panel(c)

        # -- Orb --------------------------------------------------------------
        self._draw_orb(c)

        state_label = "PAUSED" if self.paused else self._jarvis_state
        state_col = self._state_color(state_label)
        c.create_text(self.FCX, self.CTRL_Y - 34, text=SYSTEM_NAME,
                      fill=C_TEXT, font=font_display(18))
        c.create_text(self.FCX, self.CTRL_Y - 12, text=f"\u25cf {T(state_label)}",
                      fill=state_col, font=font_body_bold(11))

        # -- HEADER -----------------------------------------------------------
        c.create_rectangle(0, 0, W, HDR_H, fill="#010a0a", outline="")
        # Alt çizgi — teal parlak
        c.create_line(0, HDR_H, W, HDR_H, fill=C_MID, width=1)
        for i in range(3):
            a = 60 - i * 18
            c.create_line(0, HDR_H-1-i, W, HDR_H-1-i,
                          fill=self._ac(0, 180, 165, a), width=1)

        # Büyük başlık
        c.create_text(W//2, 24, text=SYSTEM_NAME,
                      fill=C_PRI, font=font_display(26))
        c.create_text(W//2, 52, text=T("Just A Rather Very Intelligent System"),
                      fill=C_MID, font=font_body(11))

        # Sol: model badge
        c.create_text(22, 36, text=MODEL_BADGE,
                      fill=C_DIM, font=font_body(10), anchor="w")

        # Sağ: durum indikatörü
        indicator_state = "PAUSED" if self.paused else self._jarvis_state
        ind_col = self._state_color(indicator_state)
        indicator_text = self._state_badge_text(indicator_state)
        sym = "\u25cf" if self.status_blink else "\u25cb"
        c.create_text(W-22, 36, text=f"{sym}  {indicator_text}",
                      fill=ind_col, font=font_body_bold(11), anchor="e")

        # -- FOOTER -----------------------------------------------------------
        c.create_rectangle(0, H-FOOTER_H, W, H, fill="#010a0a", outline="")
        c.create_line(0, H-FOOTER_H, W, H-FOOTER_H, fill=C_DIM, width=1)
        c.create_text(W//2, H-13, fill=C_DIM, font=font_body(9),
                      text="JARVIS · Windows Edition · Realtime Voice Core")
        c.create_text(W-18, H-13, fill=C_DIM, font=font_body(9),
                      text=f"[F4] {T('MUTE')}  [F5] {T('PAUSE')}  [ESC] {T('EXIT')}", anchor="e")

    def wait_for_api_key(self):
        self._api_key_event = threading.Event()
        if self._api_key_ready:
            self._api_key_event.set()
        self._api_key_event.wait()

    def _signal_api_key_ready(self):
        if hasattr(self, '_api_key_event'):
            self._api_key_event.set()

    def _show_setup_ui(self, edit_mode: bool = False):
        self._close_setup_ui()

        self.setup_frame = tk.Frame(self.root, bg="#00080d",
                                    highlightbackground=C_PRI,
                                    highlightthickness=1)
        setup_w = min(760, max(560, int(self.W * 0.42)))
        setup_h = min(520, max(430, int(self.H * 0.44)))
        self.setup_frame.place(relx=0.5, rely=0.5, anchor="center", width=setup_w, height=setup_h)
        self.setup_frame.pack_propagate(False)

        title = f"\u2699 {T('API SETTINGS TITLE')}" if edit_mode else f"\u26a0 {T('FIRST SETUP REQUIRED')}"
        subtitle = (
            T("UPDATE SETTINGS")
            if edit_mode else
            T("ENTER KEY")
        )
        config = load_app_config()

        tk.Label(self.setup_frame, text=title,
                 fg=C_PRI, bg="#00080d", font=font_display(20)).pack(pady=(28, 6))
        tk.Label(self.setup_frame, text=subtitle,
                 fg=C_MID, bg="#00080d", font=font_body(13)).pack(pady=(0, 14))
        
        tk.Label(self.setup_frame, text=T("GEMINI API KEY"),
                 fg=C_DIM, bg="#00080d", font=font_body(12)).pack(pady=(8, 4))

        self.api_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(14), show="*")
        self.api_entry.pack(pady=(0, 8), ipady=5)

        current_key = str(config.get("gemini_api_key", "") or "")
        if current_key:
            self.api_entry.insert(0, current_key)

        tk.Label(self.setup_frame, text=T("OPENROUTER API KEY"),
                 fg=C_DIM, bg="#00080d", font=font_body(12)).pack(pady=(10, 4))

        self.openrouter_api_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(14), show="*")
        self.openrouter_api_entry.pack(pady=(0, 8), ipady=5)
        
        current_or_key = str(config.get("openrouter_api_key", "") or "")
        if current_or_key:
            self.openrouter_api_entry.insert(0, current_or_key)

        buttons = tk.Frame(self.setup_frame, bg="#00080d")
        buttons.pack(pady=14)

        def _on_kaydet():
            self.sound.play_click()
            self._save_api_key()

        tk.Button(buttons, text=f"\u2714 {T('SAVE')}",
                  command=_on_kaydet, bg=C_BG, fg=C_PRI,
                  activebackground="#003344", font=font_body_bold(13),
                  borderwidth=0, padx=24, pady=10).pack(side="left", padx=8)

        if edit_mode:
            def _on_kapat():
                self.sound.play_click()
                self._close_setup_ui()

            tk.Button(buttons, text=T("CLOSE"),
                      command=_on_kapat, bg="#08111a", fg=C_DIM,
                      activebackground="#10202b", font=font_body_bold(13),
                      borderwidth=0, padx=24, pady=10).pack(side="left", padx=8)

    def _save_api_key(self):
        was_ready = self._api_key_ready
        key = self.api_entry.get().strip() if self.api_entry else ""
        or_key = self.openrouter_api_entry.get().strip() if self.openrouter_api_entry else ""
        
        if not key and not or_key:
            return
            
        save_app_config(
            {
                "gemini_api_key": key,
                "openrouter_api_key": or_key,
                "voice": self._current_voice,
            }
        )
        self._close_setup_ui()
        self._api_key_ready = True
        self._refresh_settings_status()
        self._signal_api_key_ready()
        if was_ready:
            self.write_log("SYS: API ayarlari guncellendi.")
        else:
            self.set_state("LISTENING")
            self.write_log("SYS: JARVIS hazır. Dinliyorum...")

    # -- Webcam --------------------------------------------------------------

    def toggle_webcam(self):
        """Webcam penceresini aç/kapat."""
        try:
            if self._webcam_window and self._webcam_window.winfo_exists():
                self._close_webcam_window()
            else:
                self._open_webcam_window()
        except Exception as e:
            self.write_log(f"SYS: Webcam hatasi: {e}")

    def _open_webcam_window(self):
        if not self.webcam.is_available:
            self.write_log("SYS: OpenCV veya PIL bulunamadi.")
            return

        if self._webcam_window and self._webcam_window.winfo_exists():
            self._webcam_window.lift()
            return

        try:
            self._webcam_feed_active = False
            win = tk.Toplevel(self.root)
            win.title("JARVIS Webcam")
            root_x = self.root.winfo_x()
            root_w = self.root.winfo_width()
            screen_w = self.root.winfo_screenwidth()
            wx = min(root_x + root_w + 20, screen_w - 440)
            wy = max(self.root.winfo_y(), 50)
            win.geometry(f"420x340+{wx}+{wy}")
            win.configure(bg="#041111")
            win.resizable(False, False)
            win.protocol("WM_DELETE_WINDOW", self._close_webcam_window)
            self._webcam_window = win

            header = tk.Label(win, text="WEBCAM", fg=C_PRI, bg="#041111",
                              font=font_body_bold(11))
            header.pack(pady=(10, 5))

            canvas = tk.Canvas(win, bg="#000000", width=400, height=280,
                               highlightthickness=0)
            canvas.pack(padx=10)
            self._webcam_canvas = canvas

            self._webcam_status_label = tk.Label(
                win, text="Starting...", fg=C_MID, bg="#041111",
                font=font_body(9))
            self._webcam_status_label.pack(pady=(4, 2))

            self.write_log("SYS: Webcam baslatildi.")
            self._start_webcam_feed()
        except Exception as e:
            self.write_log(f"SYS: Webcam penceresi acilamadi: {e}")
            self._close_webcam_window()

    def _close_webcam_window(self):
        self._stop_webcam_feed()
        if self._webcam_window:
            try:
                self._webcam_window.destroy()
            except Exception:
                pass
            self._webcam_window = None
            self._webcam_canvas = None

    def _toggle_webcam_feed(self):
        if self._webcam_feed_active:
            self._stop_webcam_feed()
        else:
            self._start_webcam_feed()

    def _start_webcam_feed(self):
        if not self.webcam.is_running:
            ok = self.webcam.start()
            if not ok:
                self.write_log("SYS: Kamera acilamadi!")
                if getattr(self, "_webcam_status_label", None):
                    self._webcam_status_label.config(text="Camera error", fg=C_RED)
                return
        self._webcam_feed_active = True
        self._draw_webcam_button()
        if getattr(self, "_webcam_status_label", None):
            self._webcam_status_label.config(text="LIVE", fg=C_GREEN)
        self._update_webcam_feed()

    def _stop_webcam_feed(self):
        self._webcam_feed_active = False
        if self.webcam.is_running:
            self.webcam.stop()
        self._draw_webcam_button()

    def _update_webcam_feed(self):
        if not self._webcam_feed_active or not self._webcam_canvas:
            return
        rgb = self.webcam.get_frame_rgb()
        if rgb is not None:
            try:
                img = Image.fromarray(rgb)
                img = img.resize((400, 280), Image.Resampling.LANCZOS)
                self._webcam_photo = ImageTk.PhotoImage(img)
                self._webcam_canvas.delete("all")
                self._webcam_canvas.create_image(0, 0, anchor="nw",
                                                  image=self._webcam_photo)
            except Exception:
                pass
        if self._webcam_feed_active and self._webcam_window and self._webcam_window.winfo_exists():
            self.root.after(66, self._update_webcam_feed)

    def _webcam_capture_photo(self):
        path = self.webcam.capture_photo()
        if path:
            self.write_log(f"SYS: Fotoğraf kaydedildi: {Path(path).name}")
            self.sound.play_sfx("done")

    def _webcam_analyze(self):
        """Mevcut kareyi AI'a gönder — analiz etmesini iste."""
        b64 = self.webcam.get_frame_base64(quality=80)
        if not b64:
            self.write_log("SYS: Kare alinamadi!")
            return
        self.write_log("SYS: Webcam karesi AI'a gonderiliyor...")
        self.sound.play_sfx("think")
        # Medyayı main.py'deki out_queue'ye gönder (metin prompt ile birlikte)
        if hasattr(self, 'on_send_media') and self.on_send_media:
            self.on_send_media({
                "data": b64,
                "mime_type": "image/jpeg",
                "text": "Kamerada ne goruyorsun? Bu kareyi detaylica analiz et."
            })

    # -- Chat Sidebar ------------------------------------------------------

    def toggle_sidebar(self):
        if self._sidebar_open:
            self._close_sidebar()
        else:
            self._open_sidebar()

    def _open_sidebar(self):
        self._sidebar_open = True
        self._refresh_sidebar_list()
        sw = self.LEFT_W - 12
        btn_y = int(HDR_H + (self.H - HDR_H - FOOTER_H) * 0.78)
        sx = 6
        sy = btn_y + 26
        sh = self.H - sy - FOOTER_H - 8
        self._sidebar_frame.place(x=sx, y=sy, width=sw, height=sh)
        self._sidebar_frame.lift()

    def _close_sidebar(self):
        self._sidebar_open = False
        self._sidebar_frame.place_forget()

    def _refresh_sidebar_list(self):
        for w in self._sidebar_inner.winfo_children():
            w.destroy()
        for conv in self.chat_mgr.conversations:
            is_current = conv.id == self.chat_mgr.current_id
            bg = "#0a1a1a" if is_current else "#020a0a"
            fg = C_PRI if is_current else C_MID
            row = tk.Frame(self._sidebar_inner, bg=bg)
            row.pack(fill="x", padx=2, pady=1)
            title_btn = tk.Button(
                row, text=conv.title[:24], fg=fg, bg=bg,
                activeforeground=C_PRI, activebackground="#0a1a1a",
                font=font_body(10), bd=0, anchor="w",
                padx=4, pady=3, cursor="hand2",
                command=lambda cid=conv.id: self._switch_chat(cid))
            title_btn.pack(side="left", fill="x", expand=True)
            rename_btn = tk.Button(
                row, text="R", fg=C_MID, bg=bg,
                activeforeground=C_PRI, activebackground="#0a1a1a",
                font=font_body_bold(9), bd=0, width=2, cursor="hand2",
                command=lambda cid=conv.id: self._rename_chat(cid))
            rename_btn.pack(side="right")
            del_btn = tk.Button(
                row, text="X", fg=C_RED, bg=bg,
                activeforeground=C_BG, activebackground="#8b0000",
                font=font_body_bold(9), bd=0, width=2, cursor="hand2",
                command=lambda cid=conv.id: self._delete_chat(cid))
            del_btn.pack(side="right")

    def _new_chat(self):
        self.chat_mgr.new_conversation()
        self._refresh_sidebar_list()
        self._clear_chat_log()
        self.write_log(f"SYS: {T('NEW CHAT')}")
        self.sound.play_click()

    def _switch_chat(self, conv_id):
        self.chat_mgr.switch_to(conv_id)
        self._refresh_sidebar_list()
        self._load_chat_log()
        self.sound.play_click()

    def _rename_chat(self, conv_id):
        conv = next((c for c in self.chat_mgr.conversations if c.id == conv_id), None)
        if not conv:
            return
        import tkinter.simpledialog as sd
        new_title = sd.askstring("Yeniden Adlandir", "Sohbet adi:", initialvalue=conv.title, parent=self.root)
        if new_title and new_title.strip():
            conv.title = new_title.strip()[:50]
            self.chat_mgr.save()
            self._refresh_sidebar_list()
        self.sound.play_click()

    def _delete_chat(self, conv_id):
        if len(self.chat_mgr.conversations) <= 1:
            return
        self.chat_mgr.delete_conversation(conv_id)
        self._refresh_sidebar_list()
        self._load_chat_log()
        self.sound.play_click()

    def _clear_chat_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _load_chat_log(self):
        self._clear_chat_log()
        for msg in self.chat_mgr.get_recent(50):
            if msg.role == "user":
                self.write_log(f"Siz: {msg.text}", tag="you")
            else:
                self.write_log(f"JARVIS: {msg.text}", tag="ai")

    def _save_user_message(self, text):
        self.chat_mgr.add_message("user", text)

    def _save_ai_message(self, text):
        self.chat_mgr.add_message("assistant", text)
