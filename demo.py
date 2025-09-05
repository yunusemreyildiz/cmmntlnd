#!/usr/bin/env python3
"""
App Review Monitor Demo
WhatsApp uygulamasından örnek yorumları çeker ve gösterir.
"""

from app_review_monitor import AppReviewMonitor
from test_config import TestConfig
import sys

def demo_google_play():
    """Google Play Store'dan örnek yorumları çek"""
    print("🔍 Google Play Store'dan yorumlar çekiliyor...")
    
    try:
        from google_play_scraper import reviews, Sort
        
        result, continuation_token = reviews(
            TestConfig.GOOGLE_PLAY_APP_ID,
            lang='tr',
            country=TestConfig.GOOGLE_PLAY_COUNTRY,
            sort=Sort.NEWEST,
            count=3
        )
        
        print(f"✅ {len(result)} yorum bulundu:")
        print("-" * 50)
        
        for i, review in enumerate(result, 1):
            stars = "⭐" * review['score'] + "☆" * (5 - review['score'])
            print(f"{i}. {review['userName']} - {stars} ({review['score']}/5)")
            print(f"   📅 {review['at']}")
            print(f"   💬 {review['content'][:100]}...")
            print()
            
    except Exception as e:
        print(f"❌ Google Play Store hatası: {e}")

def demo_app_store():
    """App Store'dan örnek yorumları çek"""
    print("🔍 App Store'dan yorumlar çekiliyor...")
    
    try:
        from app_store_scraper import AppStore
        
        app = AppStore(country=TestConfig.APP_STORE_COUNTRY, app_name=TestConfig.APP_STORE_APP_ID)
        app.review(how_many=3)
        
        print(f"✅ {len(app.reviews)} yorum bulundu:")
        print("-" * 50)
        
        for i, review in enumerate(app.reviews, 1):
            stars = "⭐" * review['rating'] + "☆" * (5 - review['rating'])
            print(f"{i}. {review['userName']} - {stars} ({review['rating']}/5)")
            print(f"   📅 {review['date']}")
            print(f"   💬 {review['review'][:100]}...")
            print()
            
    except Exception as e:
        print(f"❌ App Store hatası: {e}")

def demo_slack_format():
    """Slack mesaj formatını göster"""
    print("📱 Slack mesaj formatı örneği:")
    print("=" * 50)
    
    sample_review = {
        'source': 'Google Play',
        'author': 'Ahmet Yılmaz',
        'rating': 5,
        'content': 'Harika bir uygulama! Çok kullanışlı ve hızlı. Kesinlikle tavsiye ederim.',
        'date': '2024-12-15 14:30:00',
        'url': 'https://play.google.com/store/apps/details?id=com.whatsapp'
    }
    
    # Yıldız emojisi oluştur
    stars = "⭐" * sample_review['rating'] + "☆" * (5 - sample_review['rating'])
    
    message = f"""
🔔 **Yeni {sample_review['source']} Yorumu**

**{sample_review['author']}** - {stars} ({sample_review['rating']}/5)
📅 {sample_review['date']}

{sample_review['content']}

🔗 [Yorumu Görüntüle]({sample_review['url']})
"""
    print(message.strip())

def main():
    print("🚀 App Review Monitor Demo")
    print("=" * 50)
    print("Bu demo WhatsApp uygulamasından örnek yorumları çeker.")
    print("Gerçek kullanım için .env dosyasını düzenleyin.\n")
    
    # Slack formatını göster
    demo_slack_format()
    print("\n" + "=" * 50)
    
    # Google Play Store demo
    demo_google_play()
    print("\n" + "=" * 50)
    
    # App Store demo
    demo_app_store()
    
    print("\n🎯 Demo tamamlandı!")
    print("📝 Gerçek kullanım için:")
    print("   1. .env dosyasını düzenleyin")
    print("   2. python3 main.py komutunu çalıştırın")

if __name__ == "__main__":
    main()
