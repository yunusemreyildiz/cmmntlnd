#!/bin/bash

# App Review Monitor - Kurulum Scripti
# Bu script uygulamayı kurmak ve çalıştırmak için gerekli adımları gerçekleştirir

set -e  # Hata durumunda scripti durdur

echo "🚀 App Review Monitor Kurulum Başlatılıyor..."
echo "================================================"

# Python versiyonunu kontrol et
echo "📋 Python versiyonu kontrol ediliyor..."
python3 --version || {
    echo "❌ Python3 bulunamadı. Lütfen Python 3.8+ yükleyin."
    exit 1
}

# pip versiyonunu kontrol et
echo "📋 pip versiyonu kontrol ediliyor..."
pip3 --version || {
    echo "❌ pip3 bulunamadı. Lütfen pip3 yükleyin."
    exit 1
}

# Virtual environment oluştur (opsiyonel)
if [ "$1" = "--venv" ]; then
    echo "🐍 Virtual environment oluşturuluyor..."
    python3 -m venv venv
    source venv/bin/activate
    echo "✅ Virtual environment aktif edildi"
fi

# pip'i güncelle
echo "🔄 pip güncelleniyor..."
pip3 install --upgrade pip

# Bağımlılıkları yükle
echo "📦 Bağımlılıklar yükleniyor..."
pip3 install -r requirements.txt || {
    echo "⚠️  Bağımlılık çakışması tespit edildi. Alternatif kurulum deneniyor..."
    echo "📦 Bağımlılıklar tek tek yükleniyor..."
    pip3 install "requests>=2.23.0,<3.0.0"
    pip3 install python-dotenv
    pip3 install flask
    pip3 install google-play-scraper
    pip3 install app-store-scraper
    pip3 install slack-sdk
    pip3 install gunicorn
}

# .env dosyası oluştur (eğer yoksa)
if [ ! -f ".env" ]; then
    echo "⚙️  .env dosyası oluşturuluyor..."
    cp env_example.txt .env
    echo "✅ .env dosyası oluşturuldu. Lütfen ayarlarınızı düzenleyin."
else
    echo "✅ .env dosyası zaten mevcut"
fi

# Gerekli dizinleri oluştur
echo "📁 Gerekli dizinler oluşturuluyor..."
mkdir -p logs
mkdir -p data

# İzinleri ayarla
echo "🔐 İzinler ayarlanıyor..."
chmod +x web_ui.py
chmod +x main.py

echo ""
echo "🎉 Kurulum tamamlandı!"
echo "================================================"
echo ""
echo "📝 Sonraki adımlar:"
echo "1. .env dosyasını düzenleyin ve ayarlarınızı girin"
echo "2. Web UI'yi başlatın: python3 web_ui.py"
echo "3. Tarayıcınızda http://localhost:5000 adresine gidin"
echo ""
echo "🔧 Manuel kurulum için:"
echo "   python3 web_ui.py"
echo ""
echo "📚 Daha fazla bilgi için README.md dosyasını okuyun"
echo ""
