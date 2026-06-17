#!/usr/bin/env python3
"""
App Review Monitor - Ana çalıştırma dosyası
Google Play Store ve App Store yorumlarını takip eder ve Slack'e gönderir.
"""

import os
import fcntl
import schedule
import time
import signal
import sys
from datetime import datetime
from app_review_monitor import AppReviewMonitor

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_MONITOR_LOCK_PATH = os.path.join(_BASE_DIR, '.monitor.lock')


class ReviewMonitorService:
    def __init__(self):
        self.monitor = AppReviewMonitor()
        self.running = True
        self._monitor_lock_fd = None

        # Graceful shutdown için signal handler
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """Graceful shutdown için signal handler"""
        print(f"\n🛑 Signal {signum} alındı. Servis kapatılıyor...")
        self.running = False

    def _acquire_monitor_lock(self) -> bool:
        """web_ui içindeki monitor ile aynı anda çalışmasın (ortak .monitor.lock)."""
        try:
            fd = open(_MONITOR_LOCK_PATH, 'w')
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(
                "❌ Monitor kilidi alınamadı: başka bir süreç zaten yorum döngüsü çalıştırıyor "
                f"({_MONITOR_LOCK_PATH}).\n"
                "   Web UI’den Başlat’a basılmış olabilir veya ikinci bir `main.py` açık.\n"
                "   Önce diğerini durdur, sonra tekrar dene."
            )
            return False
        except OSError as e:
            print(f"❌ Monitor kilidi açılamadı: {e}")
            return False
        fd.write(str(os.getpid()))
        fd.flush()
        self._monitor_lock_fd = fd
        return True

    def _release_monitor_lock(self) -> None:
        if not self._monitor_lock_fd:
            return
        try:
            fcntl.flock(self._monitor_lock_fd.fileno(), fcntl.LOCK_UN)
            self._monitor_lock_fd.close()
        except OSError:
            pass
        self._monitor_lock_fd = None

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
            # Disk ile birleştir (= kullanma: disk yazılamazsa boş set belleği sıfırlar)
            self.monitor.sent_reviews |= self.monitor.load_sent_reviews()
            print(f"📋 Sent reviews birleştirildi (bellek ∪ disk): {len(self.monitor.sent_reviews)} adet")
            
            self.monitor.check_and_send_reviews()
        except Exception as e:
            print(f"❌ Yorum kontrolü sırasında hata: {e}")

    def daily_summary_job(self):
        """Günlük istatistik özeti işi (rating + ranking → DB + Slack)"""
        if not self.running:
            return
        try:
            print("📊 Günlük özet işi çalışıyor...")
            self.monitor.send_daily_summary()
        except Exception as e:
            print(f"❌ Günlük özet sırasında hata: {e}")
    
    def start_monitoring(self):
        """İzleme servisini başlat"""
        if not self._acquire_monitor_lock():
            return

        print("🚀 App Review Monitor başlatılıyor...")
        print(f"⏰ Kontrol aralığı: {self.monitor.config.CHECK_INTERVAL_MINUTES} dakika")
        print(f"📱 Google Play App ID: {self.monitor.config.GOOGLE_PLAY_APP_ID}")
        print(f"🍎 App Store App ID: {self.monitor.config.APP_STORE_APP_ID}")
        print(f"💬 Slack Kanalı: {self.monitor.config.SLACK_CHANNEL}")
        print("-" * 50)

        try:
            # İlk kurulumu çalıştır
            if not self.run_initial_setup():
                print("❌ İlk kurulum başarısız. Servis durduruluyor.")
                return

            # Zamanlanmış görevleri ayarla
            schedule.every(self.monitor.config.CHECK_INTERVAL_MINUTES).minutes.do(self.check_reviews_job)
            # Günlük istatistik özeti — her gün 10:00
            daily_time = os.getenv('DAILY_SUMMARY_TIME', '10:00')
            schedule.every().day.at(daily_time).do(self.daily_summary_job)

            print(f"✅ Servis başlatıldı. {self.monitor.config.CHECK_INTERVAL_MINUTES} dakikada bir kontrol yapılacak.")
            print(f"📊 Günlük özet her gün {daily_time}'da Slack'e gönderilecek.")
            print("🔄 Servis çalışıyor... (Ctrl+C ile durdurun)")
            print("💡 Sadece yeni yorum varsa Slack'e mesaj gönderilecek")

            # Ana döngü
            try:
                while self.running:
                    try:
                        schedule.run_pending()
                        time.sleep(1)
                    except KeyboardInterrupt:
                        print("\n🛑 KeyboardInterrupt alındı. Servis kapatılıyor...")
                        break
                    except Exception as e:
                        print(f"❌ Ana döngüde hata: {e}")
                        time.sleep(5)  # Hata durumunda 5 saniye bekle
            except Exception as e:
                print(f"❌ Servis hatası: {e}")
            finally:
                print("👋 App Review Monitor durduruldu.")
        finally:
            self._release_monitor_lock()

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
