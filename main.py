#!/usr/bin/env python3
"""
App Review Monitor - Ana çalıştırma dosyası
Google Play Store ve App Store yorumlarını takip eder ve Slack'e gönderir.
"""

import schedule
import time
import signal
import sys
from datetime import datetime
from app_review_monitor import AppReviewMonitor

class ReviewMonitorService:
    def __init__(self):
        self.monitor = AppReviewMonitor()
        self.running = True
        
        # Graceful shutdown için signal handler
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """Graceful shutdown için signal handler"""
        print(f"\n🛑 Signal {signum} alındı. Servis kapatılıyor...")
        self.running = False
    
    def run_initial_setup(self):
        """İlk kurulumu çalıştır"""
        try:
            self.monitor.run_initial_setup()
            return True
        except Exception as e:
            print(f"❌ İlk kurulum sırasında hata: {e}")
            return False
    
    def check_reviews_job(self):
        """Zamanlanmış yorum kontrolü işi"""
        if not self.running:
            return
        
        try:
            self.monitor.check_and_send_reviews()
        except Exception as e:
            print(f"❌ Yorum kontrolü sırasında hata: {e}")
    
    def start_monitoring(self):
        """İzleme servisini başlat"""
        print("🚀 App Review Monitor başlatılıyor...")
        print(f"⏰ Kontrol aralığı: {self.monitor.config.CHECK_INTERVAL_MINUTES} dakika")
        print(f"📱 Google Play App ID: {self.monitor.config.GOOGLE_PLAY_APP_ID}")
        print(f"🍎 App Store App ID: {self.monitor.config.APP_STORE_APP_ID}")
        print(f"💬 Slack Kanalı: {self.monitor.config.SLACK_CHANNEL}")
        print("-" * 50)
        
        # İlk kurulumu çalıştır
        if not self.run_initial_setup():
            print("❌ İlk kurulum başarısız. Servis durduruluyor.")
            return
        
        # Zamanlanmış görevleri ayarla
        schedule.every(self.monitor.config.CHECK_INTERVAL_MINUTES).minutes.do(self.check_reviews_job)
        
        print(f"✅ Servis başlatıldı. Saat başı kontrol yapılacak.")
        print("🔄 Servis çalışıyor... (Ctrl+C ile durdurun)")
        print("💡 Sadece yeni yorum varsa Slack'e mesaj gönderilecek")
        
        # Ana döngü
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                break
        
        print("👋 App Review Monitor durduruldu.")

def main():
    """Ana fonksiyon"""
    print("=" * 60)
    print("📱 App Review Monitor")
    print("Google Play Store ve App Store yorumlarını Slack'e gönderir")
    print("=" * 60)
    
    try:
        service = ReviewMonitorService()
        service.start_monitoring()
    except Exception as e:
        print(f"❌ Servis başlatılırken hata: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
