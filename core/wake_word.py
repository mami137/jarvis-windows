"""
Wake Word Dedektörü — Vosk ile offline "Jarvis" / "Hey Jarvis" algılama.
Arka planda mikrofonu dinler, wake word duyunca callback çağırır.
"""

import json
import os
import sys
import threading
import queue
import zipfile
import urllib.request

import pyaudio

VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
VOSK_MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vosk-model-en")

WAKE_WORDS = [
    "jarvis", "hey jarvis", "hey jarvis",
]

# Ses ayarları (wake word için düşük kalite yeterli = düşük CPU)
WW_RATE = 16000
WW_CHANNELS = 1
WW_CHUNK = 4000


def _ensure_model() -> str:
    """Vosk Türkçe modelini indir (yoksa) ve yolunu döndür."""
    abs_model = os.path.abspath(VOSK_MODEL_DIR)

    if os.path.isdir(abs_model) and os.listdir(abs_model):
        return abs_model

    print("[WAKE] Vosk İngilizce Wake-Word modeli indiriliyor (~40 MB)...")
    zip_path = abs_model + ".zip"
    os.makedirs(os.path.dirname(abs_model), exist_ok=True)

    urllib.request.urlretrieve(VOSK_MODEL_URL, zip_path)

    print("[WAKE] Model çıkarılıyor...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        # ZIP içindeki klasör adını bul
        top_dirs = {n.split("/")[0] for n in zf.namelist() if "/" in n}
        zf.extractall(os.path.dirname(abs_model))

        # Çıkan klasörü istenen isme taşı
        if top_dirs:
            extracted = os.path.join(os.path.dirname(abs_model), top_dirs.pop())
            if extracted != abs_model and os.path.isdir(extracted):
                os.rename(extracted, abs_model)

    try:
        os.remove(zip_path)
    except Exception:
        pass

    print("[WAKE] Model hazır.")
    return abs_model


class WakeWordListener:
    """Arka planda mikrofonu dinler, 'Jarvis' duyunca on_wake çağırır."""

    def __init__(self, on_wake: callable):
        self.on_wake = on_wake
        self._running = False
        self._paused = False
        self._thread = None
        self._last_trigger_time = 0  # Son tetikleme zamanı

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        print("[WAKE] Wake word dinleniyor...")

    def stop(self):
        self._running = False

    def pause(self):
        """Ana menü aktifken wake word'ü duraklat (mikrofon çakışmasını önler)."""
        self._paused = True
        print("[WAKE] Wake word duraklatıldı.")

    def resume(self):
        """Tray moduna dönünce wake word'ü devam ettir."""
        self._paused = False
        print("[WAKE] Wake word devam ediyor.")

    def _listen_loop(self):
        from vosk import Model, KaldiRecognizer

        model_path = _ensure_model()
        model = Model(model_path)  # Modeli yükle
        # Sadece bu kelimelere izin ver
        grammar = '["jarvis", "hey jarvis", "[unk]"]'
        rec = KaldiRecognizer(model, WW_RATE, grammar)

        pya = pyaudio.PyAudio()
        stream = None

        while self._running:
            # Ana menü aktifken mikrofonu kullanma (Serbest bırak)
            if self._paused:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                    stream = None
                import time
                time.sleep(0.5)
                continue

            # Mikrofonu aç (kopma durumunda yeniden dene)
            if stream is None:
                try:
                    stream = pya.open(
                        format=pyaudio.paInt16,
                        channels=WW_CHANNELS,
                        rate=WW_RATE,
                        input=True,
                        frames_per_buffer=WW_CHUNK,
                    )
                except Exception as e:
                    print(f"[WAKE] Mikrofon açılamadı: {e}")
                    import time
                    time.sleep(2)
                    continue

            try:
                data = stream.read(WW_CHUNK, exception_on_overflow=False)
            except Exception:
                # Mikrofon koptu — kapat ve yeniden dene
                try:
                    stream.close()
                except Exception:
                    pass
                stream = None
                continue

            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = result.get("text", "").lower().strip()
                if text:
                    print(f"[WAKE DUYULAN - TAM]: {text}")
                # Sadece tam eşleşme ile tetikle (kısmi eşleşme yapma)
                if text and any(w == text for w in WAKE_WORDS):
                    import time
                    now = time.time()
                    # Son tetiklemeden beri 3 saniye geçtiyse tetikle
                    if now - self._last_trigger_time > 3:
                        self._last_trigger_time = now
                        print(f"[WAKE] 🎯 Wake word algılandı: '{text}'")
                        rec.Reset()  # Tanıyıcıyı sıfırla
                        try:
                            self.on_wake()
                        except Exception as e:
                            print(f"[WAKE] Callback hatası: {e}")
                    else:
                        print(f"[WAKE] Tetikleme reddedildi (3sn bekleme): '{text}'")
            else:
                # Partial result'ları tamamen yoksay (çok hassas tetiklemeyi önle)
                pass

        # Temizlik
        if stream:
            try:
                stream.close()
            except Exception:
                pass
        pya.terminate()
