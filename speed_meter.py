"""
Cloudflare internet hız ölçümü — browser UA ile speed test uçları.

Arka plan thread'i belirli aralıkla:
  - https://speed.cloudflare.com/__down?bytes=N  → indirme hızı (Mbps)
  - https://speed.cloudflare.com/__up            → yükleme hızı (Mbps)
ölçer ve sonuçları atributlarda tutar. UI thread'i saniyede bir okur;
ölçüm başka thread'de olduğundan arayüzü kilitlemez.
"""

import os
import threading
import time
import urllib.request

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


class SpeedMeter:
    def __init__(self, interval=1, down_bytes=1048576, up_bytes=524288):
        self._interval = max(0.4, float(interval))
        self._down_bytes = int(down_bytes)
        self._up_bytes = int(up_bytes)
        self.running = False
        self.busy = False
        self.down_mbps = 0.0
        self.up_mbps = 0.0
        self.error = ""
        self.last_update = 0.0
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def _run(self):
        while self.running:
            self.busy = True
            try:
                self._measure()
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
            finally:
                self.busy = False
            deadline = time.time() + self._interval
            while self.running and time.time() < deadline:
                time.sleep(0.25)

    def _measure(self):
        # İndirme
        try:
            url = f"https://speed.cloudflare.com/__down?bytes={self._down_bytes}"
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=25) as r:
                got = 0
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    got += len(chunk)
            dt = time.time() - t0
            if dt > 0.2:
                self.down_mbps = got / dt * 8 / 1_000_000
        except Exception as e:
            self.error = f"down: {e}"

        # Yükleme
        try:
            payload = os.urandom(self._up_bytes)
            req = urllib.request.Request(
                "https://speed.cloudflare.com/__up", data=payload,
                method="POST",
                headers={"User-Agent": _UA, "Content-Type": "application/octet-stream"})
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=25) as r:
                r.read()
            dt = time.time() - t0
            if dt > 0.2:
                self.up_mbps = len(payload) / dt * 8 / 1_000_000
        except Exception as e:
            self.error = f"up: {e}"

        self.last_update = time.time()


if __name__ == "__main__":
    m = SpeedMeter(interval=10, down_bytes=2097152, up_bytes=1048576)
    m.start()
    seen = 0
    while seen < 20:
        time.sleep(1)
        print(f"down={m.down_mbps:.2f} Mbps up={m.up_mbps:.2f} Mbps "
              f"busy={m.busy} last={m.last_update:.0f} err={m.error!r}")
        if m.last_update and m.busy is False and m.down_mbps > 0:
            seen += 1
        if m.last_update and not m.busy and seen == 0:
            seen = 20
    m.stop()