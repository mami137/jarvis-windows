"""Webcam modülü — OpenCV ile canlı yayın ve görüntü yakalama."""

import threading
import time
import io
import base64
from pathlib import Path

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class WebcamManager:
    """Webcam akışını yönetir: başlat/durdur, kare yakala, JPEG'e dönüştür."""

    def __init__(self):
        self._cap = None
        self._running = False
        self._thread = None
        self._frame = None
        self._frame_lock = threading.Lock()
        self._fps = 15
        self._camera_index = 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_available(self) -> bool:
        return CV2_AVAILABLE and PIL_AVAILABLE

    def start(self, camera_index: int = 0) -> bool:
        if not self.is_available:
            return False
        if self._running:
            return True
        self._camera_index = camera_index
        try:
            self._cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
            if not self._cap.isOpened():
                self._cap = cv2.VideoCapture(camera_index)
            if not self._cap.isOpened():
                return False
            self._running = True
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            return True
        except Exception:
            return False

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        with self._frame_lock:
            self._frame = None

    def _capture_loop(self):
        interval = 1.0 / self._fps
        while self._running and self._cap and self._cap.isOpened():
            ret, frame = self._cap.read()
            if ret and frame is not None:
                with self._frame_lock:
                    self._frame = frame
            time.sleep(interval)
        self._running = False

    def get_frame_rgb(self):
        """Mevcut kareyi RGB formatında (PIL Image için) döndür."""
        with self._frame_lock:
            if self._frame is None:
                return None
            frame = self._frame.copy()
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def get_frame_jpeg_bytes(self, quality: int = 85) -> bytes:
        """Mevcut kareyi JPEG bytes olarak döndür (AI'a göndermek için)."""
        with self._frame_lock:
            if self._frame is None:
                return b""
            frame = self._frame.copy()
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes()

    def get_frame_base64(self, quality: int = 85) -> str:
        """Mevcut kareyi base64 JPEG string olarak döndür."""
        jpeg = self.get_frame_jpeg_bytes(quality)
        if not jpeg:
            return ""
        return base64.b64encode(jpeg).decode("ascii")

    def capture_photo(self, save_path: str = None) -> str:
        """Fotoğraf çek ve kaydet. Yolu döndür."""
        jpeg = self.get_frame_jpeg_bytes(quality=95)
        if not jpeg:
            return ""
        if save_path is None:
            save_path = str(Path.home() / "Pictures" / f"jarvis_webcam_{int(time.time())}.jpg")
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(jpeg)
        return save_path
