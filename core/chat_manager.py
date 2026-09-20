"""Çoklu sohbet yöneticisi — JSON dosyasında saklama."""

import json
import threading
import time
import uuid
from pathlib import Path
from typing import List, Dict, Optional
from core.i18n import T


class ChatMessage:
    def __init__(self, role: str, text: str, timestamp: float = None):
        self.role = role  # "user" or "assistant"
        self.text = text
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "text": self.text,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatMessage":
        return cls(
            role=data.get("role", "user"),
            text=data.get("text", ""),
            timestamp=data.get("timestamp", 0),
        )


class ChatConversation:
    def __init__(self, conv_id: str = None, title: str = None):
        self.id = conv_id or str(uuid.uuid4())[:8]
        self.title = title or T("NEW CHAT")
        self.messages: List[ChatMessage] = []
        self.created_at = time.time()
        self.updated_at = time.time()

    def add_message(self, role: str, text: str):
        msg = ChatMessage(role, text)
        self.messages.append(msg)
        self.updated_at = time.time()
        # İlk kullanıcı mesajından başlık üret
        if role == "user" and len([m for m in self.messages if m.role == "user"]) == 1:
            clean = text.strip()
            # Prompt/command temizle
            for prefix in ["jarvis", "hey jarvis"]:
                if clean.lower().startswith(prefix):
                    clean = clean[len(prefix):].strip()
            self.title = clean[:40] + ("..." if len(clean) > 40 else "")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatConversation":
        conv = cls(
            conv_id=data.get("id"),
            title=data.get("title", "Sohbet"),
        )
        conv.messages = [ChatMessage.from_dict(m) for m in data.get("messages", [])]
        conv.created_at = data.get("created_at", 0)
        conv.updated_at = data.get("updated_at", 0)
        return conv


_SAVE_DEBOUNCE_SEC = 3.0


class ChatManager:
    def __init__(self, filepath: str = None):
        if filepath is None:
            filepath = str(Path.home() / ".jarvis" / "chats.json")
        self.filepath = Path(filepath)
        self.conversations: List[ChatConversation] = []
        self.current_id: Optional[str] = None
        self._current_cache: Optional[ChatConversation] = None
        self._dirty = False
        self._last_save_time = 0.0
        self._lock = threading.Lock()
        self.load()

    @property
    def current(self) -> Optional[ChatConversation]:
        if self._current_cache and self._current_cache.id == self.current_id:
            return self._current_cache
        for c in self.conversations:
            if c.id == self.current_id:
                self._current_cache = c
                return c
        self._current_cache = None
        return None

    def load(self):
        if not self.filepath.exists():
            self.conversations = []
            return
        try:
            data = json.loads(self.filepath.read_text(encoding="utf-8"))
            self.conversations = [ChatConversation.from_dict(c) for c in data.get("conversations", [])]
            self.current_id = data.get("current_id")
            self._current_cache = None
        except Exception:
            self.conversations = []

    def save(self):
        with self._lock:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "conversations": [c.to_dict() for c in self.conversations],
                "current_id": self.current_id,
            }
            self.filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._dirty = False
            self._last_save_time = time.monotonic()

    def _maybe_save(self):
        now = time.monotonic()
        if not self._dirty:
            return
        if now - self._last_save_time < _SAVE_DEBOUNCE_SEC:
            return
        self.save()

    def flush(self):
        """Force an immediate write if dirty (call on app exit)."""
        if self._dirty:
            self.save()

    def new_conversation(self) -> ChatConversation:
        conv = ChatConversation()
        self.conversations.insert(0, conv)
        self.current_id = conv.id
        self._current_cache = conv
        self.save()
        return conv

    def switch_to(self, conv_id: str):
        for c in self.conversations:
            if c.id == conv_id:
                self.current_id = conv_id
                self._current_cache = c
                self.save()
                return

    def delete_conversation(self, conv_id: str):
        self.conversations = [c for c in self.conversations if c.id != conv_id]
        if self.current_id == conv_id:
            self.current_id = self.conversations[0].id if self.conversations else None
            self._current_cache = None
        self.save()

    def add_message(self, role: str, text: str):
        conv = self.current
        if conv:
            conv.add_message(role, text)
            self._dirty = True
            self._maybe_save()

    def get_recent(self, limit: int = 20) -> List[ChatMessage]:
        conv = self.current
        if conv:
            return conv.messages[-limit:]
        return []

    def get_title(self, conv_id: str) -> str:
        conv = next((c for c in self.conversations if c.id == conv_id), None)
        if conv:
            return conv.title
        return "Sohbet"
