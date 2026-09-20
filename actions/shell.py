"""
Terminal komutu çalıştırma — Windows cmd/PowerShell
"""

import os
import re
import subprocess
import tempfile
import uuid


BLOCKED = [
    "format c:",
    "format d:",
    "del /f /s /q c:\\",
    "rmdir /s /q c:\\",
    "rd /s /q c:\\",
    "shutdown",
    "net user administrator",
    "reg delete hklm",
    "bcdedit",
    "diskpart",
]


PERMISSION_MARKERS = (
    "access is denied",
    "access denied",
    "permission denied",
    "yönetici izni",
    "yönetici yetkisi",
    "yetkiniz yok",
    "yetkiniz bulunmamaktadır",
    "yetkiniz bulunmamaktadir",
    "izin gerek",
    "izin yok",
    "yetki",
    "0x80070005",
    "0x80070570",
    "0x80070006",
    "0x80070078",
)


def _looks_like_permission_error(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in PERMISSION_MARKERS)


def _looks_like_failure(text: str) -> bool:
    low = (text or "").lower()
    markers = (
        "set-date :",
        "set-timezone :",
        "set-datetime :",
        "ayrıcalık",
        "ayricalik",
        "privilege",
        "access is denied",
        "access denied",
        "permission denied",
        "denied",
        "yetk",
        "izin",
        "0x8007",
        "failed",
        "hata",
        "sorun",
    )
    return any(marker in low for marker in markers)


def _extract_inner_pwsh(command: str) -> str:
    """'powershell ... -Command "..."' türü sarmalayıcıdan içteki PowerShell komutunu çıkarır."""
    if not command:
        return ""
    for pattern in (
        r"-Command\s+[\"'](?P<inner>.*)[\"']\s*$",
        r"-Command\s+[\"'](?P<inner>.*)[\"']",
        r"-Command\s+(?P<inner>.+)$",
    ):
        m = re.search(pattern, command, re.I | re.S)
        if m:
            return m.group("inner").replace('\\"', '"').strip()
    return command.strip()


def wants_elevation(command: str, output_text: str) -> bool:
    """Geriye dönük uyumluluk sürümü (metin tabanlı)."""
    if not command or not output_text:
        return False
    low_cmd = command.lower()
    settings_ok = (
        "set-date" in low_cmd
        or "set-timezone" in low_cmd
        or "set-datetime" in low_cmd
        or "net time" in low_cmd
        or ("timezone" in low_cmd and "set-" in low_cmd)
    )
    return settings_ok and _looks_like_failure(output_text)


def should_elevate(command: str, stdout: str = "", stderr: str = "", returncode: int = 0) -> bool:
    """
    Sistem saati/tarih/saat dilimi komutları için: komut hatalı biterse
    (returncode != 0 veya metinde hata/izin işareti) yetki yükseltmeyi önerir.
    PowerShell hataları çoğu zaman OEM kodlamasında (bozuk UTF-8) geldiği için
    asıl güvenilir sinyal returncode != 0 olarak kullanılır.
    """
    if not command:
        return False
    low_cmd = command.lower()
    settings_ok = (
        "set-date" in low_cmd
        or "set-timezone" in low_cmd
        or "set-datetime" in low_cmd
        or "net time" in low_cmd
        or ("timezone" in low_cmd and "set-" in low_cmd)
    )
    if not settings_ok:
        return False
    if returncode != 0:
        return True
    combined = (stdout or "") + " " + (stderr or "")
    return _looks_like_failure(combined)


def run_elevated_powershell(inner_command: str, timeout: int = 120) -> str:
    """
    İçteki PowerShell komutunu UAC ile yükseltilmiş (yönetici) pencerede çalıştırır.
    Kullanıcının UAC penceresini onaylaması gerekir. Sonucu metin olarak döndürür.
    """
    if not inner_command:
        return "Komut belirtilmedi."

    tmp_dir = tempfile.gettempdir()
    script_path = os.path.join(tmp_dir, f"jarvis_elev_{uuid.uuid4().hex[:8]}.ps1")
    out_path = os.path.join(tmp_dir, f"jarvis_elev_{uuid.uuid4().hex[:8]}.txt")

    script = (
        "$ErrorActionPreference = 'Stop'\r\n"
        f"$o = '{out_path}'\r\n"
        "try {\r\n"
        f"    $r = {inner_command}\r\n"
        "    '[OK] ' + (($r | Out-String).Trim()) | Out-File $o -Encoding utf8\r\n"
        "} catch {\r\n"
        "    ('[HATA] ' + $_.Exception.Message) | Out-File $o -Encoding utf8\r\n"
        "    exit 1\r\n"
        "}\r\n"
    )

    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)

        launcher = (
            "powershell -NoProfile -ExecutionPolicy Bypass -Command "
            "\"Start-Process powershell -Verb RunAs -Wait -ArgumentList "
            "'-NoProfile','-ExecutionPolicy','Bypass','-File','"
            + script_path
            + "'\""
        )

        proc = subprocess.run(
            launcher,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )

        if os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            return content or "Yönetici izniyle komut çalıştırıldı (çıktı yok)."

        low_err = (proc.stderr or "").lower() + (proc.stdout or "").lower()
        if "canceled" in low_err or "iptal" in low_err or proc.returncode != 0:
            return "Yetki yükseltme onaylanmadı veya başlatılamadı. (UAC penceresi reddedildi.)"
        return "Yönetici izniyle komut çalıştırıldı; çıktı alınamadı."
    except subprocess.TimeoutExpired:
        return "Yönetici komutu zaman aşımına uğradı."
    except Exception as e:
        return f"Yetki yükseltme hatası: {e}"
    finally:
        for path in (script_path, out_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


def shell_run(command: str, timeout: int = 30) -> str:
    if not command:
        return "Komut belirtilmedi."

    cmd_lower = command.lower().strip()

    for blocked in BLOCKED:
        if blocked in cmd_lower:
            return f"Güvenlik: Bu komut engellendi → {blocked}"

    for attempt, elevated in ((1, False), (2, True)):
        try:
            if elevated:
                inner = _extract_inner_pwsh(command)
                return run_elevated_powershell(inner, timeout=timeout)

            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            output = (result.stdout + result.stderr).strip()

            if should_elevate(command, result.stdout, result.stderr, result.returncode):
                continue  # ikinci denemede yönetici olarak çalıştır

            if not output:
                return "Komut başarıyla çalıştı (çıktı yok)."
            if len(output) > 800:
                output = output[:800] + "\n... (çıktı kısaltıldı)"

            return output
        except subprocess.TimeoutExpired:
            return f"Komut zaman aşımına uğradı ({timeout}s)."
        except Exception as e:
            if elevated:
                return f"Yönetici denemesi hatası: {e}"
            return f"Hata: {e}"

    return "Komut çalıştırılamadı."