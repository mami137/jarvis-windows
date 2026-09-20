@echo off
chcp 65001 >nul
echo.
echo ╔══════════════════════════════════════╗
echo ║     J.A.R.V.I.S  Windows Kurulum    ║
echo ╚══════════════════════════════════════╝
echo.

REM Python kontrolü
python --version >nul 2>&1
if errorlevel 1 (
    echo [HATA] Python bulunamadi. python.org adresinden Python 3.10+ yukle.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo [OK] %%i

REM Virtual environment
if not exist "venv" (
    echo [*] Virtual environment olusturuluyor...
    python -m venv venv
)

call venv\Scripts\activate.bat

REM API key dosyası
if not exist "config\api_keys.json" (
    copy "config\api_keys.example.json" "config\api_keys.json" >nul
    echo [*] config\api_keys.json olusturuldu — Gemini API anahtarini buraya gir
)

echo [*] Paketler yukleniyor...
pip install --upgrade pip -q
pip install -r requirements.txt -q

REM Fontları Windows font dizinine kur (yönetici gerekebilir)
if exist "Fonts" (
    echo [*] Grift fontlari kuruluyor...
    for %%f in (Fonts\*.ttf) do (
        copy "%%f" "%WINDIR%\Fonts\" >nul 2>&1
    )
    echo [OK] Fontlar kuruldu (basarisiz olursa Fonts klasorunden elle yukle)
)

echo.
echo ╔══════════════════════════════════════╗
echo ║         Kurulum Tamamlandi!          ║
echo ╚══════════════════════════════════════╝
echo.
echo JARVIS'i baslatmak icin:
echo   venv\Scripts\activate.bat
echo   python main.py
echo.
set /p choice="Simdi baslatilsin mi? (e/h): "
if /i "%choice%"=="e" python main.py
