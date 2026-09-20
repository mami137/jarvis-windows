#!/usr/bin/env python3
"""
JARVIS Windows — Gercek zamanli sesli yardimci cekirdegi
Alp Ünlü tarafından yapılmıştır — @alppunlu
Windows ortamina uyarlanmis calisma akisi
"""

import asyncio
import sys
from core.file_parser import parse_file_to_text
import datetime
import threading
import traceback
import os
import re
from pathlib import Path

import pyaudio  # type: ignore[reportMissingModuleSource]
from google import genai  # type: ignore[reportMissingImports]
from google.genai import types  # type: ignore[reportMissingImports]

from app_config import get_app_config_value
from ui import JarvisUI
from net_usage import add_sent, add_recv
from memory.memory_manager import load_memory, update_memory, delete_memory, format_memory_for_prompt
from actions.open_app import open_app
from actions.sys_info  import sys_info
from actions.calendar import get_calendar_events, add_calendar_event, delete_calendar_event
from actions.reminders import get_reminders, add_reminder
from actions.browser   import browser_control
from actions.shell     import shell_run
from actions.whatsapp  import send_whatsapp_message, save_whatsapp_contact
from actions.media     import play_media
from actions.weather   import get_weather_summary
from actions.screen_vision import analyze_screen
from actions.youtube_stats import get_youtube_channel_report
from wakeup_listener import WakeGestureListener

# -- Paths -------------------------------------------------------------------
BASE_DIR        = Path(__file__).resolve().parent
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"


CONTROL_TOKEN_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

# -- Model -------------------------------------------------------------------
LIVE_MODEL = "models/gemini-2.5-flash-native-audio-latest"

# -- Audio -------------------------------------------------------------------
FORMAT           = pyaudio.paInt16
CHANNELS         = 1
SEND_SAMPLE_RATE = 16000
RECV_SAMPLE_RATE = 24000
CHUNK_SIZE       = 1024
pya              = pyaudio.PyAudio()

# -- Tool tanımları ----------------------------------------------------------
TOOL_DECLARATIONS = [
    {
        "name": "wake_up_system",
        "description": "Kullanici 'Jarvis', 'Uyan', 'Burada misin', 'Geri don', 'Yardim et' gibi seni arka plandan (uyku modundan) cagiracak kelimeler soylediginde veya senle iletisime gectiginde ZORUNLU OLARAK bu araci calistir. Bu arac programin arayuzunu ekrana getirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "smart_click",
        "description": "Ekrandaki belirli bir dugmeye veya ogreye HIZLICA ve DOGRUDAN tiklar. Eger kullanici ekrandaki bir seye tiklamani istiyorsa (ornegin 'GO butonuna tikla', 'Baslat'a bas') GECIKMEYI ONLEMEK ICIN analyze_screen ve mouse_control araclarini ayri ayri cagirmak YERINE, sadece bu araci cagir. Bu arac ekran analizini ve tiklamayi kendi icinde tek bir hamlede milisaniyeler icinde yapar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "target": {"type": "STRING", "description": "Tiklanacak hedefin adi veya uzerindeki yazi. Orn: 'GO butonu', 'Kapat isareti', 'Arama kutusu'"}
            },
            "required": ["target"]
        }
    },
    {
        "name": "mouse_control",
        "description": "Bilgisayarin faresini kontrol eder. Ekranda herhangi bir noktaya tiklayabilir, fareyi hareket ettirebilir, ekrani kaydirir (scroll) veya surukleyebilir. ONEMLI: Bir web sayfasindaki butona tiklamak istiyorsan, once analyze_screen ile ekrani analiz edip butonun koordinatlarini bul, sonra bu araci kullanarak o koordinatlara tikla. Ornek akis: 1) analyze_screen ile ekrandaki dugmelerin konumlarini oku, 2) mouse_control ile o koordinata tikla.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "'click' (tikla), 'move' (tasi), 'scroll' (kaydir), 'drag' (surukle), 'position' (konum sor), 'screen_size' (ekran boyutu)"},
                "x": {"type": "INTEGER", "description": "X koordinati (ekranin sol kenari 0). click, move, drag icin gerekli."},
                "y": {"type": "INTEGER", "description": "Y koordinati (ekranin ust kenari 0). click, move, drag icin gerekli."},
                "end_x": {"type": "INTEGER", "description": "Surukle (drag) icin bitis X koordinati."},
                "end_y": {"type": "INTEGER", "description": "Surukle (drag) icin bitis Y koordinati."},
                "button": {"type": "STRING", "description": "Fare dugmesi: 'left' (sol), 'right' (sag), 'middle' (orta). Varsayilan: 'left'"},
                "clicks": {"type": "INTEGER", "description": "Kac kez tiklanacagi. Cift tik icin 2 ver. Varsayilan: 1"},
                "scroll_amount": {"type": "INTEGER", "description": "Kaydirma miktari. Pozitif yukari, negatif asagi. Orn: 3 veya -5"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "read_web_page",
        "description": "Belirtilen bir internet sitesinin HTML icerigini okur ve temizlenmis metnini getirir. Eger kullanici bir bilgi ariyorsa once search_duckduckgo ile arama yap, sonra ilginc linkleri bu aracla oku.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "Okunacak tam web adresi (URL)."}
            },
            "required": ["url"]
        }
    },
    {
        "name": "search_duckduckgo",
        "description": "Internet uzerinde DuckDuckGo kullanarak arama yapar ve cikan sonuclarin (URL'lerin) bir listesini dondurur. Bu cikan linkleri detayli okumak istersen, cikan url'yi read_web_page aracina verebilirsin.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Arama kelimesi veya cumlesi."}
            },
            "required": ["query"]
        }
    },
    {
        "name": "manage_file",
        "description": "Kullanicinin dosya sisteminde islem yapar. Klasor icerigini listeleme, dosya okuma, dosya tasima, kopyalama veya silme islemleri yapabilirsin.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "'list' (klasoru listele), 'read' (dosyayi oku), 'move' (tasi), 'copy' (kopyala), 'delete' (sil)"},
                "source": {"type": "STRING", "description": "Islem yapilacak dosya veya klasorun tam yolu (Orn: 'C:/Users/m7268/Desktop')."},
                "destination": {"type": "STRING", "description": "Tasinacak veya kopyalanacak ise hedef yol. Diger eylemlerde bos kalabilir."}
            },
            "required": ["action", "source"]
        }
    },
    {
        "name": "set_timer",
        "description": "Kullanicinin istedigi bir zamanda ona haber vermek icin hatirlatici / alarm / kronometre kurar. Belirtilen saniye kadar arka planda sayilir ve doldugunda hatirlatma mesajini Jarvis sesli olarak okur.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "seconds": {"type": "INTEGER", "description": "Kac saniye sonra hatirlatilacagi. Ornegin '10 dakika' icin 600 vermelisin."},
                "message": {"type": "STRING", "description": "Zaman doldugunda soylenecek mesaj. Orn: 'Efendim, cayiniz hazir, hemen alin'"}
            },
            "required": ["seconds", "message"]
        }
    },

    {
        "name": "simulate_typing",
        "description": "Bilgisayarda sanki bir insan klavyeden yaziyormus gibi belirli bir uygulamamın penceresine yazi yazar. ONEMLI: text parametresine yazilacak metni AYNEN gonder; Turkce karakterleri asla ASCIIye cevirme (ornegin kulub degil kulüp, genc degil genç). Uzun ve Turkce metinler otomatik olarak panoya kopyalanip yapistirilir (Ctrl+V), bu yuzden karakterler bozulmaz ve ozel tuslara ({ENTER}, {TAB} vb.) basar. Baska bir uygulamaya (orn. Not Defteri, Word, browser) yazi yazacaksan 'focus' parametresine hedef uygulamanin adini (orn. 'Notepad', 'Not Defteri', 'winword', 'chrome') yaz; o uygulama once one alinip odaklanir, SONRA yazi oraya yazilir. Bos birakilirsa su an aktif olan pencereye yazar. DIKKAT: Bir uygulamayi (open_app) actiktan hemen sonra yazi yazacaksaniz, araya 1-2 saniyelik bir gecikme eklemek icin bu aracin 'delay' parametresini kullanin ki uygulama tamamen acilmis ve imlec icine odaklanmis olsun.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "text": {
                    "type": "STRING",
                    "description": "Yazilacak metin veya basilacak tuslar (Orn: 'Merhaba Dunya~' (SendKeys'te ~ enter demektir ama {ENTER} de calisir))."
                },
                "delay": {
                    "type": "INTEGER",
                    "description": "Yazmaya baslamadan once beklenecek saniye (Orn: Uygulamanin acilmasini beklemek icin 2 veya 3 saniye). Varsayilan 0."
                },
                "focus": {
                    "type": "STRING",
                    "description": "Yazinin gitmesi gereken hedef uygulama adi (Orn: 'Notepad', 'winword', 'chrome', 'spotify'). Verilirse once o uygulamanin penceresi on plana alinir ve yazi oraya yazilir. Bos birakilirsa aktif pencere kullanilir."
                }
            },
            "required": ["text"]
        }
    },
    {
        "name": "execute_shell_command",
        "description": "Bilgisayarda PowerShell/CMD komutlari calistirir. Uygulama acma (start ...), dosya sistemi yonetimi, tarayicida sekme/arama acma ('start https://google.com/search?q=...') veya isletim sistemi ayarlarini degistirmek icin bu araci kullanin. Sistem saati/tarihini ayarlamak icin 'powershell -NoProfile -Command \"Set-Date -Date ...\"', saat dilimi icin 'powershell -NoProfile -Command \"Set-TimeZone -Id ...\"' kullanabilirsiniz. Windows (Powershell/CMD) komutlarina hakimseniz her turlu isi bu aracla yapabilirsiniz.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {
                    "type": "STRING",
                    "description": "Calistirilacak tam komut satiri (Powershell/CMD icin uygun formatta)."
                },
                "background": {
                    "type": "BOOLEAN",
                    "description": "Komut arka planda calistirilacak ve sonucun beklenmeyecegi durumlarda true yapin (Orn: tarayici acarken veya exe baslatirken). Dosya okuma veya komut ciktisi gereken durumlarda false yapin."
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "delegate_to_expert_model",
        "description": "Kullanici kapsamli bir kod yazimi, makale, uzun metin, karmasik matematik, derin arastirma veya analiz (mantik) gerektiren uzun soluklu bir gorev istediginde bu araci KESINLIKLE kullan. Gorev uzman modellere devredilir: kod/agentic sistem icin Claude Sonnet 5, matematik/algoritma icin DeepSeek R1, genis doku/arastirma icin Gemini 2.5 Flash, Turkce/talimat uyum icin Qwen 2.5 72B, uzun metin ozeti / buyuk veri analizi icin Nemotron 3 Ultra, genel / sohbet icin Llama 3.3 70B. task_category degerini buna gore sec ('code', 'research', 'math', 'general').",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task_description": {
                    "type": "STRING",
                    "description": "Kullanicinin istedigi gorevin detayli ve tam aciklamasi."
                },
                "task_category": {
                    "type": "STRING",
                    "description": "Gorevin kategorisi: 'code' (karmaşık kod/agentic/mantık -> Claude Sonnet 5), 'math' (matematik/algoritma -> DeepSeek R1), 'tr' (Türkçe/talimat/JSON -> Qwen 2.5 72B), 'summary' (uzun metin özeti/büyük veri/geniş analiz -> Nemotron 3 Ultra), 'research' (geniş doküman/veri araştırması -> Gemini 2.5 Flash), veya 'general'"
                }
            },
            "required": ["task_description", "task_category"]
        }
    },
    {
        "name": "open_app",
        "description": "Windows'ta herhangi bir uygulamayı açar. Spotify, Chrome, Terminal, Dosya Gezgini, VS Code vb.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Uygulama adı (örn. 'Spotify', 'Chrome', 'Terminal')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "sys_info",
        "description": "Sistem bilgisi alır: pil durumu, CPU, RAM, disk, saat, tarih, ağ bağlantısı.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "battery | cpu | ram | disk | time | date | network | all"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_weather",
        "description": (
            "Anlik hava durumunu ozetler. Varsayilan konum Istanbul'dur. "
            "Kullanici hava durumunu, sicakligi veya yagmur durumunu sordugunda kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "location": {
                    "type": "STRING",
                    "description": "Sehir veya konum. Bos birakilirsa Istanbul kullanilir."
                }
            }
        }
    },
    {
        "name": "get_calendar_events",
        "description": (
            "Takvim (Google Calendar) etkinliklerini okur. "
            "Bugun, yarin, siradaki etkinlik veya yaklasan ajandayi ozetler. "
            "Kullanici toplanti, takvim, ajanda, etkinlik veya gunluk programini sordugunda kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": (
                        "today | tomorrow | next | agenda | week veya dogal dilde "
                        "'onumuzdeki 30 gun', '2 hafta', 'bu ay', 'gelecek ay'"
                    )
                },
                "limit": {
                    "type": "NUMBER",
                    "description": "Maksimum etkinlik sayisi"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "add_calendar_event",
        "description": (
            "Takvim (Google Calendar) servisine yeni etkinlik ekler. "
            "Kullanici toplanti, randevu, takvime ekleme veya etkinlik olusturma isterse kullan. "
            "Baslangic tarihini gercek tarih/saat olarak ver; bitis verilmezse varsayilan sure kullanilir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Etkinlik basligi. Ornek: 'Disci Randevusu'"
                },
                "start_iso": {
                    "type": "STRING",
                    "description": "Baslangic tarih/saat. ISO veya yyyy-MM-dd HH:mm formatinda."
                },
                "end_iso": {
                    "type": "STRING",
                    "description": "Bitis tarih/saat. Opsiyonel."
                },
                "location": {
                    "type": "STRING",
                    "description": "Etkinlik konumu. Opsiyonel."
                },
                "notes": {
                    "type": "STRING",
                    "description": "Etkinlik notlari. Opsiyonel."
                },
                "calendar_name": {
                    "type": "STRING",
                    "description": "Eklenecek takvim adi. Opsiyonel."
                },
                "all_day": {
                    "type": "BOOLEAN",
                    "description": "true ise tum gun etkinligi olusturur."
                }
            },
            "required": ["title", "start_iso"]
        }
    },
    {
        "name": "delete_calendar_event",
        "description": (
            "Takvim (Google Calendar) servisinden etkinlik siler. "
            "Kullanici bir toplantiyi, randevuyu veya takvim kaydini silmek istediginde kullan. "
            "Ayni ada birden fazla etkinlik varsa dogru kaydi bulmak icin baslangic tarihini gercek tarih/saat olarak ver."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Silinecek etkinlik basligi. Ornek: 'Disci Randevusu'"
                },
                "start_iso": {
                    "type": "STRING",
                    "description": "Opsiyonel tarih/saat. Ayni isimli birden fazla etkinligi ayirt etmek icin kullan."
                },
                "calendar_name": {
                    "type": "STRING",
                    "description": "Opsiyonel takvim adi"
                },
                "delete_all_matches": {
                    "type": "BOOLEAN",
                    "description": "true ise eslesen tum etkinlikleri siler"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "get_reminders",
        "description": (
            "Hatırlatıcılar (Microsoft To-Do) listesini okur. "
            "Bugunku, yaklasan, geciken veya tum acik animsaticilari ozetler. "
            "Kullanici hatirlatma, animsatici, reminder veya yapilacaklar listesini sordugunda kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "today | upcoming | overdue | all | next"
                },
                "limit": {
                    "type": "NUMBER",
                    "description": "Maksimum animsatici sayisi"
                },
                "list_name": {
                    "type": "STRING",
                    "description": "Istenirse belirli bir animsatici listesi adi"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "add_reminder",
        "description": (
            "Hatırlatıcılar (Microsoft To-Do) uygulamasina yeni bir animsatici ekler. "
            "Kullanici 'hatirlat', 'animsatici ekle', 'reminder kur' dediginde kullan. "
            "Goreli zaman ifadelerini bugunku tarih baglamina gore due_iso alanina ISO formatinda cevir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Animsatici basligi"
                },
                "due_iso": {
                    "type": "STRING",
                    "description": "Opsiyonel tarih/saat. Ornek: 2026-04-13T09:00 veya tum gun icin 2026-04-13"
                },
                "notes": {
                    "type": "STRING",
                    "description": "Opsiyonel not"
                },
                "list_name": {
                    "type": "STRING",
                    "description": "Opsiyonel animsatici listesi"
                },
                "priority": {
                    "type": "STRING",
                    "description": "low | medium | high"
                },
                "all_day": {
                    "type": "BOOLEAN",
                    "description": "Tum gun animsatici ise true"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "browser_control",
        "description": "Tarayıcıda URL açar, Google'da arama yapar veya YouTube'da ilk sonucu doğrudan oynatır.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "open_url | search | play_youtube"},
                "url":    {"type": "STRING", "description": "Açılacak URL (open_url için)"},
                "query":  {"type": "STRING", "description": "Arama sorgusu (search veya play_youtube için)"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "shell_run",
        "description": "Windows komut satırı komutu çalıştırır. Dosya işlemleri, sistem yönetimi.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {
                    "type": "STRING",
                    "description": "Çalıştırılacak komut"
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "play_media",
        "description": (
            "YouTube, Spotify veya Spotify/YouTube'da şarkı, müzik veya video açar. "
            "Kullanıcı belirli bir platform söylerse onu kullan. "
            "Belirtmezse uygun olanı dene. "
            "Kullanıcı 'çal', 'oynat', 'aç' diyorsa autoplay=true kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Şarkı, sanatçı, albüm veya video arama ifadesi"
                },
                "provider": {
                    "type": "STRING",
                    "description": "auto | youtube | spotify | apple_music"
                },
                "autoplay": {
                    "type": "BOOLEAN",
                    "description": "true ise mümkünse doğrudan oynatır"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_youtube_channel_report",
        "description": (
            "YouTube kanalinin public istatistiklerini ve son videolarin performansini raporlar. "
            "Kullanici kanal istatistiklerini, abone sayisini, son videolarini, buyume hizini "
            "veya YouTube analizini sordugunda kullan. Bu arac Studio yerine public YouTube Data API verisini kullanir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": (
                        "Dogal dilde analiz istegi. Ornek: "
                        "'YouTube istatistiklerim nasil', 'son videolarimi analiz et', "
                        "'kanal buyumemi ozetle'"
                    )
                },
                "handle": {
                    "type": "STRING",
                    "description": (
                        "Opsiyonel kanal handle'i, kanal linki veya kanal ID'si. "
                        "Bos birakilirsa ayarlardaki youtube_channel_handle kullanilir."
                    )
                },
                "video_limit": {
                    "type": "NUMBER",
                    "description": "Analize dahil edilecek son video sayisi. Varsayilan 6."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "analyze_screen",
        "description": (
            "Aktif pencerenin ekran goruntusunu alip Gemini vision ile analiz eder. "
            "Kullanici ekranda ne oldugunu, bir hatayi, gorunen metni, butonlari veya pencere icerigini sordugunda kullan. "
            "Bu surum yalnizca aktif pencereyi destekler."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Kullanicinin ekranla ilgili sorusu. Ornek: 'Bu hatayi oku', 'Ekranda ne var?'"
                },
                "target": {
                    "type": "STRING",
                    "description": "Su an sadece active_window desteklenir."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "save_memory",
        "description": "Kullanıcı hakkında önemli bilgiyi kalıcı belleğe kaydeder. İsim, tercihler, projeler vb. duyunca sessizce çağır.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": "identity | preferences | projects | notes"
                },
                "key":   {"type": "STRING", "description": "Kısa anahtar (örn. 'name')"},
                "value": {"type": "STRING", "description": "Değer (İngilizce)"}
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "delete_memory",
        "description": (
            "Kalici hafizadaki bir kaydi siler. "
            "Kullanici 'bunu hafizandan kaldir', 'unut', 'sil' gibi bir sey derse kullan. "
            "Mumkunse category ve key ile sil; emin degilsen match_text ile ilgili kaydi bulup kaldir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": "Kaydin kategorisi. Ornek: notes | identity | preferences | projects"
                },
                "key": {
                    "type": "STRING",
                    "description": "Silinecek anahtar. Ornek: claude_limit_refresh"
                },
                "match_text": {
                    "type": "STRING",
                    "description": "Kaydi bulmak icin kullanilacak dogal dil parcasi. Ornek: 'claude ai limit yenilenmesi'"
                }
            }
        }
    },
    {
        "name": "send_whatsapp_message",
        "description": (
            "WhatsApp Desktop veya WhatsApp Web üzerinden mesaj taslağı açar veya mesajı gönderir. "
            "Kişi adı veya telefon numarasıyla çalışabilir. "
            "Telefon numarası verilmemişse kişi adını önce kayıtlı WhatsApp kişileri ve içe aktarılan telefon rehberinde ara. "
            "Kullanıcı 'gönder', 'yolla', 'ile', 'hemen gönder' gibi açık bir gönderme niyeti söylüyorsa "
            "ekstra onay istemeden send_now=true kullan. "
            "Yalnızca 'hazırla', 'taslak aç', 'yaz ama gönderme' diyorsa send_now=false kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "recipient_name": {
                    "type": "STRING",
                    "description": "Kişi adı. Örn: 'Anne', 'Ahmet', 'Ece'"
                },
                "phone_number": {
                    "type": "STRING",
                    "description": "Uluslararası telefon numarası. Örn: +905551112233"
                },
                "message": {
                    "type": "STRING",
                    "description": "Gönderilecek mesaj içeriği"
                },
                "app_target": {
                    "type": "STRING",
                    "description": "desktop | web | auto. Varsayılan auto, tercihen desktop."
                },
                "send_now": {
                    "type": "BOOLEAN",
                    "description": "true ise sohbet açıldıktan sonra mesajı otomatik gönderir"
                }
            },
            "required": ["message"]
        }
    },
    {
        "name": "save_whatsapp_contact",
        "description": (
            "Sık kullanılan bir WhatsApp kişisini adı ve telefon numarasıyla kalıcı belleğe kaydeder. "
            "Kullanıcı bir kişiyi 'annem', 'Ahmet', 'iş ortağım' gibi tekrar kullanılacak şekilde tanımladığında kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "display_name": {
                    "type": "STRING",
                    "description": "Kaydedilecek kişi adı. Örn: 'Annem', 'Ahmet'"
                },
                "phone_number": {
                    "type": "STRING",
                    "description": "Uluslararası telefon numarası. Örn: +905551112233"
                },
                "aliases": {
                    "type": "STRING",
                    "description": "Virgülle ayrılmış alternatif hitaplar. Örn: 'anne, annem, mom'"
                }
            },
            "required": ["display_name", "phone_number"]
        }
    }
]


def get_api_key() -> str:
    return str(get_app_config_value("gemini_api_key", "") or "")


def load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "Sen JARVIS'sin — Windows'ta çalışan kişisel AI asistanı. "
            "Kullanıcının dilini algıla ve aynı dille cevap ver. "
            "Kısa ve net yanıtlar ver. "
            "Araçları kullanarak görevleri tamamla, asla taklit etme."
        )


class JarvisLive:
    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._mini_menu     = None  # Mini menü referansı (sonra bağlanır)

        self.ui.on_text_command  = self._on_text_command
        self.ui.on_pause_toggle  = self._on_pause_toggle
        self.ui.on_voice_change  = self._on_voice_change
        self.ui.on_effects_state_change = self._on_effects_state_change
        self.ui.on_send_media    = self._on_send_media
        self._paused             = False
        self._reconnect_requested = False  # Ses değişimi gibi planlı yeniden bağlanmalar için

    def _on_pause_toggle(self, paused: bool):
        self._paused = paused

    def _on_send_media(self, media: dict):
        """UI'dan medya (webcam karesi) gelir — out_queue'ye ekle."""
        try:
            loop = self.loop
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.out_queue.put(media), loop
                )
        except Exception as e:
            err_s = str(e).encode('ascii','replace').decode('ascii')
            sys.stdout.write(f"[JARVIS] Media gonderilemedi: {err_s}\n")

    def _on_voice_change(self, voice: str):
        # Ses config'e ui tarafında kaydedildi; Gemini Live'da ses yalnızca
        # bağlantı kurulurken okunduğu için yeni sesin duyulması için
        # oturumu kapatıp yeniden bağlanmak gerekir.
        self.ui.write_log(f"SYS: Ses '{voice}' olarak ayarlandı. Yeni ses için yeniden bağlanılıyor...")
        try:
            if self._loop and self.session:
                self._reconnect_requested = True
                asyncio.run_coroutine_threadsafe(self.session.close(), self._loop)
            else:
                self.ui.write_log("SYS: Bağlantı kurulunca yeni ses aktif olacak.")
        except Exception as e:
            err_s = str(e).encode('ascii','replace').decode('ascii')
            sys.stdout.write(f"[JARVIS] ! Ses degisiminde yeniden baglanma istegi basarisiz: {err_s}\n")

    def _on_effects_state_change(self, enabled: bool):
        pass

    def _focus_ui_section_for_tool(self, tool_name: str, args: dict):
        if tool_name == "sys_info":
            query = str(args.get("query", "")).strip().lower()
            if query in {"time", "saat", "zaman", "date", "tarih"}:
                self.ui.focus_panel("time", duration_ms=5200)
            else:
                self.ui.focus_panel("system", duration_ms=5200)
        elif tool_name == "get_weather":
            self.ui.focus_panel("weather", duration_ms=5600)

    def _on_text_command(self, text: str):
        if self._paused:
            return
        
        # Ekli dosyalar varsa onlari metin olarak parse edip prompta ekle
        attached_content = ""
        if hasattr(self.ui, 'attached_files') and self.ui.attached_files:
            for filepath in self.ui.attached_files:
                parsed_text = parse_file_to_text(filepath)
                filename = os.path.basename(filepath)
                
                # Eger metin cok uzunsa (WebSocket limitine takilmamasi icin) araci kullanmasini soyle:
                if len(parsed_text) > 2000:
                    import tempfile
                    temp_dir = os.path.join(os.getcwd(), "temp_uploads")
                    os.makedirs(temp_dir, exist_ok=True)
                    safe_name = f"parsed_{filename}.txt"
                    temp_path = os.path.join(temp_dir, safe_name)
                    
                    with open(temp_path, "w", encoding="utf-8") as f:
                        f.write(parsed_text)
                        
                    attached_content += (
                        f"\n\n[EKLENEN DOSYA: {filename}]\n"
                        f"(Dosya cok buyuk oldugu icin buraya sigmadi. Sen bunu analiz etmek icin "
                        f"manage_file aracini kullanarak su dosya yolunu okumalisin: {temp_path})\n"
                    )
                else:
                    attached_content += f"\n\n[EKLENEN DOSYA: {filename}]\n{parsed_text}\n"
                    
            self.ui.attached_files.clear()
            self.ui.write_log("SYS: Dosyalar okundu (uzunlarsa bellege alindi) ve hazirlandi.")
            
        final_text = text + attached_content
        
        self.ui.write_log(f"Siz: {text}")
        self.ui._save_user_message(text)
        if not self._loop or not self.session:
            self.ui.write_log("ERR: JARVIS baglantisi henuz hazir degil.")
            return
            
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": final_text}]},
                turn_complete=True
            ),
            self._loop
        )

    async def _interrupt_audio(self):
        try:
            if self.audio_in_queue:
                while not self.audio_in_queue.empty():
                    try:
                        self.audio_in_queue.get_nowait()
                    except Exception:
                        break
            if self.session:
                await self.session.send_realtime_input(audio_stream_end=True)
            self.set_speaking(False)
        except Exception:
            pass


    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        else:
            self.ui.set_state("LISTENING")

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.ui.write_debug(f"{tool_name}: {short}", level="ERROR")
        self.ui.set_state("ERROR")

    @staticmethod
    def _result_looks_like_error(result) -> bool:
        text = str(result or "").strip().lower()
        if not text:
            return False
        error_markers = (
            "hata",
            "error",
            "alinamadi",
            "alınamadı",
            "bulunamadi",
            "bulunamadı",
            "acilamadi",
            "açılamadı",
            "tamamlanamadi",
            "tamamlanamadı",
            "gecersiz",
            "geçersiz",
            "izin gerekiyor",
            "izin gerekli",
            "baglanti",
            "bağlantı",
            "gerekli.",
        )
        return any(marker in text for marker in error_markers)

    @staticmethod
    def _should_play_success_sfx(tool_name: str, args: dict, result) -> bool:
        action_tools = {
            "open_app",
            "add_calendar_event",
            "add_reminder",
            "delete_calendar_event",
            "remove_calendar_event",
        }
        if tool_name in action_tools:
            return True

        if tool_name == "send_whatsapp_message":
            text = str(result or "").lower()
            if bool(args.get("send_now", False)):
                return "gönderildi" in text or "gonderildi" in text
            return False

        return False

    @staticmethod
    def _clean_transcript_text(text: str) -> tuple[str, bool]:
        raw = str(text or "")
        had_noise = False
        if CONTROL_TOKEN_RE.search(raw):
            had_noise = True
            raw = CONTROL_TOKEN_RE.sub(" ", raw)
        cleaned = []
        for ch in raw:
            if ch in "\n\r\t" or ord(ch) >= 32:
                cleaned.append(ch)
            else:
                had_noise = True
        normalized = " ".join("".join(cleaned).split())
        return normalized.strip(), had_noise

    def _build_config(self) -> types.LiveConnectConfig:
        memory  = load_memory()
        mem_str = format_memory_for_prompt(memory)
        sys_p   = load_system_prompt()
        now     = datetime.datetime.now()
        time_ctx = f"[ŞU ANKİ ZAMAN]\n{now.strftime('%A, %d %B %Y — %H:%M')}\n\n"

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str + "\n\n")
        # Dil kuralı prompt'un BAŞINDA olmalı — güçlülük sırası önemli
        parts.append(
            "[CRITICAL LANGUAGE RULE — OVERRIDE ALL OTHER INSTRUCTIONS]\n"
            "RESPOND IN THE SAME LANGUAGE THE USER SPEAKS. "
            "If the user speaks English -> respond in English. "
            "If the user speaks Turkish -> respond in Turkish. "
            "NEVER force a language. Detect and match automatically.\n\n"
        )
        parts.append(sys_p)

        return types.LiveConnectConfig(
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="wake_up_system",
                    description="SADECE sistem arka planda (tray/uyku modunda) ise bu aracı çalıştır. Kullanıcı 'Jarvis', 'Uyan' gibi kelimeler söylediğinde, eğer ana menü zaten açıksa bu aracı ÇALIŞTIRMA — sadece normalce cevap ver. Bu araç yalnızca ekran görünmuyorken arayüzü geri getirir.",
                )
            ]
        ),
    ],
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=str(get_app_config_value("voice", "Charon") or "Charon")
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})
        print(f"[JARVIS] TOOL {name} {args}")
        self.ui.set_state("THINKING")

        loop   = asyncio.get_event_loop()
        result = "Tamam."
        had_exception = False

        try:
            if name == "wake_up_system":
                print("[JARVIS] YZ tarafindan uyanma tetiklendi!")
                # Ana menü zaten açıksa mini menüyü açma
                root = self.ui.root
                if root.winfo_viewable() and not root.winfo_ismapped():
                    result = "Ana menü zaten açık. Mini menü açmaya gerek yok."
                elif root.winfo_ismapped():
                    # Ana menü görünür — mini menü açma
                    result = "Ana menü zaten açık, kullanıcı zaten burada."
                else:
                    # Tray modunda — mini menü aç
                    if hasattr(self.ui, 'trigger_mini_menu') and self.ui.trigger_mini_menu:
                        self.ui.root.after(0, self.ui.trigger_mini_menu)
                    result = "Sistem basariyla uyandirildi ve mini menu ekrana geldi. Kullaniciya neseli bir sekilde kisa bir 'Buradayim' de."
            elif name == "delegate_to_expert_model":
                from core.auto_router import stream_expert_task, determine_best_model
                self.ui.write_log(f"SYS: Uzman Modele Baglaniliyor...")
                tdesc = args.get("task_description", "")
                tcat = args.get("task_category", "general")
                
                # Akışlı (streaming) uzman görev: executor thread'de OpenRouter SSE
                # tüketilirken her kısmi parça anında UI'ya (ekrana) yansıtılır.
                expert_model = determine_best_model(tdesc, tcat)
                self.ui.begin_expert_stream(expert_model)

                def _run_expert_stream():
                    collected = []
                    actual_model = expert_model
                    try:
                        for event in stream_expert_task(tdesc, tcat):
                            etype = event.get("type")
                            if etype == "delta":
                                piece = event.get("text", "")
                                if piece:
                                    collected.append(piece)
                                    self.ui.stream_expert_chunk(piece)
                            elif etype == "done":
                                if event.get("model"):
                                    actual_model = event["model"]
                            elif etype == "error":
                                return {"error": True, "message": event.get("message", "Bilinmeyen hata")}
                    except Exception as e:
                        return {"error": True, "message": f"Hata oluştu: {str(e)}"}
                    finally:
                        # Akış başlasa da bittiğinde UI'yi her durumda kapat
                        self.ui.end_expert_stream()
                    return {"error": False, "model": actual_model, "result": "".join(collected)}

                res = await loop.run_in_executor(None, _run_expert_stream)
                
                if res.get("error"):
                    result = res["message"]
                    self.ui.write_log(f"ERR: Uzman Model Hatası: {result}")
                else:
                    result = f"Uzman Model ({res['model']}) sonucu:\n\n{res['result']}"
                    self.ui.write_log(f"SYS: Görev başarıyla devredildi (Model: {res['model']})")
                    # İşlem bittiğinde sonucu (kısa özet halinde) kalıcı hafızaya kaydet
                    try:
                        saved_text = res["result"][:1500]
                        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                        note_key = f"expert_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
                        update_memory({"notes": {note_key: {"value": f"[{stamp}] {res['model']}:\n{saved_text}"}}})
                    except Exception:
                        pass
                    



            elif name == "smart_click":
                from actions.smart_click import smart_click
                target = args.get("target", "")
                r = await loop.run_in_executor(None, lambda: smart_click(target))
                result = r

            elif name == "mouse_control":
                from actions.mouse_control import mouse_click, mouse_move, mouse_scroll, mouse_drag, get_mouse_position, get_screen_size
                action = args.get("action", "")
                if action == "click":
                    r = await loop.run_in_executor(None, lambda: mouse_click(
                        args.get("x", 0), args.get("y", 0),
                        args.get("button", "left"), args.get("clicks", 1)))
                elif action == "move":
                    r = await loop.run_in_executor(None, lambda: mouse_move(args.get("x", 0), args.get("y", 0)))
                elif action == "scroll":
                    r = await loop.run_in_executor(None, lambda: mouse_scroll(
                        args.get("scroll_amount", 0), args.get("x"), args.get("y")))
                elif action == "drag":
                    r = await loop.run_in_executor(None, lambda: mouse_drag(
                        args.get("x", 0), args.get("y", 0),
                        args.get("end_x", 0), args.get("end_y", 0)))
                elif action == "position":
                    r = get_mouse_position()
                elif action == "screen_size":
                    r = get_screen_size()
                else:
                    r = f"Bilinmeyen fare eylemi: {action}"
                result = r

            elif name == "read_web_page":
                from actions.web_reader import read_web_page
                r = await loop.run_in_executor(None, lambda: read_web_page(args.get("url", "")))
                result = r
                
            elif name == "search_duckduckgo":
                from actions.web_reader import search_duckduckgo
                r = await loop.run_in_executor(None, lambda: search_duckduckgo(args.get("query", "")))
                result = r
                
            elif name == "manage_file":
                from actions.file_manager import manage_file, list_directory, read_file_content
                action = args.get("action", "")
                src = args.get("source", "")
                dst = args.get("destination", "")
                if action == "list":
                    r = await loop.run_in_executor(None, lambda: list_directory(src))
                elif action == "read":
                    r = await loop.run_in_executor(None, lambda: read_file_content(src))
                else:
                    r = await loop.run_in_executor(None, lambda: manage_file(action, src, dst))
                result = r
                
            elif name == "set_timer":
                from core.scheduler import add_timer
                secs = args.get("seconds", 0)
                msg = args.get("message", "")
                r = add_timer(secs, msg)
                result = r

            elif name == "save_memory":
                cat = args.get("category", "notes")
                key = args.get("key", "")
                val = args.get("value", "")
                if key and val:
                    update_memory({cat: {key: {"value": val}}})
                    print(f"[Memory] MEM {cat}/{key} = {val}")
                result = "ok"

            elif name == "delete_memory":
                result = delete_memory(
                    args.get("category", ""),
                    args.get("key", ""),
                    args.get("match_text", ""),
                )

            elif name == "execute_shell_command":
                cmd_str = args.get("command", "")
                is_bg = args.get("background", False)
                self.ui.write_log(f"SYS: Komut calistiriliyor: {cmd_str}")
                
                try:
                    import subprocess
                    if is_bg:
                        subprocess.Popen(cmd_str, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        result = f"Arka planda komut baslatildi: {cmd_str}"
                    else:
                        proc = await asyncio.create_subprocess_shell(
                            cmd_str,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        stdout, stderr = await proc.communicate()
                        out_str = stdout.decode('utf-8', errors='replace').strip()
                        err_str = stderr.decode('utf-8', errors='replace').strip()
                        
                        result = out_str if out_str else (err_str if err_str else "Komut basariyla calisti ama cikti vermedi.")

                        # Saat/tarih türü komutlar yönetici izni gerektirirse otomatik UAC ile tekrar dene
                        if not is_bg:
                            from actions.shell import should_elevate, run_elevated_powershell, _extract_inner_pwsh
                            if should_elevate(cmd_str, out_str, err_str, proc.returncode):
                                self.ui.write_log("SYS: Yonetici izni gerekiyor — UAC penceresini onaylayin...")
                                inner = _extract_inner_pwsh(cmd_str)
                                elevated = await asyncio.to_thread(run_elevated_powershell, inner)
                                result = f"Yonetici izniyle calistirildi:\n{elevated}"
                except Exception as e:
                    result = f"Komut calistirma hatasi: {str(e)}"
            elif name == "simulate_typing":
                text_to_type = args.get("text", "")
                delay_sec = args.get("delay", 0)
                focus_app = str(args.get("focus", "") or "").strip()
                
                # SendKeys uyumlu CTRL/ALT/SHIFT tokenlarini cevir:
                #  {CTRL}  -> ^   (Orn: {CTRL}a => ^a = Ctrl+A)
                #  {ALT}   -> %   {SHIFT} -> +   {ESC} -> {ESC} (SendKeys'te gecerli)
                from actions.open_app import APP_ALIASES
                sendkeys_text = re.sub(r"\{CTRL\}", "^", text_to_type, flags=re.IGNORECASE)
                sendkeys_text = re.sub(r"\{ALT\}", "%", sendkeys_text, flags=re.IGNORECASE)
                sendkeys_text = re.sub(r"\{SHIFT\}", "+", sendkeys_text, flags=re.IGNORECASE)
                
                # PowerShell tek tirnak hatasi olmamasi icin
                safe_text = sendkeys_text.replace("'", "''")
                safe_focus = focus_app.replace("'", "''")
                
                # focus => islem adina cevir (APP_ALIASES yardimiyla)
                #  "Not Defteri" -> notepad, "notpad"->notepad gibi
                focus_key = focus_app.lower().strip()
                if focus_key.endswith(" defteri") or focus_key.endswith(" notepad"):
                    focus_name = "notepad"
                else:
                    focus_name = APP_ALIASES.get(focus_key, focus_app)
                safe_focus_name = focus_name.replace("'", "''")
                
                # Hedef pencere varsa once onu one al (izin: baslik + islem adi + PID ile)
                focus_ps = ""
                if focus_app:
                    focus_ps = f"""
                try {{
                    $proc = Get-Process | Where-Object {{
                        $_.MainWindowHandle -ne 0 -and (
                            $_.ProcessName -ilike '*{safe_focus_name}*' -or
                            $_.ProcessName -ilike '*{safe_focus}*' -or
                            $_.MainWindowTitle -like '*{safe_focus}*'
                        )
                    }} | Select-Object -First 1
                    if ($proc -ne $null) {{
                        $activated = $wshell.AppActivate([int]$proc.Id)
                        if ($activated) {{
                            Start-Sleep -Milliseconds 800
                        }} else {{
                            Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class W32 {{
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}}
'@
                            [W32]::ShowWindow($proc.MainWindowHandle, 9) | Out-Null
                            [W32]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
                            Start-Sleep -Milliseconds 800
                        }}
                    }} else {{
                        $wshell.AppActivate('{safe_focus}') | Out-Null
                        Start-Sleep -Milliseconds 800
                    }}
                }} catch {{}}
                """
                
                # -- Metni yazma stratejisini sec ------------------------------
                # WScript SendKeys tek cagrida ~255 karakter sinirlidir ve Turkce
                # karakterleri (ı ğ ş ç ö ü) guvenilir basamaz. Kisa + saf-ASCII
                # yazilar icin SendKeys, uzun/Turkce metinler icin PANO (Ctrl+V)
                # yontemi kullanilir.
                need_unicode = any(ord(ch) > 127 for ch in text_to_type)
                long_text = len(text_to_type) > 80

                # Sadece özel tuslardan mibarek (Orn: {CTRL}n, {ENTER}) -> SendKeys.
                # Dipte gercek karakter içeriyorsa pano yontemi daha guvenli.
                pure_keys = bool(re.fullmatch(
                    r"(?:\{(?:CTRL|ALT|SHIFT|DELETE|ESC|TAB|BACKSPACE|BS|SPACE|ENTER)\}[a-zA-Z]?)*",
                    text_to_type, re.IGNORECASE))

                # En basindaki "temiz sayfa / yeni sayfa" emirlerini ayir
                ctrl_prefix = ""          # SendKeys olarak basilacak on tuslar
                body = text_to_type
                m_clear = re.match(r"(?i)\{CTRL\}a\{DELETE\}", body)
                m_new = re.match(r"(?i)\{CTRL\}n", body)
                if m_clear:
                    ctrl_prefix = "^a{DELETE}"
                    body = body[len(m_clear.group(0)):]
                elif m_new:
                    ctrl_prefix = "^n"
                    body = body[len(m_new.group(0)):]

                # Geri kalan metindeki Enter/Tab token'larini gercek satir/tab'a cevir
                converted_body = body.replace("{ENTER}", "\n").replace("{TAB}", "\t")

                use_clipboard = (body != "") and (need_unicode or long_text)

                final_script = ""
                if use_clipboard:
                    # ---------- PANO YONTEMI (Türkçe/uzun metin) ----------
                    import tempfile
                    # Kodlama kaybini onlemek icin metni UTF-8 olarak diske yaz,
                    # PS'te get-content -Raw -Encoding UTF8 ile okuyup panoya koy.
                    tmp_path = os.path.join(
                        tempfile.gettempdir(),
                        f"jarvis_paste_{datetime.datetime.now().strftime('%H%M%S%f')}.txt",
                    )
                    with open(tmp_path, "w", encoding="utf-8") as fh:
                        fh.write(converted_body)
                    safe_tmp = tmp_path.replace("'", "''")

                    # Not: Ctrl+V ('^v') ile yapistirirken asla 255-sinir yok,
                    # ve Unicode karakterler aynen korunur.
                    final_script = f"""
                    $wshell = New-Object -ComObject wscript.shell
                    {focus_ps}
                    if ('{ctrl_prefix}' -ne '') {{ $wshell.SendKeys('{ctrl_prefix}') }}
                    Start-Sleep -Milliseconds 400
                    $content = Get-Content -LiteralPath '{safe_tmp}' -Raw -Encoding UTF8
                    Set-Clipboard -Value $content
                    Start-Sleep -Milliseconds 300
                    $wshell.SendKeys('^v')
                    Start-Sleep -Milliseconds 200
                    Remove-Item -LiteralPath '{safe_tmp}' -Force -ErrorAction SilentlyContinue
                    """
                elif pure_keys or body == "":
                    # ---------- SAF TUŞ / KISA YAZI YÖNTEMİ ----------
                    # SendKeys'e uygun hale getirilmiş (CTRL/ALT/SHIFT -> ^ % +)
                    remainder = (body.replace("{ENTER}", "~")
                                      .replace("{TAB}", "{TAB}"))
                    remainder = re.sub(r"\{CTRL\}", "^", remainder, flags=re.IGNORECASE)
                    remainder = re.sub(r"\{ALT\}", "%", remainder, flags=re.IGNORECASE)
                    remainder = re.sub(r"\{SHIFT\}", "+", remainder, flags=re.IGNORECASE)
                    safe_remainder = (ctrl_prefix + remainder).replace("'", "''")
                    final_script = f"""
                    $wshell = New-Object -ComObject wscript.shell
                    {focus_ps}
                    if ({delay_sec} -gt 0) {{ Start-Sleep -Seconds {delay_sec} }}
                    $wshell.SendKeys('{safe_remainder}')
                    """
                else:
                    # Kısa/ASCII metin: yine SendKeys (fakat uzunluk sirnesine dikkat)
                    safe_body_ascii = (ctrl_prefix + body).replace("'", "''")
                    final_script = f"""
                    $wshell = New-Object -ComObject wscript.shell
                    {focus_ps}
                    if ({delay_sec} -gt 0) {{ Start-Sleep -Seconds {delay_sec} }}
                    $wshell.SendKeys('{safe_body_ascii}')
                    """

                preview = re.sub(r"\{[A-Za-z]+\}", "", text_to_type)
                preview = preview[:60] + ("..." if len(preview) > 60 else "")
                method = "pano (Ctrl+V)" if use_clipboard else "SendKeys"
                self.ui.write_log(f"SYS: Klavyeden yaziyor ({method}, hedef: {focus_app or 'aktif pencere'}): {preview}")

                try:
                    import subprocess
                    # Arka planda Powershell'i tamamen sessizce cagiriyoruz. CREATE_NO_WINDOW (0x08000000)
                    subprocess.Popen(["powershell", "-NoProfile", "-Command", final_script], shell=False, creationflags=0x08000000)
                    focus_note = f" ('{focus_app}' penceresine)" if focus_app else ""
                    result = f"Klavyeden yazma islemi basariyla baslatildi{focus_note} ({method})."
                except Exception as e:
                    result = f"Klavye simule etme hatasi: {e}"
            elif name == "open_app":
                r = await loop.run_in_executor(
                    None, lambda: open_app(args.get("app_name", "")))
                result = r or f"{args.get('app_name')} açıldı."

            elif name == "sys_info":
                self._focus_ui_section_for_tool(name, args)
                r = await loop.run_in_executor(
                    None, lambda: sys_info(args.get("query", "all")))
                result = r or "Bilgi alındı."

            elif name == "get_weather":
                self._focus_ui_section_for_tool(name, args)
                location = args.get("location") or None
                r = await loop.run_in_executor(
                    None, lambda: get_weather_summary(location))
                result = r or "Hava durumu bilgisi alindi."
                # Kullanıcı belirli bir konum verdiyse, onu varsayılan yap
                if location:
                    try:
                        from app_config import save_app_config
                        save_app_config({"weather_location": location.strip()})
                    except Exception:
                        pass
                # Hava durumu kartını güncelle ve UI'yi yenile
                def _refresh_weather_bg():
                    try:
                        from actions.weather import get_weather_summary as _ws
                        from app_config import get_app_config_value
                        w = _ws(location)
                        parsed = self.ui._parse_weather_card(w)
                        # Şehir adını karışıklık olmaması için açıkça belirle
                        if location:
                            parsed["city"] = location.strip().title()
                        elif not parsed.get("city") or parsed.get("city") == "Istanbul":
                            cfg_loc = str(get_app_config_value("weather_location", "") or "").strip()
                            if cfg_loc:
                                parsed["city"] = cfg_loc.title()
                        self.ui._weather_card = parsed
                        # Kartı zorla yenile
                        self.ui.root.after(0, self.ui._kick_brief_refresh, True)
                    except Exception:
                        pass
                threading.Thread(target=_refresh_weather_bg, daemon=True).start()

            elif name == "get_calendar_events":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_calendar_events(
                        args.get("query", "today"),
                        int(args.get("limit", 6) or 6),
                    ),
                )
                result = r or "Takvim bilgisi alindi."

            elif name == "add_calendar_event":
                r = await loop.run_in_executor(
                    None,
                    lambda: add_calendar_event(
                        args.get("title", ""),
                        args.get("start_iso", ""),
                        args.get("end_iso", ""),
                        args.get("notes", ""),
                        args.get("location", ""),
                        args.get("calendar_name", ""),
                        bool(args.get("all_day", False)),
                    ),
                )
                result = r or "Takvim etkinligi eklendi."

            elif name == "delete_calendar_event":
                r = await loop.run_in_executor(
                    None,
                    lambda: delete_calendar_event(
                        args.get("title", ""),
                        args.get("start_iso", ""),
                        args.get("calendar_name", ""),
                        bool(args.get("delete_all_matches", False)),
                    ),
                )
                result = r or "Takvim etkinligi silindi."

            elif name == "get_reminders":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_reminders(
                        args.get("query", "upcoming"),
                        int(args.get("limit", 8) or 8),
                        args.get("list_name", ""),
                    ),
                )
                result = r or "Animsatici bilgisi alindi."

            elif name == "add_reminder":
                r = await loop.run_in_executor(
                    None,
                    lambda: add_reminder(
                        args.get("title", ""),
                        args.get("due_iso", ""),
                        args.get("notes", ""),
                        args.get("list_name", ""),
                        args.get("priority", ""),
                        bool(args.get("all_day", False)),
                    ),
                )
                result = r or "Animsatici eklendi."

            elif name == "browser_control":
                r = await loop.run_in_executor(
                    None, lambda: browser_control(
                        args.get("action"),
                        args.get("url"),
                        args.get("query")
                    ))
                result = r or "Tamam."

            elif name == "shell_run":
                r = await loop.run_in_executor(
                    None, lambda: shell_run(args.get("command", "")))
                result = r or "Komut çalıştırıldı."

            elif name == "play_media":
                r = await loop.run_in_executor(
                    None,
                    lambda: play_media(
                        args.get("query", ""),
                        args.get("provider", "auto"),
                        bool(args.get("autoplay", True)),
                    ),
                )
                result = r or "Medya oynatma başlatıldı."

            elif name == "get_youtube_channel_report":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_youtube_channel_report(
                        args.get("query", "overview"),
                        args.get("handle", ""),
                        int(args.get("video_limit", 6) or 6),
                    ),
                )
                result = r or "YouTube kanal raporu alindi."

            elif name == "analyze_screen":
                r = await loop.run_in_executor(
                    None,
                    lambda: analyze_screen(
                        args.get("query", "Ekranda ne var?"),
                        args.get("target", "active_window"),
                    ),
                )
                result = r or "Ekran analizi tamamlandi."

            elif name == "send_whatsapp_message":
                r = await loop.run_in_executor(
                    None,
                    lambda: send_whatsapp_message(
                        args.get("message", ""),
                        args.get("phone_number", ""),
                        args.get("recipient_name", ""),
                        bool(args.get("send_now", False)),
                        args.get("app_target", "auto"),
                    ),
                )
                result = r or "WhatsApp işlemi tamamlandı."

            elif name == "save_whatsapp_contact":
                r = await loop.run_in_executor(
                    None,
                    lambda: save_whatsapp_contact(
                        args.get("display_name", ""),
                        args.get("phone_number", ""),
                        args.get("aliases", ""),
                    ),
                )
                result = r or "WhatsApp kişisi kaydedildi."

            else:
                result = f"Bilinmeyen araç: {name}"

        except Exception as e:
            result = f"Hata: {e}"
            had_exception = True
            sys.stdout.write(traceback.format_exc().encode('ascii','replace').decode('ascii'))
            self.speak_error(name, e)

        tool_failed = self._result_looks_like_error(result)
        if tool_failed:
            if not had_exception:
                self.ui.set_state("ERROR")
        elif self._should_play_success_sfx(name, args, result):
            self.ui.play_success_sfx()

        if not tool_failed and not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] OUT {name} -> {str(result)[:80]}")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            # Webcam medyası varsa öncelikle onu gönder
            while hasattr(self, 'ui') and self.ui._media_queue:
                media = self.ui._media_queue.pop(0)
                try:
                    await self.session.send_realtime_input(media=media)
                except Exception as e:
                    err_s = str(e).encode('ascii','replace').decode('ascii')
                    sys.stdout.write(f"[JARVIS] Webcam media gonderilemedi: {err_s}\n")
            msg = await self.out_queue.get()
            data = msg.get("data")
            if data:
                add_sent(len(data))
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[JARVIS] MIC Mikrofon dinleme motoru baslatildi")
        while True:
            if self._paused:
                await asyncio.sleep(0.5)
                continue
                
            stream = None
            try:
                stream = await asyncio.to_thread(
                    pya.open,
                    format=FORMAT, channels=CHANNELS,
                    rate=SEND_SAMPLE_RATE, input=True,
                    frames_per_buffer=CHUNK_SIZE,
                )
                while True:
                    if self._paused:
                        break  # Duraklatıldıysa mikrofonu kapatmak için çık
                        
                    data = await asyncio.to_thread(
                        stream.read, CHUNK_SIZE, exception_on_overflow=False)
                    with self._speaking_lock:
                        jarvis_speaking = self._is_speaking
                    if not jarvis_speaking and not self.ui.muted:
                        await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})
            except Exception as e:
                err_s = str(e).encode('ascii','replace').decode('ascii')
                sys.stdout.write(f"[JARVIS] ! Mikrofon Hatasi (yeniden baslatiliyor...): {err_s}\n")
                await asyncio.sleep(2)  # Tekrar denemeden önce 2 saniye bekle
            finally:
                if stream:
                    try:
                        stream.close()
                    except Exception:
                        pass

    async def _receive_audio(self):
        print("[JARVIS] LISTEN Alim basladi")
        out_buf, in_buf = [], []
        output_noise = False
        output_noise_samples = []
        try:
            while True:
                async for response in self.session.receive():
                    if response.data:
                        add_recv(len(response.data))
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            self.set_speaking(True)
                            raw_txt = sc.output_transcription.text.strip()
                            if raw_txt:
                                txt, had_noise = self._clean_transcript_text(raw_txt)
                                if had_noise:
                                    output_noise = True
                                    if len(output_noise_samples) < 4:
                                        output_noise_samples.append(raw_txt)
                                if txt:
                                    out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                in_buf.append(txt)
                                self.ui.mark_user_activity(True)

                        if sc.turn_complete:
                            # Sentinel: ses kuyruğundaki tüm chunk'lar çalındıktan
                            # sonra SPEAKING -> LISTENING geçişi yapılsın.
                            self.audio_in_queue.put_nowait(None)

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"Siz: {full_in}")
                                self.ui._save_user_message(full_in)
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"JARVIS: {full_out}")
                                self.ui._save_ai_message(full_out)
                                # Mini menü açıksa yanıtı oraya da gönder
                                if self._mini_menu and self._mini_menu._visible:
                                    self._mini_menu.show_response(full_out)
                                if output_noise_samples:
                                    self.ui.write_debug(
                                        "Kısmen filtrelenen ses transcripti: " + " | ".join(output_noise_samples),
                                        level="WARN",
                                    )
                            elif output_noise:
                                self.ui.write_log("ERR: JARVIS sesli yanıtını çözümlerken bir hata oluştu.")
                                if output_noise_samples:
                                    self.ui.write_debug(
                                        "Filtrelenen ham transcript: " + " | ".join(output_noise_samples),
                                        level="WARN",
                                    )
                                self.ui.set_state("ERROR")
                            out_buf = []
                            output_noise = False
                            output_noise_samples = []

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] CALL {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses)

        except Exception as e:
            err_s = str(e).encode('ascii','replace').decode('ascii')
            sys.stdout.write(f"[JARVIS] ERR Alim: {err_s}\n")
            sys.stdout.write(traceback.format_exc().encode('ascii','replace').decode('ascii'))
            raise


    async def _timer_loop(self):
        from core.scheduler import check_timers
        import asyncio
        while True:
            await asyncio.sleep(2)
            try:
                if getattr(self, '_session', None):
                    msgs = check_timers()
                    for m in msgs:
                        self.ui.write_log(f"[!] TIMER TETIKLENDI: {m}")
                        txt = f"SISTEM UYARISI: Kullanicinin kurdugu zamanlayicinin suresi doldu. Hatirlatma mesaji: '{m}'. Lutfen su an bunu kullaniciya hevesli ve yardimsever bir ses tonuyla haber ver."
                        await self._session.send(input={"parts": [{"text": txt}]})
            except Exception:
                pass

    async def _play_audio(self):
        print("[JARVIS] SPEAK Ses calma basladi")
        stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT, channels=CHANNELS,
            rate=RECV_SAMPLE_RATE, output=True,
        )
        try:
            while True:
                chunk = await self.audio_in_queue.get()
                if chunk is None:
                    # turn_complete sentinel — tüm ses çalındı, dinlemeye geç
                    self.set_speaking(False)
                    continue
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            err_s = str(e).encode('ascii','replace').decode('ascii')
            sys.stdout.write(f"[JARVIS] ERR Ses: {err_s}\n")
            raise
        finally:
            self.set_speaking(False)
            stream.close()

    async def run(self):
        client = genai.Client(
            api_key=get_api_key(),
            http_options={"api_version": "v1alpha"}
        )

        while True:
            # Duraklatılmışsa bağlanma, bekle
            if self._paused:
                await asyncio.sleep(1)
                continue

            try:
                print("[JARVIS] CONN Baglaniyor...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=10)

                    print("[JARVIS] OK Baglandi.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS hazır. Dinliyorum...")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._timer_loop())

            except Exception as e:
                self.set_speaking(False)
                if self._reconnect_requested:
                    self._reconnect_requested = False
                    sys.stdout.write("[JARVIS] RECONN Planli yeniden baglanma (ses degisimi).\n")
                    self.ui.write_log("SYS: Yeni sesle yeniden baglaniliyor...")
                    await asyncio.sleep(1)
                else:
                    err_str = str(e).encode('ascii', 'replace').decode('ascii')
                    sys.stdout.write(f"[JARVIS] ! {err_str}\n")
                    sys.stdout.flush()
                    self.ui.write_log(f"ERR: JARVIS baglantisi kesildi veya internete ulasilamiyor - {err_str}")
                    self.ui.set_state("ERROR")
                    sys.stdout.write("[JARVIS] RETRY 3 saniyede yeniden baglaniyor...\n")
                    sys.stdout.flush()
                    await asyncio.sleep(3)


def main():
    if os.environ.get("TERM_PROGRAM") == "vscode":
        print("[JARVIS] VS Code icinden baslatildi.")

    # -- Ana UI (normal başlar, kullanıcı isterse tray'e küçültür) --
    ui = JarvisUI()
    # Ana menü görünür başlar (eski davranış korunuyor)

    jarvis_instance = [None]  # Mutable container

    # -- Mini Menü callback'leri --
    from mini_menu import MiniMenu
    from core.file_parser import parse_file_to_text as _parse

    def _mini_text_submit(text, files):
        """Mini menüden gelen mesajı Jarvis'e ilet."""
        attached = ""
        for fp in files:
            parsed = _parse(fp)
            fname = os.path.basename(fp)
            if len(parsed) > 2000:
                temp_dir = os.path.join(os.getcwd(), "temp_uploads")
                os.makedirs(temp_dir, exist_ok=True)
                tp = os.path.join(temp_dir, f"parsed_{fname}.txt")
                with open(tp, "w", encoding="utf-8") as f:
                    f.write(parsed)
                attached += f"\n\n[EKLENEN DOSYA: {fname}]\n(Dosyayi okumak icin manage_file ile su yolu oku: {tp})\n"
            else:
                attached += f"\n\n[EKLENEN DOSYA: {fname}]\n{parsed}\n"

        final = text + attached
        j = jarvis_instance[0]
        if j and j.session and j._loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(
                j.session.send_client_content(
                    turns={"parts": [{"text": final}]},
                    turn_complete=True
                ),
                j._loop
            )
            ui.write_log(f"Siz (Mini): {text}")
        elif mini_menu:
            mini_menu.show_response("JARVIS henüz bağlı değil. Ana Menüye geçmeyi dene.")

    def _minimize_to_tray():
        """Ana menüyü gizle, tray'e in ve Gemini'yi uyku moduna sok."""
        ui.root.withdraw()
        # Wake word'ü aktif et (tray modunda "Hey Jarvis" ile uyandırılmalı)
        wake_listener.resume()
        
        j = jarvis_instance[0]
        if j and j.session and j._loop:
            # Gemini'ye uyku moduna gectigini bildir
            import asyncio
            msg = "[SİSTEM MESAJI] Sistem şu an arka plana (uyku moduna) alındı. Artık KESİNLİKLE SESLİ CEVAP VERME, SESSİZ KAL. Sadece kullanıcı sana seslenirse (örneğin 'Jarvis uyan', 'Jarvis burda mısın', 'Çalış' derse) hemen 'wake_up_system' aracını çalıştır. Bu aracı çalıştırana kadar beklemede kal."
            asyncio.run_coroutine_threadsafe(
                j.session.send_client_content(
                    turns={"parts": [{"text": msg}]},
                    turn_complete=True
                ),
                j._loop
            )
            
        print("[JARVIS] Tray'e kucultuldu. Uyandirmak icin ona seslen (Orn: 'Jarvis uyan')!")

    def _mini_expand():
        """Mini menüden ana menüye geç."""
        ui.root.deiconify()
        ui.root.lift()
        wake_listener.pause()
        print("[JARVIS] Ana menuye gecildi.")

    def _mini_close():
        """Mini menü kapatıldığında (tray'e geri dön) ve wake word'ü tekrar başlat."""
        print("[JARVIS] Mini menu kapatildi, arka planda devam ediyorum.")
        # Mini menü kapatıldığında wake word'ü tekrar başlat
        wake_listener.resume()

    # UI'ye tray'e küçültme callback'i bağla
    ui.on_minimize_to_tray = _minimize_to_tray
    ui.on_main_menu_show = lambda: wake_listener.pause()

    mini_menu = MiniMenu(
        on_text_submit=_mini_text_submit,
        on_expand=_mini_expand,
        on_close=_mini_close,
        tk_root=ui.root,
    )
    
    # UI'ye wake word mini menü tetikleyicisi bağla
    ui.trigger_mini_menu = mini_menu.show

    # -- Wake Word --
    from core.wake_word import WakeWordListener

    def _on_wake():
        """Wake word algılandığında mini menüyü aç."""
        print("[JARVIS] WAKE Wake word! Mini menu aciliyor...")
        # Mini menü açıldığında wake word'ü pasif et (mikrofon çakışmasını önle)
        wake_listener.pause()
        ui.root.after(0, mini_menu.show)

    wake_listener = WakeWordListener(on_wake=_on_wake)
    wake_listener.pause()  # Başlangıçta ana menü açık, wake word pasif

    # -- Tray --
    from tray_manager import TrayManager

    def _tray_quit():
        wake_listener.stop()
        ui.root.after(0, ui.root.destroy)

    tray = TrayManager(
        on_mini_menu=lambda: ui.root.after(0, mini_menu.show),
        on_main_menu=lambda: ui.root.after(0, _mini_expand),
        on_quit=_tray_quit,
    )

    # -- Jarvis Backend --
    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        jarvis_instance[0] = jarvis
        jarvis._mini_menu = mini_menu  # Mini menü referansı
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n>> Kapatiliyor...")

    threading.Thread(target=runner, daemon=True).start()

    # -- Eski wake gesture (varsa) --
    try:
        old_wake = WakeGestureListener(on_wake=ui.wake_up)
        old_wake.start()
    except Exception:
        pass

    # -- Tray ve Wake Word başlat --
    tray.start()
    wake_listener.start()

    print("[JARVIS] Arka planda calisiyor. 'Jarvis' veya 'Hey Jarvis' deyin!")

    ui.root.mainloop()


if __name__ == "__main__":
    main()

