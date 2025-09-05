import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

class Config:
    # Slack ayarları
    SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')
    SLACK_CHANNEL = os.getenv('SLACK_CHANNEL', '#app-reviews')
    
    # App Store ayarları
    APP_STORE_APP_ID = os.getenv('APP_STORE_APP_ID')
    APP_STORE_COUNTRY = os.getenv('APP_STORE_COUNTRY', 'all')
    
    # Google Play Store ayarları
    GOOGLE_PLAY_APP_ID = os.getenv('GOOGLE_PLAY_APP_ID')
    GOOGLE_PLAY_COUNTRY = os.getenv('GOOGLE_PLAY_COUNTRY', 'all')
    
    # İzleme ayarları
    CHECK_INTERVAL_MINUTES = int(os.getenv('CHECK_INTERVAL_MINUTES', '60'))  # Saat başı
    MAX_REVIEWS_PER_CHECK = int(os.getenv('MAX_REVIEWS_PER_CHECK', '10'))
    
    # Temizlik ayarları
    CLEANUP_DAYS = int(os.getenv('CLEANUP_DAYS', '30'))  # 30 gün sonra temizle
    MAX_STORED_REVIEWS = int(os.getenv('MAX_STORED_REVIEWS', '1000'))  # Max 1000 ID sakla
    
    @classmethod
    def validate(cls):
        """Gerekli konfigürasyonları kontrol et"""
        required_vars = [
            'SLACK_WEBHOOK_URL',
            'APP_STORE_APP_ID',
            'GOOGLE_PLAY_APP_ID'
        ]
        
        missing_vars = []
        for var in required_vars:
            if not getattr(cls, var):
                missing_vars.append(var)
        
        if missing_vars:
            raise ValueError(f"Eksik konfigürasyon değişkenleri: {', '.join(missing_vars)}")
        
        return True
