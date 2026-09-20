import json
import urllib.request
import urllib.error
from app_config import get_app_config_value
from core.auto_router import get_manual_model_slug
from net_usage import add_sent, add_recv

# Gemini formatındaki tool_declarations'ı OpenAI formatına çevirir
def convert_tools_to_openai(gemini_tools):
    openai_tools = []
    for tool in gemini_tools:
        # type=OBJECT'i type=object'e çevir, alt özellikleri küçük harf yap
        props = tool.get("parameters", {}).get("properties", {})
        req = tool.get("parameters", {}).get("required", [])
        
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": req
                }
            }
        })
    return openai_tools


def ask_openrouter(messages, tools=None):
    """
    OpenRouter API'sini kullanarak yanıt veya Tool Call döndürür.
    messages: [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
    tools: Gemini formatında tool listesi (opsiyonel)
    
    Dönüş formatı (Dict):
    {
        "type": "text" veya "tool_calls",
        "content": "Metin cevap",
        "tool_calls": [{"name": "func_name", "args": {"arg1": "val"}}]
    }
    """
    api_key = get_app_config_value("openrouter_api_key", "")
    if not api_key:
        return {"type": "text", "content": "Sistem hatası: OpenRouter API anahtarı ayarlanmamış."}

    # Kullanıcı manuel model seçtiyse onu kullan; yoksa varsayılan Llama 3.3 (tool calling destekler)
    model = get_manual_model_slug() or "meta-llama/llama-3.3-70b-instruct"

    payload = {
        "model": model,
        "messages": messages
    }

    if tools:
        payload["tools"] = convert_tools_to_openai(tools)
        payload["tool_choice"] = "auto"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/alpunlu12-commits",
        "X-Title": "JARVIS V2",
        "Content-Type": "application/json"
    }

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read()
            add_sent(len(req.data))
            add_recv(len(raw))
            data = json.loads(raw.decode("utf-8"))
            
            message = data["choices"][0]["message"]
            
            # Tool call var mı?
            if "tool_calls" in message and message["tool_calls"]:
                t_calls = []
                for tc in message["tool_calls"]:
                    if tc["type"] == "function":
                        fn = tc["function"]
                        t_calls.append({
                            "id": tc.get("id", "call_id"),
                            "name": fn["name"],
                            "args": json.loads(fn.get("arguments", "{}"))
                        })
                return {"type": "tool_calls", "tool_calls": t_calls, "content": ""}
            
            # Normal metin cevabı
            return {"type": "text", "content": message.get("content", "Anlaşılamadı.")}

    except urllib.error.URLError as e:
        return {"type": "text", "content": f"Bağlantı hatası: {e}"}
    except Exception as e:
        return {"type": "text", "content": f"Hata oluştu: {e}"}
