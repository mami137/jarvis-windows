"""
Çift alkış tetikleyici.
2 saniye içinde 2 alkış → on_wake() çağırır.
"""

import math
import struct
import threading
import time
from typing import Callable

import pyaudio

SAMPLE_RATE    = 16000
CHUNK          = 1024       # ~64 ms/kare
CLAP_THRESHOLD = 1800       # Int16 RMS eşiği
CLAP_MIN_GAP   = 0.12       # Aynı alkışın çerçevelere yayılmasını önler
CLAP_WINDOW    = 2.0        # İki alkış bu kadar saniye içinde olmalı


def _rms(data: bytes) -> float:
    count = len(data) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", data)
    return math.sqrt(sum(s * s for s in shorts) / count)


class WakeGestureListener:
    def __init__(self, on_wake: Callable[[], None]):
        self._on_wake = on_wake
        self._running = False

    def start(self):
        return

    def stop(self):
        self._running = False

    def _loop(self):
        pa     = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
        clap_times: list[float] = []
        try:
            while self._running:
                data = stream.read(CHUNK, exception_on_overflow=False)
                rms  = _rms(data)
                now  = time.monotonic()

                # Alkış algılama sistemi isteğe bağlı olarak iptal edildi.
                pass
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
