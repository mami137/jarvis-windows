import json
import urllib.request
import urllib.error
from app_config import get_app_config_value
from net_usage import add_sent, add_recv

# ── Kullanıcının manuel seçebileceği (ekli) modeller ────────────────────────
MODEL_SELECT_OPTIONS = [
    {"key": "auto", "label": "Otomatik"},
    {"key": "claude_sonnet_5", "label": "Claude Sonnet 5"},
    {"key": "deepseek_r1", "label": "DeepSeek R1"},
    {"key": "gemini_2_5_flash", "label": "Gemini 2.5 Flash"},
    {"key": "qwen_2_5_72b", "label": "Qwen 2.5 72B"},
    {"key": "nemotron_3_ultra", "label": "Nemotron 3 Ultra"},
    {"key": "llama_3_3_70b", "label": "Llama 3.3 70B"},
]

MODEL_SLUGS = {
    "auto": "",
    "claude_sonnet_5": "anthropic/claude-sonnet-5",
    "deepseek_r1": "deepseek/deepseek-r1",
    "gemini_2_5_flash": "google/gemini-2.5-flash",
    "qwen_2_5_72b": "qwen/qwen-2.5-72b-instruct",
    "nemotron_3_ultra": "nvidia/nemotron-3-ultra-550b-a55b",
    "llama_3_3_70b": "meta-llama/llama-3.3-70b-instruct",
}


def get_manual_model_key() -> str:
    key = str(get_app_config_value("expert_model", "auto") or "").strip()
    if key not in MODEL_SLUGS:
        return "auto"
    return key


def get_manual_model_slug() -> str:
    return MODEL_SLUGS.get(get_manual_model_key(), "")


def determine_best_model(task_description: str, task_category: str = "") -> str:
    # Manuel seçim yapıldıysa kategori yönlendirmesini ez (override et)
    manual = get_manual_model_slug()
    if manual:
        return manual

    category = task_category.lower()
    text = (task_description or "").lower()

    # 1) Karmaşık kod mimarileri, agentic sistemler, derin mantık → Claude Sonnet 5
    if category == "code" or "kod" in category or "yazılım" in category or "kod" in text or "agent" in text:
        return "anthropic/claude-sonnet-5"
    # 2) Matematik, algoritma, teorik mantık → DeepSeek R1
    elif category == "math" or "mantık" in category or "hesap" in category or "matematik" in text or "algoritma" in text or "ispat" in text or "teorem" in text:
        return "deepseek/deepseek-r1"
    # 3) Türkçe, JSON/katı talimat uygulama → Qwen 2.5 72B
    elif category == "tr" or "türkçe" in text or "türk" in category or "json" in text or "yapılandırılmış" in text:
        return "qwen/qwen-2.5-72b-instruct"
    # 4) Uzun metin özeti / büyük veri / geniş kapsamlı araştırma → Nemotron 3 Ultra (ücretsiz)
    elif category == "summary" or "özet" in text or "özetle" in text or "uzun metin" in text or "büyük veri" in text or "geniş" in text or "summar" in text:
        return "nvidia/nemotron-3-ultra-550b-a55b"
    # 5) Geniş doküman okuma / veri araştırması / hızlı yanıt → Gemini 2.5 Flash
    elif category == "research" or "araştırma" in category or "makale" in category or "metin" in category or "doküman" in text or "belge" in text or "araştır" in text or "veri analiz" in text:
        return "google/gemini-2.5-flash"
    else:
        return "meta-llama/llama-3.3-70b-instruct"  # Günlük/sohbet → dengeli Llama


def _request_stream(model: str, messages: list, api_key: str):
    payload = {
        "model": model,
        "messages": messages,
        "stream": True
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/alpunlu12-commits",
        "X-Title": "JARVIS V2 Expert Routing",
        "Content-Type": "application/json"
    }

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    add_sent(len(req.data))
    return req


def _consume_stream(req, on_delta=None) -> list:
    collected = []
    with urllib.request.urlopen(req, timeout=60) as response:
        for raw_line in response:
            add_recv(len(raw_line))
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if not data_str or data_str == "[DONE]":
                continue
            try:
                chunk = json.loads(data_str)
            except Exception:
                continue
            if "choices" not in chunk or not chunk["choices"]:
                continue
            delta = chunk["choices"][0].get("delta") or {}
            piece = (delta.get("content") or "") or ""
            if piece:
                collected.append(piece)
                if on_delta:
                    on_delta(piece)
    return collected


def stream_expert_task(task_description: str, task_category: str):
    """
    OpenRouter'ın SSE (Server-Sent Events) akışını (stream: true) tüketen generator.
    Her token geldiği anda ANLIK olarak yield eder — toplu bekleme YOKTUR.

    Her adımda bir sözlük üretir:
      {"type": "delta", "text": "<kısmi metin>", "model": "<seçilen model>"}  → token geldi
      {"type": "done",  "model": ..., "result": "<tam metin>"}                → akış bitti
      {"type": "error", "message": "..."}                                    → hata
    """
    api_key = get_app_config_value("openrouter_api_key", "")
    if not api_key:
        yield {"type": "error", "message": "OpenRouter API anahtarı ayarlanmamış."}
        return

    model = determine_best_model(task_description, task_category)

    messages = [
        {"role": "system", "content": "Sen Jarvis'in (AI) uzman yardımcısısın. Kullanıcı Gemini'ye çok zor veya kapsamlı bir istekte bulunduğu için bu görev sana devredildi. Görevi en iyi ve eksiksiz şekilde yerine getir. DİKKAT: Görev Türkçe metin üretimini içeriyorsa, Türkçe karakterleri (ç, ğ, ı, İ, ö, ş, ü) ASLA ASCII'ye çevirme. 'genc', 'kulub', 'istikrar' gibi okunaksız şekiller YANLIŞTIR; doğrusu 'genç, kulüp, istikrar, kariyer, başarı' gibi aslına uygun yaz."},
        {"role": "user", "content": f"Lütfen şu görevi yerine getir:\n\n{task_description}"}
    ]

    FALLBACK_MODELS = ["meta-llama/llama-3.3-70b-instruct", "google/gemini-2.5-flash"]
    candidates = [model] + [m for m in FALLBACK_MODELS if m != model]

    last_error = ""
    for attempt, candidate in enumerate(candidates):
        try:
            req = _request_stream(candidate, messages, api_key)
            collected = []
            got_any = False

            # ── GERÇEK ANLIK STREAMING ──
            # HTTP yanıtını satır satır oku, her delta'yı ANINDA yield et.
            in_think_block = False
            think_buffer = ""
            with urllib.request.urlopen(req, timeout=120) as response:
                for raw_line in response:
                    add_recv(len(raw_line))
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data_str)
                    except Exception:
                        continue
                    if "choices" not in chunk or not chunk["choices"]:
                        continue
                    delta = chunk["choices"][0].get("delta") or {}
                    piece = delta.get("content") or ""
                    if piece:
                        got_any = True
                        
                        # ── THINK (DÜŞÜNME) FİLTRESİ ──
                        think_buffer += piece
                        out_piece = ""
                        
                        while think_buffer:
                            if not in_think_block:
                                idx = think_buffer.find("<think>")
                                if idx != -1:
                                    out_piece += think_buffer[:idx]
                                    in_think_block = True
                                    think_buffer = think_buffer[idx + 7:]
                                else:
                                    partial = False
                                    for i in range(1, 8):
                                        if think_buffer.endswith("<think>"[:i]):
                                            out_piece += think_buffer[:-i]
                                            think_buffer = think_buffer[-i:]
                                            partial = True
                                            break
                                    if not partial:
                                        out_piece += think_buffer
                                        think_buffer = ""
                                    break
                            else:
                                idx = think_buffer.find("</think>")
                                if idx != -1:
                                    in_think_block = False
                                    think_buffer = think_buffer[idx + 8:]
                                else:
                                    partial = False
                                    for i in range(1, 9):
                                        if think_buffer.endswith("</think>"[:i]):
                                            think_buffer = think_buffer[-i:]
                                            partial = True
                                            break
                                    if not partial:
                                        think_buffer = ""
                                    break
                        
                        if out_piece:
                            collected.append(out_piece)
                            # ⚡ ANLIK: her parça geldiği anda UI'ya iletilir
                            yield {"type": "delta", "text": out_piece, "model": candidate}

            if not got_any:
                last_error = "Model hiç içerik üretmedi (boş yanıt)."
                continue

            full_result = "".join(collected)
            if attempt == 0:
                yield {"type": "done", "model": candidate, "result": full_result}
            else:
                yield {"type": "done", "model": candidate, "result": full_result, "fallback": True}
            return

        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            last_error = f"HTTP {e.code}: {detail or str(e)}"
            continue
        except Exception as e:
            last_error = f"Hata oluştu: {str(e)}"
            continue

    yield {"type": "error", "message": last_error or "Bilinmeyen hata"}


def execute_expert_task(task_description: str, task_category: str) -> dict:
    """
    Geriye dönük uyumluluk sarmalayıcısı.
    Akış içeren stream_expert_task üretecini sonuna kadar tüketip
    tek bir sözlük döndürür.
    """
    content_parts = []
    for event in stream_expert_task(task_description, task_category):
        etype = event.get("type")
        if etype == "delta":
            content_parts.append(event.get("text", ""))
        elif etype == "done":
            return {"error": False, "model": event.get("model"), "result": event.get("result")}
        elif etype == "error":
            return {"error": True, "message": event.get("message", "Bilinmeyen hata")}
    return {"error": True, "message": "Sonuç alınamadı."}