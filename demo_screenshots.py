#!/usr/bin/env python3
"""
CmmntLnd Demo Screenshot Generator
Bu script demo verilerle uygulamayı çalıştırır ve ekran görüntüleri için hazırlar
"""

import os
import json
import time
from datetime import datetime

def create_demo_data():
    """Demo verileri oluştur"""
    
    # Demo .env dosyası
    demo_env = """# CmmntLnd Demo Configuration
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/demo/webhook/url
SLACK_CHANNEL=#app-reviews

# App Store Configuration
APP_STORE_APP_ID=310633997
APP_STORE_COUNTRY=tr

# Google Play Configuration  
GOOGLE_PLAY_APP_ID=com.whatsapp
GOOGLE_PLAY_COUNTRY=tr

# Monitor Configuration
CHECK_INTERVAL_MINUTES=60
MAX_REVIEWS_PER_CHECK=10
"""
    
    with open('.env', 'w', encoding='utf-8') as f:
        f.write(demo_env)
    
    # Demo sent reviews
    demo_reviews = [
        "review_123456789",
        "review_987654321", 
        "review_456789123"
    ]
    
    with open('sent_reviews.json', 'w', encoding='utf-8') as f:
        json.dump(demo_reviews, f, indent=2)
    
    # Demo last check
    demo_last_check = {
        "google_play": datetime.now().isoformat(),
        "app_store": datetime.now().isoformat()
    }
    
    with open('last_check.json', 'w', encoding='utf-8') as f:
        json.dump(demo_last_check, f, indent=2)
    
    print("✅ Demo veriler oluşturuldu!")

def main():
    """Ana fonksiyon"""
    print("🎬 CmmntLnd Demo Screenshot Generator")
    print("=" * 50)
    
    # Demo verileri oluştur
    create_demo_data()
    
    print("\n📸 Ekran görüntüleri için hazırlık:")
    print("1. Web UI'yi başlatın: python3 web_ui.py")
    print("2. Tarayıcıda http://localhost:5000 adresine gidin")
    print("3. Aşağıdaki ekran görüntülerini alın:")
    print("")
    print("📱 Alınacak ekranlar:")
    print("   • Ana sayfa (Dashboard)")
    print("   • Settings sayfası")
    print("   • Logs sayfası")
    print("")
    print("💾 Dosya isimleri:")
    print("   • assets/screenshots/dashboard.png")
    print("   • assets/screenshots/settings.png") 
    print("   • assets/screenshots/logs.png")
    print("")
    print("🚀 Web UI'yi başlatmak için:")
    print("   python3 web_ui.py")

if __name__ == "__main__":
    main()
