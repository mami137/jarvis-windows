import time

# Arka planda bekleyen zamanlayıcılar listesi
timers = []
_timer_id = 0

def add_timer(seconds_from_now: int, message: str) -> str:
    global _timer_id
    _timer_id += 1
    trigger_at = time.time() + seconds_from_now
    timers.append({
        "id": _timer_id,
        "trigger_time": trigger_at,
        "message": message,
        "triggered": False
    })
    return f"Zamanlayıcı ayarlandı. {seconds_from_now} saniye sonra hatırlatılacak: '{message}'"

def check_timers() -> list:
    """Süresi dolan ve tetiklenmemiş mesajları döndürür."""
    now = time.time()
    triggered_msgs = []
    for t in timers:
        if not t["triggered"] and now >= t["trigger_time"]:
            t["triggered"] = True
            triggered_msgs.append(t["message"])
    return triggered_msgs
