# CmmntLnd - App Review Monitor

## 🎯 Proje Amacı
App Store ve Google Play Store yorumlarını otomatik olarak takip eden, Slack'e anlık bildirimler gönderen kapsamlı bir monitoring sistemi.

## ✨ Özellikler
- 🍎 **App Store Integration**: RSS Feed ile yorum takibi
- 🤖 **Google Play Integration**: API ile yorum takibi  
- 💬 **Slack Notifications**: Anlık bildirimler
- 🌐 **Modern Web UI**: Flask tabanlı dashboard
- 📊 **Database Export**: CSV/JSON formatında veri dışa aktarma
- 🐳 **Docker Support**: Containerized deployment
- 🔄 **CI/CD Ready**: GitLab pipeline desteği

## 🚀 Hızlı Başlangıç

### Gereksinimler
- Python 3.8+
- Docker (opsiyonel)

### Kurulum
```bash
# Repository'yi klonla
git clone https://gitlab.pttavm.com/qa-team/review-monitor.git
cd review-monitor

# Bağımlılıkları yükle
pip install -r requirements.txt

# Konfigürasyonu ayarla
cp config.py.example config.py
# config.py dosyasını düzenle

# Web UI'yi başlat
python web_ui.py --port 5001
```

### Docker ile Çalıştırma
```bash
docker-compose up -d
```

## 📊 Kullanım
- **Web Dashboard**: http://localhost:5001
- **Database Export**: http://localhost:5001/database
- **Logs**: http://localhost:5001/logs

## 🔧 Konfigürasyon
`config.py` dosyasında:
- Slack Webhook URL
- App Store App ID
- Google Play Package Name
- Monitoring interval

## 📈 Deployment
GitLab CI/CD pipeline ile otomatik deployment:
- Docker image build
- Container registry push
- Server deployment

## 👥 Katkıda Bulunma
1. Fork yap
2. Feature branch oluştur
3. Commit yap
4. Pull request gönder

## 📄 Lisans
Bu proje şirket içi kullanım için geliştirilmiştir.
