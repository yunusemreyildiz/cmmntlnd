import os

# Test için geçici konfigürasyon
class TestConfig:
    # Slack ayarları (test için)
    SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
    SLACK_CHANNEL = "#app-reviews"
    
    # App Store ayarları (PttAVM örneği)
    APP_STORE_APP_ID = "1435788518"  # PttAVM App Store ID
    APP_STORE_COUNTRY = "tr"
    
    # Google Play Store ayarları (PttAVM örneği)
    GOOGLE_PLAY_APP_ID = "com.pttem.epttavm"  # PttAVM Google Play ID
    GOOGLE_PLAY_COUNTRY = "tr"
    
    # İzleme ayarları
    CHECK_INTERVAL_MINUTES = 60  # Saat başı
    MAX_REVIEWS_PER_CHECK = 10
    
    @classmethod
    def validate(cls):
        """Test konfigürasyonu için basit kontrol"""
        print("⚠️  Test modunda çalışıyor - Gerçek Slack webhook URL'i gerekli!")
        return True
