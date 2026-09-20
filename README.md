<div align="center">

# JARVIS

### Windows AI Assistant

**Voice-controlled personal AI assistant powered by Gemini**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Gemini](https://img.shields.io/badge/Gemini_API-2D2D2D?style=for-the-badge&logo=google&logoColor=white)](https://aistudio.google.com)
[![Platform](https://img.shields.io/badge/Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white)](https://microsoft.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

[Releases](https://github.com/mami137/jarvis-windows/releases) | [Issues](https://github.com/mami137/jarvis-windows/issues) | [Stars](https://github.com/mami137/jarvis-windows/stargazers)

---

*J.A.R.V.I.S - Just A Rather Very Intelligent System*

</div>

## Features

| Feature | Description |
|---------|-------------|
| **Voice Chat** | Natural voice communication via Gemini Live API |
| **MCI Sound System** | Click sounds, ambient audio, error alerts |
| **Webcam** | Send camera feed for AI analysis |
| **Weather** | Real-time weather information |
| **System Monitor** | CPU, RAM, battery, disk stats |
| **Browser Control** | Web search, open URLs |
| **Multi-Language** | Full Turkish and English support |
| **Chat History** | Multi-conversation management with JSON storage |
| **Wake Word** | "Hey Jarvis" voice activation |
| **System Tray** | Run in background |

## Installation

### Option 1: Exe (Easy)

1. Download `Jarvis.zip` from [Releases](https://github.com/mami137/jarvis-windows/releases)
2. Extract to any folder
3. Run `Jarvis.exe`
4. Enter your Gemini API key on first launch

### Option 2: Source Code (Developers)

```bash
git clone https://github.com/mami137/jarvis-windows.git
cd jarvis-windows
pip install -r requirements.txt
python main.py
```

## Requirements

- **OS:** Windows 10/11
- **Python:** 3.12+ (source code users only)
- **API:** Google Gemini API key (free at [aistudio.google.com](https://aistudio.google.com))

## Project Structure

```
jarvis-windows/
  main.py              # Main entry point
  ui.py                # GUI (tkinter)
  app_config.py        # Configuration manager
  webcam.py            # Camera integration
  wakeup_listener.py   # Wake word listener
  requirements.txt     # Python dependencies
  setup.bat            # Auto setup
  actions/             # Action modules
    browser.py         # Browser control
    health.py          # System status
    media.py           # Media playback
    weather.py         # Weather info
    shell.py           # Terminal commands
  core/                # Core modules
    auto_router.py     # Model routing
    chat_manager.py    # Chat management
    i18n.py            # Translations
    llm_router.py      # LLM engine selector
    prompt.txt         # AI system prompt
    scheduler.py       # Task scheduler
    wake_word.py       # Wake word engine
  config/              # API keys
  memory/              # Memory management
  SFX/                 # Sound effects
```

## Configuration

An API key is required on first run:

1. Get a free API key from [Google AI Studio](https://aistudio.google.com/apikey)
2. Launch JARVIS
3. Enter the key in the popup window
4. Click Save - JARVIS is ready!

> **Tip:** You can also add an OpenRouter API key to use different LLM models (GPT-4, Claude, etc.)

## Technologies

- **Python 3.12** - Core language
- **Google Gemini Live API** - Voice AI engine
- **Tkinter** - GUI framework
- **PyAudio** - Audio I/O
- **Vosk** - Local speech recognition (wake word)
- **OpenCV** - Camera processing
- **PyStray** - System tray icon

## Contributing

1. Fork the repo
2. Create a branch (`git checkout -b feature/new-feature`)
3. Commit changes (`git commit -m 'Add new feature'`)
4. Push (`git push origin feature/new-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License.

---

**If you like JARVIS, give it a star!**
