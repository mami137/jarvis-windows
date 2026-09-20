<div align="center">

# 🤖 JARVIS

### Windows AI Asistanı

**Sesle kontrol edilen kişisel yapay zeka asistanı**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Gemini](https://img.shields.io/badge/Gemini_API-2D2D2D?style=for-the-badge&logo=google&logoColor=white)](https://aistudio.google.com)
[![Platform](https://img.shields.io/badge/Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white)](https://microsoft.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

[📦 Releases](https://github.com/mami137/jarvis-windows/releases) • [🐛 Sorunlar](https://github.com/mami137/jarvis-windows/issues) • [⭐ Yıldız](https://github.com/mami137/jarvis-windows/stargazers)

---

*J.A.R.V.I.S — Just A Rather Very Intelligent System*

</div>

## ✨ Özellikler

| Özellik | Açıklama |
|---------|----------|
| 🎤 **Sesli Sohbet** | Doğal dil ile sesli iletişim (Gemini Live API) |
| 🔊 **MCI Ses Sistemi** | Tık sesleri, ortam sesi, hata sesleri |
| 📷 **Webcam** | Kamera görüntüsü gönderme ve analiz |
| 🌤️ **Hava Durumu** | Gerçek zamanlı hava durumu bilgisi |
| 💻 **Sistem Durumu** | CPU, RAM, batarya, disk bilgileri |
| 🌐 **Tarayıcı Kontrolü** | Web araması, URL açma |
| 🗣️ **Çoklu Dil** | Türkçe ve İngilizce tam destek |
| 💬 **Sohbet Geçmişi** | Çoklu sohbet yönetimi, JSON kayıt |
| ⏸️ **Wake Word** | "Hey Jarvis" ile aktivasyon |
| 🖥️ **Sistem Tepsisi** | Arka planda çalışma desteği |

## 🚀 Kurulum

### Yöntem 1: Exe ile (Kolay)

1. [Releases](https://github.com/mami137/jarvis-windows/releases) sayfasından `Jarvis.zip`'i indir
2. Zip'i herhangi bir klasöre çıkar
3. `Jarvis.exe`'yi çalıştır
4. İlk açılışta Gemini API anahtarını gir

### Yöntem 2: Kaynak Kod ile (Geliştiriciler)

```bash
# Depoyu klonla
git clone https://github.com/mami137/jarvis-windows.git
cd jarvis-windows

# Bağımlılıkları kur
pip install -r requirements.txt

# Çalıştır
python main.py
```

## 📋 Gereksinimler

- **İşletim Sistemi:** Windows 10/11
- **Python:** 3.12+ (sadece kaynak kod ile çalışanlar için)
- **API:** Google Gemini API anahtarı (ücretsiz: [aistudio.google.com](https://aistudio.google.com))

## 🏗️ Proje Yapısı

```
jarvis-windows/
├── main.py              # Ana uygulama giriş noktası
├── ui.py                # Arayüz (tkinter)
├── app_config.py        # Yapılandırma yönetimi
├── webcam.py            # Kamera entegrasyonu
├── wakeup_listener.py   # Wake word dinleyici
├── requirements.txt     # Python bağımlılıkları
├── setup.bat            # Otomatik kurulum
├── actions/             # Eylem modülleri
│   ├── browser.py       # Tarayıcı kontrolü
│   ├── health.py        # Sistem durumu
│   ├── media.py         # Medya oynatma
│   ├── weather.py       # Hava durumu
│   ├── shell.py         # Komut satırı
│   └── ...
├── core/                # Çekirdek modüller
│   ├── auto_router.py   # Model yönlendirme
│   ├── chat_manager.py  # Sohbet yönetimi
│   ├── i18n.py          # Dil çevirileri
│   ├── llm_router.py    # LLM motor seçici
│   ├── prompt.txt       # AI sistem promptu
│   ├── scheduler.py     # Zamanlayıcı
│   └── wake_word.py     # Wake word motoru
├── config/              # API anahtarları
├── memory/              # Hafıza yönetimi
└── SFX/                 # Ses dosyaları
```

## ⚙️ Yapılandırma

İlk çalıştırmada API anahtarı gereklidir:

1. [Google AI Studio](https://aistudio.google.com/apikey) adresinden ücretsiz API anahtarı alın
2. JARVIS'i başlatın
3. Açılan pencerede anahtarı girin
4. Kaydet deyin, JARVIS kullanıma hazır!

> 💡 **İpucu:** OpenRouter API anahtarı da ekleyebilirsiniz — bu sayede farklı LLM modellerini (GPT-4, Claude, vb.) kullanabilirsiniz.

## 🛠️ Teknolojiler

- **Python 3.12** — Ana programlama dili
- **Google Gemini Live API** — Sesli yapay zeka motoru
- **Tkinter** — Grafik arayüz
- **PyAudio** — Ses giriş/çıkışı
- **Vosk** — Yerel ses tanıma (wake word)
- **OpenCV** — Kamera işleme
- **PyStray** — Sistem tepsisi ikonu

## 📸 Ekran Görüntüleri

> Yakında eklenecek...

## � Katkıda Bulunma

1. Fork oluştur
2. Branch oluştur (`git checkout -b ozellik/yeni-ozellik`)
3. Değişiklikleri commit et (`git commit -m 'Yeni özellik ekle'`)
4. Push et (`git push origin ozellik/yeni-ozellik`)
5. Pull Request oluştur

## 📄 Lisans

Bu proje MIT Lisansı altında dağıtılmaktadır. Detaylı bilgi için [LICENSE](LICENSE) dosyasına bakın.

---

<div align="center">

**JARVIS'i beğendiyseniz ⭐ star vermeyi unutmayın!**

Made with ❤️ by [mami137](https://github.com/mami137)

</div>
