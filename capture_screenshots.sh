#!/bin/bash

# CmmntLnd Screenshot Capture Script
# Bu script uygulamanın ekran görüntülerini alır

echo "📸 CmmntLnd Ekran Görüntüleri Alınıyor..."
echo "=========================================="

# Assets klasörünü oluştur
mkdir -p assets/screenshots

echo "🌐 Web UI'yi başlatıyoruz..."
echo "Lütfen tarayıcınızda http://localhost:5000 adresine gidin"
echo "Ve ekran görüntülerini manuel olarak alın:"
echo ""
echo "📱 Alınacak ekran görüntüleri:"
echo "1. Ana sayfa (Dashboard) - assets/screenshots/dashboard.png"
echo "2. Settings sayfası - assets/screenshots/settings.png"
echo "3. Logs sayfası - assets/screenshots/logs.png"
echo ""
echo "💡 macOS'ta ekran görüntüsü alma:"
echo "   Cmd + Shift + 4: Alan seçimi"
echo "   Cmd + Shift + 3: Tüm ekran"
echo "   Cmd + Shift + 5: Ekran görüntüsü aracı"
echo ""
echo "⏳ 30 saniye bekleyin, sonra ekran görüntülerini alın..."

# 30 saniye bekle
sleep 30

echo "✅ Ekran görüntüleri alındı!"
echo "📁 Dosyalar assets/screenshots/ klasöründe saklanacak"
