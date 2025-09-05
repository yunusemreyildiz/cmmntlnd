@echo off
REM App Review Monitor - Windows Kurulum Scripti
REM Bu script uygulamayı kurmak ve çalıştırmak için gerekli adımları gerçekleştirir

echo 🚀 App Review Monitor Kurulum Başlatılıyor...
echo ================================================

REM Python versiyonunu kontrol et
echo 📋 Python versiyonu kontrol ediliyor...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python bulunamadı. Lütfen Python 3.8+ yükleyin.
    echo https://www.python.org/downloads/ adresinden indirebilirsiniz.
    pause
    exit /b 1
)

REM pip versiyonunu kontrol et
echo 📋 pip versiyonu kontrol ediliyor...
pip --version >nul 2>&1
if errorlevel 1 (
    echo ❌ pip bulunamadı. Lütfen pip yükleyin.
    pause
    exit /b 1
)

REM Virtual environment oluştur (opsiyonel)
if "%1"=="--venv" (
    echo 🐍 Virtual environment oluşturuluyor...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo ✅ Virtual environment aktif edildi
)

REM Bağımlılıkları yükle
echo 📦 Bağımlılıklar yükleniyor...
pip install -r requirements.txt

REM .env dosyası oluştur (eğer yoksa)
if not exist ".env" (
    echo ⚙️  .env dosyası oluşturuluyor...
    copy env_example.txt .env
    echo ✅ .env dosyası oluşturuldu. Lütfen ayarlarınızı düzenleyin.
) else (
    echo ✅ .env dosyası zaten mevcut
)

REM Gerekli dizinleri oluştur
echo 📁 Gerekli dizinler oluşturuluyor...
if not exist "logs" mkdir logs
if not exist "data" mkdir data

echo.
echo 🎉 Kurulum tamamlandı!
echo ================================================
echo.
echo 📝 Sonraki adımlar:
echo 1. .env dosyasını düzenleyin ve ayarlarınızı girin
echo 2. Web UI'yi başlatın: python web_ui.py
echo 3. Tarayıcınızda http://localhost:5000 adresine gidin
echo.
echo 🔧 Manuel kurulum için:
echo    python web_ui.py
echo.
echo 📚 Daha fazla bilgi için README.md dosyasını okuyun
echo.
pause
