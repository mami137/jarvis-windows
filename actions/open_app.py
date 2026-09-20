"""
Uygulama açma — Windows için os.startfile / start komutu ile çalışır.
"""

import os
import re
import shutil
import subprocess
import unicodedata


def _fold(text: str) -> str:
    """Türkçe karakter ve aksan bağımsız normalleştirme: ç->c, ğ->g, ı->i ..."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold().replace("ı", "i").replace("İ", "i")


def _strip_suffixes(raw: str) -> str:
    """Uygulama adının sonundaki Türkçe çekim eklerini temizler."""
    text = (raw or "").strip()
    text = re.sub(
        r"\s*(uygulaması|uygulamam|uygulamasını|uygulamayı|programını|programı)\s*$",
        "", text, flags=re.IGNORECASE)
    for suffix in [" uygulaması", " uygulamasını", " uygulamanı", " uygulamayı",
                   " gezginini", " gezginine", " klasörünü",
                   "'i", "'ı", "'ü", "'u",
                   "yi", "yı", "yü", "yu", "yini", "yında"]:
        if len(text) > len(suffix) and text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


APP_ALIASES = {
    "edge":              "msedge",
    "microsoft edge":    "msedge",
    "chrome":            "chrome",
    "google chrome":     "chrome",
    "tarayıcı":          "chrome",
    "tarayici":          "chrome",
    "browser":           "chrome",
    "firefox":           "firefox",
    "terminal":          "cmd",
    "cmd":               "cmd",
    "komut istemi":      "cmd",
    "komut":             "cmd",
    "powershell":        "powershell",
    "power shell":       "powershell",
    "explorer":          "explorer",
    "dosya gezgini":     "explorer",
    "dosyalar":          "explorer",
    "dosya":             "explorer",
    "file explorer":     "explorer",
    "bilgisayar":        "explorer",
    "bu bilgisayar":     "explorer",
    "spotify":           "Spotify",
    "vscode":            "code",
    "vs code":           "code",
    "code":              "code",
    "visual studio code": "code",
    "discord":           "Discord",
    "slack":             "Slack",
    "whatsapp":          "WhatsApp",
    "telegram":          "Telegram",
    "zoom":              "Zoom",
    "steam":             "steam",
    "epic games":        "com.epicgames.launcher",
    "notepad":           "notepad",
    "notlar":            "notepad",
    "not defteri":       "notepad",
    "word":              "winword",
    "excel":             "excel",
    "powerpoint":        "powerpnt",
    "calculator":        "calc",
    "hesap makinesi":    "calc",
    "task manager":      "taskmgr",
    "görev yöneticisi":  "taskmgr",
    "settings":          "ms-settings:",
    "ayarlar":           "ms-settings:",
    "paint":             "mspaint",
    "wordpad":           "wordpad",
    "snipping tool":     "SnippingTool",
    "ekran alıntısı":    "SnippingTool",
    "photos":            "ms-photos:",
    "fotoğraflar":       "ms-photos:",
    "fotograflar":       "ms-photos:",
    "maps":              "bingmaps:",
    "haritalar":         "bingmaps:",
    "mail":              "outlookmail:",
    "e posta":           "outlookmail:",
    "calendar":          "outlookcal:",
    "takvim":            "outlookcal:",
    "store":             "ms-windows-store:",
    "mağaza":            "ms-windows-store:",
    "music":             "mswindowsmusic:",
    "müzik":             "mswindowsmusic:",
    "muzik":             "mswindowsmusic:",
    "notion":            "Notion",
    "obsidian":          "Obsidian",
    "minecraft":         r"C:\Users\m7268\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Legacy Launcher Stable.lnk",
    "mc":                r"C:\Users\m7268\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Legacy Launcher Stable.lnk",
    "antigravity":       r"C:\Users\m7268\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Antigravity.lnk",
    "anti gravity":      r"C:\Users\m7268\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Antigravity.lnk",
}

# Türkçe karakterden bağımsız (fold-edilmiş) alias konumları
_FOLDED_ALIASES = {_fold(k): v for k, v in APP_ALIASES.items()}

URI_SCHEMES = {
    "ms-settings:", "ms-photos:", "bingmaps:", "outlookmail:",
    "outlookcal:", "ms-windows-store:", "mswindowsmusic:",
}


def _strip_ending_suffix(word: str) -> str:
    """Tek kelimenin sonundaki Türkçe çekim ekini at: dosyaları→dosyalar, makinesini→makinesi,
    exceli→excel, yöneticisini→yöneticisi, tarayıcıyı→tarayıcı. Öncelik sırasına göre dener."""
    endings = ["nın", "nin", "nı", "ni", "yı", "yi",
               "sını", "sini", "sına", "sine", "ları", "leri",
               "ı", "ü", "u", "i"]
    for suffix in endings:
        if len(word) > len(suffix) and word.lower().endswith(suffix):
            head = word[:-len(suffix)].strip()
            if head:
                return head
    return word


def _progressive_resolve(stripped: str) -> str | None:
    """Uygulama adını kademeli kırparak her adımda alias'ı dener.
    'hesap makinesini' -> 'hesap makinesi' -> calc ; 'dosyaları' -> dosyalar -> explorer."""
    tokens = stripped.split()
    # Baştaki ünlem/hitap kelimelerini at (hey, jarvis, siri, ...)
    stop = {"hey", "hi", "a", "ac", "acabak", "bana", "lütfen", "lutfen"}
    while tokens and _fold(tokens[0]) in stop:
        tokens.pop(0)
    for cut in range(len(tokens), 0, -1):
        candidate = " ".join(tokens[:cut])
        hit = _FOLDED_ALIASES.get(_fold(candidate))
        if hit:
            return hit
        last = tokens[cut - 1]
        for variant in [last[:-1] if len(last) > 1 else last, _strip_ending_suffix(last)]:
            if variant and variant != last:
                modified = tokens[:cut - 1] + [variant]
                candidate2 = " ".join(modified)
                if candidate2 != candidate:
                    hit2 = _FOLDED_ALIASES.get(_fold(candidate2))
                    if hit2:
                        return hit2
    return None


def open_app(app_name: str) -> str:
    if not app_name:
        return "Uygulama adı belirtilmedi."

    # Türkçe çekim eklerini ve "aç" ifadeleri‍ni temizle
    stripped = app_name.strip()
    stripped = re.sub(r"\s*(aç|ac|başlat|calistir|çalıştır|open)\s*$", "", stripped, flags=re.IGNORECASE)
    folded = _fold(stripped)

    resolved = _FOLDED_ALIASES.get(folded)
    if resolved is None:
        resolved = _progressive_resolve(stripped)
    if resolved is None:
        resolved = app_name

    # 3) Dinamik Arama Hook'u (alias yoksa)
    if resolved == app_name or resolved == '':
        found_path = _find_app_dynamically(stripped or folded)
        if found_path:
            resolved = found_path


    # URI scheme (ms-settings: vb.)
    if any(resolved.startswith(scheme) for scheme in URI_SCHEMES):
        try:
            os.startfile(resolved)
            return f"{app_name} açıldı."
        except Exception as e:
            return f"'{app_name}' açılamadı: {e}"

    # PATH'teki executable
    exe_path = shutil.which(resolved)
    if exe_path:
        try:
            subprocess.Popen([exe_path], shell=False)
            return f"{app_name} açıldı."
        except Exception as e:
            return f"'{app_name}' açılamadı: {e}"

    # start komutu (Windows shell'i aracılığıyla)
    try:
        result = subprocess.run(
            f'start "" "{resolved}"',
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return f"{app_name} açıldı."
    except Exception:
        pass

    # os.startfile son çare
    try:
        os.startfile(resolved)
        return f"{app_name} açıldı."
    except Exception as e:
        return f"'{app_name}' bulunamadı veya açılamadı: {e}"


def _find_app_dynamically(app_name: str) -> str:
    """
    Eger APP_ALIASES icinde bulunamazsa sistemin Baslat Menusu ve Masustu 
    klasorlerini tarayarak (Fuzzy Match) en cok benzeyen uygulamayi bulur.
    """
    import os
    
    # Aranacak klasorler
    user_profile = os.environ.get("USERPROFILE", "C:\\Users\\Default")
    program_data = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
    
    search_dirs = [
        os.path.join(user_profile, "Desktop"),
        os.path.join(user_profile, "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(program_data, "Microsoft", "Windows", "Start Menu", "Programs")
    ]

    needle = _fold(app_name or "")
    app_words = [w for w in needle.split() if len(w) > 1]
    best_match_path = None
    best_score = 0

    for d in search_dirs:
        if not os.path.exists(d):
            continue
        for root, dirs, files in os.walk(d):
            for file in files:
                if not (file.lower().endswith(".lnk") or file.lower().endswith(".exe")):
                    continue
                clean = file.lower().replace(".lnk", "").replace(".exe", "")
                name = _fold(clean)

                if name == needle:
                    return os.path.join(root, file)
                if needle in name:
                    return os.path.join(root, file)

                # Kelime kapsama skoru: aradığımız kelimelerin kaçı dosya adında
                score = 0
                for word in app_words:
                    if word in name:
                        score += 2
                    elif any(word in w for w in name.split()):
                        score += 1
                if score > best_score:
                    best_score = score
                    best_match_path = os.path.join(root, file)

    return best_match_path if best_match_path else ""
