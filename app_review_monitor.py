import json
import os
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import requests
from google_play_scraper import reviews, Sort
from app_store_scraper import AppStore
from config import Config
from dateutil import parser as date_parser

class AppReviewMonitor:
    def __init__(self):
        self.config = Config()
        self.config.validate()
        self.sent_reviews_file = 'sent_reviews.json'  # Gönderilen yorumları sakla
        self.sent_reviews = self.load_sent_reviews()  # Disk'ten yükle
        self.last_check_file = 'last_check.json'
        self.last_check_times = self.load_last_check_times()
    
    def parse_date(self, date_input):
        """Tarih objesini normalize et - string veya datetime'ı datetime'a çevir"""
        if isinstance(date_input, str):
            try:
                parsed = date_parser.parse(date_input)
                # Timezone bilgisini kaldır (naive datetime yap)
                if parsed.tzinfo is not None:
                    parsed = parsed.replace(tzinfo=None)
                return parsed
            except:
                return datetime.now()
        elif isinstance(date_input, datetime):
            # Timezone bilgisini kaldır (naive datetime yap)
            if date_input.tzinfo is not None:
                date_input = date_input.replace(tzinfo=None)
            return date_input
        else:
            return datetime.now()
    
    def load_sent_reviews(self):
        """Daha önce gönderilen yorumları disk'ten yükle"""
        try:
            if os.path.exists(self.sent_reviews_file):
                with open(self.sent_reviews_file, 'r', encoding='utf-8') as f:
                    return set(json.load(f))
            return set()
        except Exception as e:
            print(f"⚠️  Gönderilen yorumlar yüklenemedi: {e}")
            return set()
    
    def save_sent_reviews(self):
        """Gönderilen yorumları disk'e kaydet"""
        try:
            with open(self.sent_reviews_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.sent_reviews), f, ensure_ascii=False, indent=2)
            self.cleanup_old_reviews()  # Eski yorumları temizle
        except Exception as e:
            print(f"⚠️  Gönderilen yorumlar kaydedilemedi: {e}")
    
    def cleanup_old_reviews(self):
        """Eski review ID'lerini temizle (ayarlanabilir) - Tarih kontrolü ile güvenli"""
        try:
            # Max review sayısını aştıysa temizle
            if len(self.sent_reviews) > self.config.MAX_STORED_REVIEWS:
                print(f"⚠️  Review limit aşıldı: {len(self.sent_reviews)} > {self.config.MAX_STORED_REVIEWS}")
                
                # ÖNEMLİ: Son kontrol tarihlerini geri almayalım!
                # Böylece silinen ID'ler tarih kontrolü ile engellenir
                
                # Sadece yarısını tut (en yenileri)
                old_count = len(self.sent_reviews)
                reviews_list = list(self.sent_reviews)
                keep_count = self.config.MAX_STORED_REVIEWS // 2
                self.sent_reviews = set(reviews_list[-keep_count:])  # Son yarısını tut
                
                print(f"🧹 Eski review ID'leri temizlendi: {old_count} → {len(self.sent_reviews)}")
                print(f"🛡️  Tarih kontrolü aktif - silinen yorumlar yeniden gönderilmeyecek")
                print(f"📅 Google Play son kontrol: {self.last_check_times.get('google_play')}")
                print(f"📅 App Store son kontrol: {self.last_check_times.get('app_store')}")
                
        except Exception as e:
            print(f"⚠️  Eski yorum temizleme hatası: {e}")
    
    def load_last_check_times(self):
        """Son kontrol zamanlarını disk'ten yükle"""
        try:
            if os.path.exists(self.last_check_file):
                with open(self.last_check_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # String tarihlerini datetime'a çevir
                    for platform in data:
                        if data[platform]:
                            data[platform] = datetime.fromisoformat(data[platform])
                    return data
            return {'google_play': None, 'app_store': None}
        except Exception as e:
            print(f"⚠️  Son kontrol zamanları yüklenemedi: {e}")
            return {'google_play': None, 'app_store': None}
    
    def save_last_check_times(self):
        """Son kontrol zamanlarını disk'e kaydet"""
        try:
            # Datetime'ları string'e çevir
            data = {}
            for platform, dt in self.last_check_times.items():
                data[platform] = dt.isoformat() if dt else None
            
            with open(self.last_check_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️  Son kontrol zamanları kaydedilemedi: {e}")
    
    def update_last_check_time(self, platform: str, latest_date: datetime):
        """Platform için son kontrol zamanını güncelle"""
        if not self.last_check_times[platform] or latest_date > self.last_check_times[platform]:
            self.last_check_times[platform] = latest_date
            self.save_last_check_times()
            print(f"📅 {platform} için son kontrol zamanı güncellendi: {latest_date.strftime('%d.%m.%Y %H:%M')}")
    
    def is_review_sent(self, review_id: str) -> bool:
        """Bu yorum daha önce gönderildi mi?"""
        return review_id in self.sent_reviews
    
    def mark_review_as_sent(self, review_id: str):
        """Yorumu gönderildi olarak işaretle"""
        self.sent_reviews.add(review_id)
        self.save_sent_reviews()
        
    def get_google_play_reviews(self) -> List[Dict]:
        """Google Play Store'dan yeni yorumları çek - sadece son kontrolden yeni olanları"""
        try:
            # Son kontrol zamanını al
            last_check = self.last_check_times.get('google_play')
            if last_check:
                print(f"📅 Google Play son kontrol: {last_check.strftime('%d.%m.%Y %H:%M')}")
            else:
                print("📅 Google Play ilk kontrol yapılıyor")
            
            # Ülke ayarını kontrol et
            country = self.config.GOOGLE_PLAY_COUNTRY if self.config.GOOGLE_PLAY_COUNTRY != 'all' else 'tr'
            
            result, continuation_token = reviews(
                self.config.GOOGLE_PLAY_APP_ID,
                lang='tr',
                country=country,
                sort=Sort.NEWEST,
                count=self.config.MAX_REVIEWS_PER_CHECK * 2  # Biraz fazla al ki filtreden sonra yeterli kalsın
            )
            
            # Sadece yeni yorumları filtrele
            new_reviews = []
            newest_date = None
            processed_count = 0
            
            for review in result:
                try:
                    review_id = review['reviewId']
                    review_date = self.parse_date(review['at'])
                    
                    # En yeni tarihi takip et
                    if newest_date is None or review_date > newest_date:
                        newest_date = review_date
                    
                    # SADECE son kontrolden daha YENİ olanları al (GÜÇLÜ KORUMA)
                    if last_check and review_date <= last_check:
                        # Bu yorum zaten kontrol edildi, atla
                        continue
                    
                    # Daha önce gönderildi mi kontrol et (İKİNCİL KORUMA)
                    if self.is_review_sent(review_id):
                        print(f"⏭️  ID kontrolü: Daha önce gönderilmiş - {review['userName']}")
                        continue
                    
                    # Maximum limit kontrolü
                    if processed_count >= self.config.MAX_REVIEWS_PER_CHECK:
                        print(f"📝 Google Play: {self.config.MAX_REVIEWS_PER_CHECK} yeni yorum limiti doldu, durduruluyor")
                        break
                    
                    new_reviews.append({
                        'source': 'Google Play',
                        'review_id': review_id,
                        'rating': review['score'],
                        'title': review.get('title', ''),
                        'content': review['content'],
                        'author': review['userName'],
                        'date': review_date,
                        'url': f"https://play.google.com/store/apps/details?id={self.config.GOOGLE_PLAY_APP_ID}&reviewId={review_id}"
                    })
                    processed_count += 1
                    print(f"🆕 Yeni Google Play yorumu bulundu: {review['userName']} - {review_date.strftime('%d.%m.%Y %H:%M')}")
                    
                except Exception as e:
                    print(f"⚠️  Google Play yorum parse hatası: {e}")
                    continue
            
            # En yeni tarihi güncelle (yorum bulunsa da bulunmasa da)
            # ÖNEMLİ: Yorum gönderilsin ya da gönderilmesin, son kontrol zamanını güncelle
            if newest_date:
                self.update_last_check_time('google_play', newest_date)
            elif last_check:
                # Eğer hiç yeni yorum yoksa, şu anki zamanı kaydet
                self.update_last_check_time('google_play', datetime.now())
            
            if new_reviews:
                print(f"✅ Google Play'da {len(new_reviews)} gerçekten yeni yorum bulundu")
            else:
                print("📭 Google Play'da yeni yorum bulunmadı (tüm yorumlar son kontrolden eski)")
            return new_reviews
            
        except Exception as e:
            print(f"❌ Google Play Store bağlantı hatası: {e}")
            return []
    
    def get_app_store_reviews(self) -> List[Dict]:
        """App Store'dan yeni yorumları çek (RSS Feed) - sadece son kontrolden yeni olanları"""
        try:
            if not self.config.APP_STORE_APP_ID:
                print("⚠️  App Store App ID ayarlanmamış")
                return []
            
            # Son kontrol zamanını al
            last_check = self.last_check_times.get('app_store')
            if last_check:
                print(f"📅 App Store son kontrol: {last_check.strftime('%d.%m.%Y %H:%M')}")
            else:
                print("📅 App Store ilk kontrol yapılıyor")
            
            # App Store RSS Feed URL - "all" seçilirse varsayılan olarak "tr" kullan
            country = self.config.APP_STORE_COUNTRY if self.config.APP_STORE_COUNTRY != 'all' else 'tr'
            url = f"https://itunes.apple.com/{country}/rss/customerreviews/id={self.config.APP_STORE_APP_ID}/sortBy=mostRecent/json"
            
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            reviews = []
            newest_date = None
            
            # RSS feed'den yorumları parse et
            if 'feed' in data and 'entry' in data['feed']:
                processed_count = 0
                for entry in data['feed']['entry']:
                    try:
                        review_id = entry['id']['label']
                        review_date = self.parse_date(entry['updated']['label'])
                        
                        # En yeni tarihi takip et
                        if newest_date is None or review_date > newest_date:
                            newest_date = review_date
                        
                        # SADECE son kontrolden daha YENİ olanları al (GÜÇLÜ KORUMA)
                        if last_check and review_date <= last_check:
                            # Bu yorum zaten kontrol edildi, atla
                            continue
                        
                        # Daha önce gönderildi mi kontrol et (İKİNCİL KORUMA)
                        if self.is_review_sent(review_id):
                            print(f"⏭️  ID kontrolü: Daha önce gönderilmiş - {entry['author']['name']['label']}")
                            continue
                        
                        # Maximum limit kontrolü
                        if processed_count >= self.config.MAX_REVIEWS_PER_CHECK:
                            print(f"📝 App Store: {self.config.MAX_REVIEWS_PER_CHECK} yeni yorum limiti doldu, durduruluyor")
                            break
                        
                        review = {
                            'source': 'App Store',
                            'review_id': review_id,
                            'author': entry['author']['name']['label'],
                            'rating': int(entry['im:rating']['label']),
                            'title': entry['title']['label'],
                            'content': entry['content']['label'],
                            'date': review_date,
                            'version': entry['im:version']['label'],
                            'url': f"https://apps.apple.com/tr/app/id{self.config.APP_STORE_APP_ID}"
                        }
                        reviews.append(review)
                        processed_count += 1
                        print(f"🆕 Yeni App Store yorumu bulundu: {entry['author']['name']['label']} - {review_date.strftime('%d.%m.%Y %H:%M')}")
                        
                    except (KeyError, ValueError) as e:
                        print(f"⚠️  App Store yorum parse hatası: {e}")
                        continue
            
            # En yeni tarihi güncelle (yorum bulunsa da bulunmasa da)
            # ÖNEMLİ: Yorum gönderilsin ya da gönderilmesin, son kontrol zamanını güncelle
            if newest_date:
                self.update_last_check_time('app_store', newest_date)
            elif last_check:
                # Eğer hiç yeni yorum yoksa, şu anki zamanı kaydet
                self.update_last_check_time('app_store', datetime.now())
            
            if reviews:
                print(f"✅ App Store'da {len(reviews)} gerçekten yeni yorum bulundu")
            else:
                print("📭 App Store'da yeni yorum bulunmadı (tüm yorumlar son kontrolden eski)")
            return reviews
            
        except requests.RequestException as e:
            print(f"❌ App Store RSS Feed bağlantı hatası: {e}")
            return []
        except Exception as e:
            print(f"❌ App Store yorumları çekilirken hata: {e}")
            return []
    
    def format_review_for_slack(self, review: Dict) -> str:
        """Yorumu Slack için formatla"""
        # Yıldız emojisi oluştur
        stars = "⭐" * review['rating'] + "☆" * (5 - review['rating'])
        
        # Tarih formatla
        if isinstance(review['date'], str):
            date_str = review['date']
        else:
            date_str = review['date'].strftime("%d.%m.%Y %H:%M")
        
        # Platform emojisi
        platform_emoji = "🍎" if review['source'] == 'App Store' else "🤖"
        
        # Slack mesajı oluştur
        message = f"""
{platform_emoji} **Yeni {review['source']} Yorumu**

**{review['author']}** - {stars} ({review['rating']}/5)
📅 {date_str}

{review['content'][:500]}{'...' if len(review['content']) > 500 else ''}

🔗 [Yorumu Görüntüle]({review['url']})
"""
        return message.strip()
    
    def send_to_slack(self, message: str) -> bool:
        """Slack'e mesaj gönder"""
        try:
            payload = {
                "channel": self.config.SLACK_CHANNEL,
                "text": message,
                "username": "App Review Monitor",
                "icon_emoji": ":star:"
            }
            
            response = requests.post(
                self.config.SLACK_WEBHOOK_URL,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"✅ Slack'e mesaj gönderildi: {datetime.now()}")
                return True
            else:
                print(f"❌ Slack mesajı gönderilemedi: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Slack mesajı gönderilirken hata: {e}")
            return False
    
    def check_and_send_reviews(self):
        """Yorumları kontrol et ve Slack'e gönder"""
        print(f"🔍 Yorumlar kontrol ediliyor: {datetime.now().strftime('%H:%M:%S')}")
        
        # Google Play Store kontrol
        print("📱 Play Store tarafında güncel yorum buluması için istek atılıyor...")
        google_reviews = self.get_google_play_reviews()
        if google_reviews:
            print(f"✅ Play Store tarafında {len(google_reviews)} güncel yorum bulundu")
            # Kendi içinde tarihe göre sırala (en yeni önce)
            google_reviews.sort(key=lambda x: self.parse_date(x['date']), reverse=True)
        else:
            print("📭 Play Store tarafında güncel bir yorum bulunamadı")
        
        # App Store kontrol
        print("🍎 App Store tarafında güncel yorum buluması için istek atılıyor...")
        app_store_reviews = self.get_app_store_reviews()
        if app_store_reviews:
            print(f"✅ App Store tarafında {len(app_store_reviews)} güncel yorum bulundu")
            # Kendi içinde tarihe göre sırala (en yeni önce)
            app_store_reviews.sort(key=lambda x: self.parse_date(x['date']), reverse=True)
        else:
            print("📭 App Store tarafında güncel bir yorum bulunamadı")
        
        # Tüm yeni yorumları birleştir
        all_reviews = google_reviews + app_store_reviews
        
        # Sadece yeni yorum varsa Slack'e gönder
        if all_reviews:
            total_count = len(all_reviews)
            google_count = len(google_reviews)
            app_store_count = len(app_store_reviews)
            
            print(f"🚀 Toplam {total_count} yeni yorum bulundu (Play Store: {google_count}, App Store: {app_store_count})")
            print("📤 Bulunan güncel yorumlar Slack üzerinden paylaşılıyor...")
            
            # Son karışık sıralama (tüm platformlar karışık en yeni önce)
            all_reviews.sort(key=lambda x: self.parse_date(x['date']), reverse=True)
            
            sent_count = 0
            for review in all_reviews:
                try:
                    message = self.format_review_for_slack(review)
                    if self.send_to_slack(message):
                        # Başarıyla gönderildi, işaretle
                        self.mark_review_as_sent(review['review_id'])
                        sent_count += 1
                        print(f"✅ {review['source']}: {review['author']} - {review['rating']}/5 → Slack'e gönderildi")
                        time.sleep(1)  # Rate limiting için kısa bekleme
                    else:
                        print(f"❌ Slack'e gönderilemedi: {review['review_id']}")
                except Exception as e:
                    print(f"❌ Yorum gönderilirken hata: {e}")
            
            if sent_count > 0:
                print(f"🎉 Play Store ve App Store tarafında bulunan {sent_count} güncel yorum başarıyla Slack üzerinden paylaşıldı")
            else:
                print("⚠️ Yorumlar bulundu ancak Slack'e gönderilemedi")
        else:
            print("💤 Play Store ve App Store tarafında güncel yorum bulunamadı - Slack'e mesaj gönderilmedi")
            print("⏰ Bir sonraki kontrol: 60 dakika sonra")
    
    def run_initial_setup(self):
        """İlk kurulum - mevcut yorumları çek ama gönderme"""
        print("🚀 İlk kurulum başlatılıyor...")
        
        # Google Play Store'dan son yorumu çek
        google_reviews = self.get_google_play_reviews()
        if google_reviews:
            self.last_google_play_review_id = google_reviews[0]['review_id']
            print(f"✅ Google Play Store son yorum ID: {self.last_google_play_review_id}")
        
        # App Store'dan son yorumu çek
        app_store_reviews = self.get_app_store_reviews()
        if app_store_reviews:
            self.last_app_store_review_id = app_store_reviews[0]['review_id']
            print(f"✅ App Store son yorum ID: {self.last_app_store_review_id}")
        
        print("🎯 İlk kurulum tamamlandı. Artık sadece yeni yorumlar takip edilecek.")
