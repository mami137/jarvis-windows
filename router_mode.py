import asyncio
import threading
import speech_recognition as sr

from app_config import get_app_config_value
from ui import JarvisUI
from core.llm_router import ask_openrouter
from actions.tts import speak_text
from memory.memory_manager import load_memory, format_memory_for_prompt
import main as main_module

class JarvisRouter:
    def __init__(self, ui: JarvisUI):
        self.ui = ui
        self._paused = False
        self._history = []
        
        self.ui.on_text_command = self._on_text_command
        self.ui.on_pause_toggle = self._on_pause_toggle
        
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 4000
        self.recognizer.dynamic_energy_threshold = True

    def _on_pause_toggle(self, paused: bool):
        self._paused = paused

    def _on_text_command(self, text: str):
        if self._paused:
            return
        self.ui.write_log(f"Siz: {text}")
        threading.Thread(target=self._handle_input, args=(text,), daemon=True).start()

    def set_speaking(self, value: bool):
        if value:
            self.ui.set_state("SPEAKING")
        else:
            self.ui.set_state("LISTENING")

    def _get_system_messages(self):
        memory = load_memory()
        mem_str = format_memory_for_prompt(memory)
        sys_p = main_module.load_system_prompt()
        
        full_sys = sys_p
        if mem_str:
            full_sys = f"{mem_str}\n\n{sys_p}"
            
        return [{"role": "system", "content": full_sys}]

    def _handle_input(self, user_text: str):
        self.ui.set_state("THINKING")
        
        if not self._history:
            self._history = self._get_system_messages()
            
        self._history.append({"role": "user", "content": user_text})
        
        self.ui.write_log("SYS: OpenRouter'a baglaniliyor...")
        response = ask_openrouter(self._history, tools=main_module.TOOL_DECLARATIONS)
        
        if response["type"] == "text":
            reply = response["content"]
            self._history.append({"role": "assistant", "content": reply})
            self.ui.write_log(f"JARVIS: {reply}")
            
            self.set_speaking(True)
            speak_text(reply, on_done=lambda: self.set_speaking(False), blocking=True)
            self.ui.set_state("LISTENING")
            
        elif response["type"] == "tool_calls":
            self.ui.write_log("SYS: Araç çağrılıyor...")
            
            for tc in response["tool_calls"]:
                self._run_tool(tc["name"], tc["args"])
            
            self.ui.set_state("LISTENING")

    def _run_tool(self, name, args):
        print(f"[ROUTER] 🔧 {name} {args}")
        try:
            dummy_fc = type("DummyFC", (object,), {"id": "1", "name": name, "args": args})()
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            jl = main_module.JarvisLive(self.ui)
            # Monkey patch the internal variables to avoid UI crashes
            jl._api_key_ready = True
            
            coro = jl._execute_tool(dummy_fc)
            res = loop.run_until_complete(coro)
            
            result_text = res.response["result"]
            
            self._history.append({
                "role": "assistant", 
                "content": f"Araç '{name}' çalıştı ve şu sonucu verdi: {result_text}. Bu sonucu kullanıcıya doğal bir dille söyle."
            })
            
            response2 = ask_openrouter(self._history)
            if response2["type"] == "text":
                reply = response2['content']
                self._history.append({"role": "assistant", "content": reply})
                self.ui.write_log(f"JARVIS: {reply}")
                self.set_speaking(True)
                speak_text(reply, on_done=lambda: self.set_speaking(False), blocking=True)
            
        except Exception as e:
            self.ui.write_log(f"ERR: Tool Hatası: {e}")
            self.set_speaking(True)
            speak_text("Araç çalıştırılırken bir hata oluştu.", on_done=lambda: self.set_speaking(False), blocking=True)

    async def run(self):
        self.ui.write_log("SYS: OpenRouter Modu hazır. Yazarak komut verebilirsiniz.")
        self.ui.set_state("LISTENING")
        
        while True:
            if self._paused:
                await asyncio.sleep(1)
                continue
            
            try:
                # Sesi Google ile dinle ve metne çevir (Sadece mikrofon dinlenirken uyanmak istersen burayı açarsın)
                # Şimdilik text (UI üzerinden) girişlere odaklanıldı. 
                # Gerçek zamanlı VAD ve Wakeup için projenin kendi wakeup listener'ı main.py'de bağlıdır.
                pass
            except Exception as e:
                pass
                
            await asyncio.sleep(0.5)
