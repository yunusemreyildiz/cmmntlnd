import json
import os
import re
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import requests
from google_play_scraper import reviews, Sort
from config import Config
from database import Database
from dateutil import parser as date_parser

# Proje kökü (cwd'ye bağlı kalma — yanlış dizine yazılınca her döngüde aynı yorumlar Slack'e gider)
_DATA_DIR = os.path.dirname(os.path.abspath(__file__))


class AppReviewMonitor:
    def __init__(self):
        self.config = Config()
        self.config.validate()
        self.db = Database()
        self.sent_reviews_file = os.path.join(_DATA_DIR, 'sent_reviews.json')
        self.sent_reviews = self.load_sent_reviews()
        self.last_check_file = os.path.join(_DATA_DIR, 'last_check.json')
        self.last_check_times = self.load_last_check_times()
        self._migrate_legacy_sent_reviews()

    def _migrate_legacy_sent_reviews(self) -> None:
        """Eski sent_reviews.json'daki ID'leri DB'ye taşı (tek seferlik, idempotent).

        İçerik bilgisi olmadığı için bu ID'ler gönderilmiş işaretlenir; böylece
        DB'ye geçişte eski yorumlar Slack'e tekrar düşmez.
        """
        try:
            legacy_ids = self.load_sent_reviews()
            if not legacy_ids:
                return
            existing_sent = self.db.get_sent_ids()
            new_ids = legacy_ids - existing_sent
            for review_id in new_ids:
                self.db.upsert_review(
                    {
                        'review_id': review_id,
                        'platform': '',
                        'source': '',
                        'rating': None,
                    },
                    sent=True,
                )
            if new_ids:
                print(f"🗃️  {len(new_ids)} eski gönderim kaydı DB'ye taşındı")
        except Exception as e:
            print(f"⚠️  Eski sent_reviews taşıma hatası: {e}")
    
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
    
    def is_review_newer_than_last_check(self, review_date, last_check_date):
        """Yorum tarihi son kaydedilen kontrol zamanından *kesin* daha mı yeni (timezone güvenli).

        NOT: last_check'e 5 dk geri tolerans vermek, last_check ile aynı saniyedeki yorumların
        her turda yeniden 'yeni' sayılmasına yol açıyordu (sent_reviews yazılamazsa Slack spam).
        """
        if not last_check_date:
            return True

        review_naive = review_date.replace(tzinfo=None) if review_date.tzinfo else review_date
        last_check_naive = last_check_date.replace(tzinfo=None) if last_check_date.tzinfo else last_check_date

        return review_naive > last_check_naive

    @staticmethod
    def _normalize_apple_review_id(label: str) -> str:
        """RSS id/label bazen tam URL; kararlı kısa anahtar üret."""
        s = (label or '').strip()
        if 'reviews/' in s:
            tail = s.split('reviews/')[-1].split('?')[0].strip('/')
            if tail:
                return tail
        return s

    @staticmethod
    def _apple_rss_entries(feed: dict) -> List[Dict]:
        """Apple RSS entry alanını listeye çevir; tek entry dict gelince anahtarlar üzerinde dönme hatasını önle."""
        raw = feed.get('entry')
        if raw is None:
            return []
        if isinstance(raw, dict):
            candidates = [raw]
        elif isinstance(raw, list):
            candidates = raw
        else:
            return []
        return [e for e in candidates if isinstance(e, dict) and 'im:rating' in e]

    def _app_store_countries_to_try(self) -> List[str]:
        """Ülke feed'i boş dönerse (ör. us) tr yedeğine düş."""
        primary = self.config.APP_STORE_COUNTRY if self.config.APP_STORE_COUNTRY != 'all' else 'tr'
        countries = [primary]
        if primary != 'tr':
            countries.append('tr')
        return countries

    def _app_store_rss_url(self, country: str, page: int = 1) -> str:
        # Canlı izleme: sortBy=mostRecent (sayfa 1 için page parametresi yok)
        base = (
            f"https://itunes.apple.com/{country}/rss/customerreviews/"
            f"id={self.config.APP_STORE_APP_ID}/sortBy=mostRecent"
        )
        if page <= 1:
            return f"{base}/json"
        return f"{base}/page={page}/json"

    def _app_store_rss_url_export(self, country: str, page: int = 1) -> str:
        # Export yedeği: sortby=mostrecent ile 10 sayfaya kadar ~250 yorum
        return (
            f"https://itunes.apple.com/{country}/rss/customerreviews/"
            f"page={page}/id={self.config.APP_STORE_APP_ID}/sortby=mostrecent/json"
        )

    def _fetch_app_store_rss_page(self, page: int, export_mode: bool = False) -> tuple:
        """Belirtilen sayfadaki App Store yorum entry'lerini çek (ülke yedeği ile). (entries, country) döner."""
        last_error = None
        primary = self._app_store_countries_to_try()[0]
        for country in self._app_store_countries_to_try():
            try:
                url = (
                    self._app_store_rss_url_export(country, page)
                    if export_mode
                    else self._app_store_rss_url(country, page)
                )
                response = requests.get(
                    url,
                    timeout=15,
                    headers={
                        'User-Agent': (
                            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                        ),
                        'Accept': 'application/json',
                    },
                )
                if response.status_code == 400:
                    return [], country
                response.raise_for_status()
                entries = self._apple_rss_entries(response.json().get('feed', {}))
                if entries:
                    if country != primary:
                        print(f"ℹ️  App Store RSS: {primary} boş, {country} kullanıldı")
                    return entries, country
                if page == 1:
                    print(f"📭 App Store RSS ({country}) sayfa {page}: yorum entry yok")
                    continue
                return [], country
            except requests.RequestException as e:
                last_error = e
                print(f"❌ App Store RSS ({country}) sayfa {page} bağlantı hatası: {e}")
                continue
        if last_error:
            raise last_error
        return [], primary

    def _parse_app_store_entry(self, entry: Dict, country: str) -> Optional[Dict]:
        """Tek bir App Store RSS entry'sini review dict'e çevir."""
        try:
            review_date = self.parse_date(entry['updated']['label'])
            return {
                'source': 'App Store',
                'platform': 'iOS',
                'review_id': self._normalize_apple_review_id(entry['id']['label']),
                'author': entry['author']['name']['label'],
                'rating': int(entry['im:rating']['label']),
                'title': entry['title']['label'],
                'content': entry['content']['label'],
                'date': review_date,
                'version': entry['im:version']['label'],
                'url': f"https://apps.apple.com/{country}/app/id{self.config.APP_STORE_APP_ID}",
                'country': country,
            }
        except (KeyError, ValueError, TypeError) as e:
            print(f"⚠️  App Store yorum parse hatası: {e}")
            return None

    def _app_store_web_api_headers(self, country: str) -> Dict[str, str]:
        app_id = self.config.APP_STORE_APP_ID
        landing = f'https://apps.apple.com/{country}/app/id{app_id}'
        return {
            'Accept': 'application/json',
            'Authorization': 'Bearer ',
            'Origin': 'https://apps.apple.com',
            'Referer': landing,
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ),
        }

    def _fetch_app_store_web_api_batch(
        self, country: str, offset: int = 0,
    ) -> Tuple[List[Dict], Optional[int]]:
        """Apple web API'den 20'şer yorum çek. (kayıtlar, sonraki_offset) döner."""
        app_id = self.config.APP_STORE_APP_ID
        url = (
            f'https://apps.apple.com/api/apps/v1/catalog/{country}/apps/{app_id}/reviews'
        )
        params = {
            'l': 'en-GB',
            'offset': offset,
            'limit': 20,
            'platform': 'web',
            'additionalPlatforms': 'appletv,ipad,iphone,mac',
            'sort': 'recent',
        }
        headers = self._app_store_web_api_headers(country)
        response = None
        for attempt in range(6):
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 429:
                wait = 15 * (attempt + 1)
                print(f'⏳ App Store API rate limit (429), {wait}s bekleniyor...')
                time.sleep(wait)
                continue
            response.raise_for_status()
            break
        else:
            raise requests.RequestException(
                f'App Store API rate limit aşıldı (offset={offset})'
            )

        data = response.json()
        items = data.get('data') or []
        next_offset = None
        next_url = data.get('next')
        if next_url:
            match = re.search(r'offset=([0-9]+)', next_url)
            if match:
                next_offset = int(match.group(1))
        return items, next_offset

    def _parse_app_store_api_review(self, item: Dict, country: str) -> Optional[Dict]:
        """Apple web API yanıtındaki tek bir yorumu normalize et."""
        try:
            attrs = item.get('attributes') or {}
            review_date = self.parse_date(attrs.get('date', ''))
            return {
                'source': 'App Store',
                'platform': 'iOS',
                'review_id': str(item.get('id', '')),
                'author': attrs.get('userName', ''),
                'rating': int(attrs.get('rating', 0)),
                'title': attrs.get('title', ''),
                'content': attrs.get('review', ''),
                'date': review_date,
                'version': attrs.get('appVersion', '') or '',
                'url': f'https://apps.apple.com/{country}/app/id{self.config.APP_STORE_APP_ID}',
                'country': country,
            }
        except (KeyError, ValueError, TypeError) as e:
            print(f'⚠️  App Store API yorum parse hatası: {e}')
            return None

    def _get_app_store_historical_via_web_api(
        self, start_date: datetime,
    ) -> Optional[List[Dict]]:
        """Apple web API ile sayfa sayfa yorum çek (RSS'ten çok daha fazla veri)."""
        country = self._app_store_countries_to_try()[0]
        historical_reviews: List[Dict] = []
        seen_ids: set = set()
        offset = 0
        page = 0
        max_pages = 120
        oldest_review_date = None
        total_fetched = 0

        print(
            f'🍎 App Store Web API pagination: {start_date.strftime("%d.%m.%Y")} '
            f'tarihinden itibaren (20\'şer yorum, rate limit korumalı)'
        )

        while page < max_pages:
            page += 1
            print(f'📄 API sayfa {page} (offset {offset}) çekiliyor...')
            try:
                items, next_offset = self._fetch_app_store_web_api_batch(country, offset)
            except requests.RequestException as e:
                print(f'❌ App Store Web API sayfa {page} hatası: {e}')
                return None if not historical_reviews else historical_reviews

            if not items:
                print(f'📭 API sayfa {page}: yorum yok, durduruluyor')
                break

            total_fetched += len(items)
            page_oldest = None
            page_added = 0

            for item in items:
                parsed = self._parse_app_store_api_review(item, country)
                if not parsed:
                    continue

                review_date = parsed['date']
                review_id = parsed['review_id']

                if page_oldest is None or review_date < page_oldest:
                    page_oldest = review_date
                if oldest_review_date is None or review_date < oldest_review_date:
                    oldest_review_date = review_date

                if review_date >= start_date and review_id not in seen_ids:
                    seen_ids.add(review_id)
                    historical_reviews.append(parsed)
                    page_added += 1

            print(
                f'✅ API sayfa {page}: +{page_added} yeni yorum '
                f'(bu sayfada {len(items)} kayıt, toplam {len(historical_reviews)})'
            )

            if page_oldest and page_oldest < start_date:
                print(
                    f'📅 En eski yorum ({page_oldest.strftime("%d.%m.%Y")}) '
                    f'hedef tarihten önce — pagination durduruluyor'
                )
                break

            if next_offset is None:
                print('📭 Sonraki sayfa yok — API pagination tamamlandı')
                break

            offset = next_offset
            time.sleep(1.2)

        in_range = len(historical_reviews)
        print(
            f'🎉 App Store Web API tamamlandı: {in_range} yorum (aralıkta), '
            f'{total_fetched} ham kayıt tarandı, {len(seen_ids)} benzersiz ID'
        )
        if oldest_review_date:
            print(
                f'📅 API tarih aralığı: {oldest_review_date.strftime("%d.%m.%Y")} - '
                f'{datetime.now().strftime("%d.%m.%Y")}'
            )
        if total_fetched >= 1000:
            print(
                'ℹ️  Apple public API tüm erişilebilir yorumları döndürmüş olabilir; '
                'App Store Connect\'teki toplamdan düşükse bu Apple\'ın API limitidir.'
            )
        return historical_reviews
    
    def load_sent_reviews(self):
        """Daha önce gönderilen yorumları yükle (DB birincil, eski JSON ile birleştir)"""
        ids = set()
        try:
            if os.path.exists(self.sent_reviews_file):
                with open(self.sent_reviews_file, 'r', encoding='utf-8') as f:
                    ids |= set(json.load(f))
        except Exception as e:
            print(f"⚠️  Gönderilen yorumlar (JSON) yüklenemedi: {e}")
        try:
            if getattr(self, 'db', None) is not None:
                ids |= self.db.get_sent_ids()
        except Exception as e:
            print(f"⚠️  Gönderilen yorumlar (DB) yüklenemedi: {e}")
        return ids
    
    def _atomic_write_json(self, final_path: str, data) -> None:
        """Geçici dosyaya yazıp os.replace ile atomik taşı (sent_reviews.json.tmp kalmasını azaltır)."""
        temp_file = f"{final_path}.tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, final_path)

    def save_sent_reviews(self):
        """Gönderilen yorumları disk'e kaydet"""
        try:
            # Önce bellekte limit uygula; sonra diske yaz (aksi halde disk ile bellek uyumsuz kalırdı)
            self.cleanup_old_reviews()
            self._atomic_write_json(self.sent_reviews_file, sorted(self.sent_reviews))
        except OSError as e:
            print(f"❌ Dosya sistemi hatası: {e}")
            print(f"💡 Çözüm: Disk alanını kontrol edin veya dosya izinlerini düzeltin")
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
                
                # Limit aşıldığında set sırası rastgele olabileceğinden deterministik kes (lex sıra)
                old_count = len(self.sent_reviews)
                reviews_list = sorted(self.sent_reviews)
                keep_count = self.config.MAX_STORED_REVIEWS // 2
                self.sent_reviews = set(reviews_list[-keep_count:])
                
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
            data = {}
            for platform, dt in self.last_check_times.items():
                data[platform] = dt.isoformat() if dt else None
            self._atomic_write_json(self.last_check_file, data)
        except OSError as e:
            print(f"❌ Dosya sistemi hatası: {e}")
            print(f"💡 Çözüm: Disk alanını kontrol edin veya dosya izinlerini düzeltin")
        except Exception as e:
            print(f"⚠️  Son kontrol zamanları kaydedilemedi: {e}")
    
    def update_last_check_time(self, platform: str, latest_date: datetime):
        """Platform için son kontrol zamanını güncelle"""
        if not self.last_check_times[platform] or latest_date > self.last_check_times[platform]:
            self.last_check_times[platform] = latest_date
            self.save_last_check_times()
            print(f"📅 {platform} için son kontrol zamanı güncellendi: {latest_date.strftime('%d.%m.%Y %H:%M')}")
    
    def is_review_sent(self, review_id: str) -> bool:
        """Bu yorum daha önce gönderildi mi? (DB birincil kaynak, bellek yedek)"""
        if review_id in self.sent_reviews:
            return True
        return self.db.is_sent(review_id)
    
    def mark_review_as_sent(self, review_id: str):
        """Yorumu gönderildi olarak işaretle (DB + bellek + eski JSON yedeği)"""
        self.sent_reviews.add(review_id)
        self.db.mark_sent(review_id)
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
                    if not self.is_review_newer_than_last_check(review_date, last_check):
                        # Bu yorum zaten kontrol edildi, atla
                        print(f"⏰ Tarih kontrolü: Eski yorum - {review['userName']} ({review_date.strftime('%d.%m.%Y %H:%M')} <= {last_check.strftime('%d.%m.%Y %H:%M')})")
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
            
            # En yeni tarihi güncelle - SADECE feed'den gerçek bir tarih geldiyse
            # ÖNEMLİ: Feed geçici boş döndüğünde datetime.now() ile ilerleme yapma!
            if newest_date:
                self.update_last_check_time('google_play', newest_date)
            
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
            
            entries, country = self._fetch_app_store_rss_page(1)
            reviews = []
            newest_date = None
            processed_count = 0

            for entry in entries:
                parsed = self._parse_app_store_entry(entry, country)
                if not parsed:
                    continue

                review_id = parsed['review_id']
                review_date = parsed['date']

                if newest_date is None or review_date > newest_date:
                    newest_date = review_date

                if not self.is_review_newer_than_last_check(review_date, last_check):
                    print(
                        f"⏰ Tarih kontrolü: Eski yorum - {parsed['author']} "
                        f"({review_date.strftime('%d.%m.%Y %H:%M')} <= {last_check.strftime('%d.%m.%Y %H:%M')})"
                    )
                    continue

                if self.is_review_sent(review_id):
                    print(f"⏭️  ID kontrolü: Daha önce gönderilmiş - {parsed['author']}")
                    continue

                if processed_count >= self.config.MAX_REVIEWS_PER_CHECK:
                    print(f"📝 App Store: {self.config.MAX_REVIEWS_PER_CHECK} yeni yorum limiti doldu, durduruluyor")
                    break

                reviews.append(parsed)
                processed_count += 1
                print(f"🆕 Yeni App Store yorumu bulundu: {parsed['author']} - {review_date.strftime('%d.%m.%Y %H:%M')}")
            
            # En yeni tarihi güncelle - SADECE feed'den gerçek bir tarih geldiyse
            # ÖNEMLİ: Feed geçici boş döndüğünde datetime.now() ile ilerleme yapma!
            # Aksi halde gerçek yorumlar last_check'in arkasında kalır ve hiç gönderilmez.
            if newest_date:
                self.update_last_check_time('app_store', newest_date)
            
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
        # Disk ile birleştir: dışarıdan atanan boş set, bellekteki gönderilmiş id'leri silmesin
        self.sent_reviews |= self.load_sent_reviews()

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
                    # Yorumu (içeriğiyle) DB'ye kaydet — Slack'e gitmese bile geçmişte tutulur
                    self.db.upsert_review(review)
                    if self.is_review_sent(review['review_id']):
                        continue
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
    
    def get_historical_reviews(
        self,
        start_date: datetime,
        platforms: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Belirtilen tarihten itibaren tüm yorumları çek (export için)."""
        print(f"📊 Geçmiş yorumlar çekiliyor: {start_date.strftime('%d.%m.%Y')} - {datetime.now().strftime('%d.%m.%Y')}")

        if platforms is None:
            platforms = ['app_store', 'google_play']

        all_reviews = []

        # iOS önce — uzun Android pagination export'u keserse bile App Store verisi gelsin
        if 'app_store' in platforms:
            try:
                print("🍎 App Store geçmiş yorumları çekiliyor...")
                app_store_reviews = self.get_app_store_historical_reviews(start_date)
                all_reviews.extend(app_store_reviews)
                print(f"✅ App Store: {len(app_store_reviews)} yorum bulundu")
            except Exception as e:
                print(f"❌ App Store geçmiş yorum hatası: {e}")

        if 'google_play' in platforms:
            try:
                print("🤖 Google Play Store geçmiş yorumları çekiliyor...")
                google_reviews = self.get_google_play_historical_reviews(start_date)
                all_reviews.extend(google_reviews)
                print(f"✅ Google Play: {len(google_reviews)} yorum bulundu")
            except Exception as e:
                print(f"❌ Google Play geçmiş yorum hatası: {e}")
        
        # Tarihe göre sırala (en yeni önce)
        all_reviews.sort(key=lambda x: self.parse_date(x['date']), reverse=True)
        
        print(f"🎉 Toplam {len(all_reviews)} geçmiş yorum bulundu")
        return all_reviews
    
    def get_google_play_historical_reviews(self, start_date: datetime) -> List[Dict]:
        """Google Play Store'dan geçmiş yorumları çek (Pagination ile belirtilen tarihe kadar)"""
        try:
            country = self.config.GOOGLE_PLAY_COUNTRY if self.config.GOOGLE_PLAY_COUNTRY != 'all' else 'tr'
            historical_reviews = []
            continuation_token = None
            page_count = 0
            max_pages = 50  # Maksimum 50 sayfa (25,000 yorum)
            oldest_review_date = None
            
            print(f"🤖 Google Play pagination başlatılıyor: {start_date.strftime('%d.%m.%Y')} tarihinden itibaren")
            
            while page_count < max_pages:
                try:
                    page_count += 1
                    print(f"📄 Sayfa {page_count} çekiliyor...")
                    
                    # Google Play reviews API call with continuation token
                    if continuation_token:
                        result, continuation_token = reviews(
                            self.config.GOOGLE_PLAY_APP_ID,
                            lang='tr',
                            country=country,
                            sort=Sort.NEWEST,
                            count=500,  # Her sayfada 500 yorum
                            continuation_token=continuation_token
                        )
                    else:
                        result, continuation_token = reviews(
                            self.config.GOOGLE_PLAY_APP_ID,
                            lang='tr',
                            country=country,
                            sort=Sort.NEWEST,
                            count=500  # İlk sayfa
                        )
                    
                    if not result:
                        print(f"📭 Sayfa {page_count}: Yorum bulunamadı, pagination durduruluyor")
                        break
                    
                    page_reviews = []
                    for review in result:
                        try:
                            review_date = self.parse_date(review['at'])
                            
                            # En eski yorum tarihini takip et
                            if oldest_review_date is None or review_date < oldest_review_date:
                                oldest_review_date = review_date
                            
                            # Sadece belirtilen tarihten sonraki yorumları al
                            if review_date >= start_date:
                                page_reviews.append({
                                    'source': 'Google Play',
                                    'platform': 'Android',
                                    'review_id': review['reviewId'],
                                    'rating': review['score'],
                                    'title': review.get('title', ''),
                                    'content': review['content'],
                                    'author': review['userName'],
                                    'date': review_date,
                                    'version': review.get('appVersion', ''),
                                    'url': f"https://play.google.com/store/apps/details?id={self.config.GOOGLE_PLAY_APP_ID}&reviewId={review['reviewId']}",
                                    'country': self.config.GOOGLE_PLAY_COUNTRY
                                })
                        except Exception as e:
                            print(f"⚠️  Google Play yorum parse hatası: {e}")
                            continue
                    
                    if not page_reviews:
                        print(f"📭 Sayfa {page_count}: Hedef tarih aralığında yorum yok, pagination durduruluyor")
                        break
                    
                    historical_reviews.extend(page_reviews)
                    print(f"✅ Sayfa {page_count}: {len(page_reviews)} yorum eklendi (Toplam: {len(historical_reviews)})")
                    
                    # Eğer en eski yorum hedef tarihten önceyse dur
                    if oldest_review_date and oldest_review_date < start_date:
                        print(f"📅 En eski yorum tarihi ({oldest_review_date.strftime('%d.%m.%Y')}) hedef tarihten önce, pagination durduruluyor")
                        break
                    
                    # Continuation token yoksa daha fazla sayfa yok
                    if not continuation_token:
                        print(f"📭 Continuation token yok, pagination durduruluyor")
                        break
                    
                    time.sleep(2)  # Rate limiting için bekleme
                    
                except Exception as e:
                    print(f"❌ Sayfa {page_count} hatası: {e}")
                    break
            
            print(f"🎉 Google Play pagination tamamlandı: {len(historical_reviews)} yorum toplandı")
            if oldest_review_date:
                print(f"📅 Tarih aralığı: {oldest_review_date.strftime('%d.%m.%Y')} - {datetime.now().strftime('%d.%m.%Y')}")
            
            return historical_reviews
            
        except Exception as e:
            print(f"❌ Google Play Store geçmiş yorum hatası: {e}")
            return []
    
    def get_app_store_historical_reviews(self, start_date: datetime) -> List[Dict]:
        """App Store'dan geçmiş yorumları çek.

        Önce Apple web API (apps.apple.com/api, ~1000+ yorum), başarısız olursa RSS yedeği.
        """
        if not self.config.APP_STORE_APP_ID:
            print("⚠️  App Store App ID ayarlanmamış — export'ta iOS yorumu atlanıyor")
            return []

        api_reviews = self._get_app_store_historical_via_web_api(start_date)
        if api_reviews is not None:
            return api_reviews

        print('⚠️  App Store Web API kullanılamadı — RSS yedeğine düşülüyor (~250 yorum limiti)')
        return self._get_app_store_historical_via_rss(start_date)

    def _get_app_store_historical_via_rss(self, start_date: datetime) -> List[Dict]:
        """App Store RSS yedeği — sayfa sayfa ~50'şer, aralıklı boş sayfalar atlanır."""
        try:
            historical_reviews: List[Dict] = []
            seen_ids: set = set()
            page = 1
            max_pages = 10
            consecutive_empty = 0
            max_consecutive_empty = 4
            oldest_review_date = None
            country = self._app_store_countries_to_try()[0]

            print(
                f"🍎 App Store RSS yedeği: {start_date.strftime('%d.%m.%Y')} "
                f"tarihinden itibaren (sayfa başına ~50 yorum, max ~250)"
            )

            while page <= max_pages:
                print(f"📄 RSS sayfa {page} çekiliyor...")
                try:
                    entries, country = self._fetch_app_store_rss_page(page, export_mode=True)
                except requests.RequestException as e:
                    print(f"❌ Sayfa {page} bağlantı hatası: {e}")
                    break

                if not entries:
                    consecutive_empty += 1
                    print(
                        f"📭 Sayfa {page}: boş ({consecutive_empty}/{max_consecutive_empty} ardışık boş)"
                    )
                    if consecutive_empty >= max_consecutive_empty:
                        print("📭 Ardışık boş sayfa limiti — App Store pagination durduruluyor")
                        break
                    page += 1
                    time.sleep(2)
                    continue

                consecutive_empty = 0
                page_oldest = None
                page_added = 0

                for entry in entries:
                    parsed = self._parse_app_store_entry(entry, country)
                    if not parsed:
                        continue

                    review_date = parsed['date']
                    review_id = parsed['review_id']

                    if page_oldest is None or review_date < page_oldest:
                        page_oldest = review_date
                    if oldest_review_date is None or review_date < oldest_review_date:
                        oldest_review_date = review_date

                    if review_date >= start_date and review_id not in seen_ids:
                        seen_ids.add(review_id)
                        historical_reviews.append(parsed)
                        page_added += 1

                print(
                    f"✅ Sayfa {page}: +{page_added} yeni yorum "
                    f"(bu sayfada {len(entries)} kayıt, toplam {len(historical_reviews)})"
                )

                if page_oldest and page_oldest < start_date:
                    print(
                        f"📅 En eski yorum tarihi ({page_oldest.strftime('%d.%m.%Y')}) "
                        f"hedef tarihten önce, pagination durduruluyor"
                    )
                    break

                page += 1
                time.sleep(2)

            print(f"🎉 App Store pagination tamamlandı: {len(historical_reviews)} benzersiz yorum toplandı")
            if oldest_review_date:
                print(
                    f"📅 Tarih aralığı: {oldest_review_date.strftime('%d.%m.%Y')} - "
                    f"{datetime.now().strftime('%d.%m.%Y')}"
                )

            return historical_reviews

        except Exception as e:
            print(f"❌ App Store geçmiş yorum hatası: {e}")
            return []

    # ===================================================================
    # İstatistikler: ortalama rating + mağaza sıralaması
    # ===================================================================

    def get_app_store_stats(self) -> Dict:
        """iOS ortalama rating, oy sayısı ve kategori sıralamasını çek."""
        stats = {
            'platform': 'iOS',
            'avg_rating': None,
            'rating_count': None,
            'rank_category': None,
            'rank_position': None,
        }
        country = self._app_store_countries_to_try()[0]
        app_id = str(self.config.APP_STORE_APP_ID)

        try:
            lookup = requests.get(
                'https://itunes.apple.com/lookup',
                params={'id': app_id, 'country': country},
                timeout=15,
            ).json()
            results = lookup.get('results') or []
            if results:
                info = results[0]
                stats['avg_rating'] = info.get('averageUserRating')
                stats['rating_count'] = info.get('userRatingCount')
                genre_ids = info.get('genreIds') or []
                genres = info.get('genres') or []
                primary_genre_id = (
                    info.get('primaryGenreId')
                    or (genre_ids[0] if genre_ids else None)
                )
                primary_genre = (
                    info.get('primaryGenreName')
                    or (genres[0] if genres else None)
                )
                if primary_genre_id:
                    rank, total = self._get_app_store_rank(
                        country, app_id, str(primary_genre_id)
                    )
                    if rank:
                        stats['rank_position'] = rank
                        stats['rank_category'] = f"{primary_genre or 'Kategori'} (iPhone)"
        except Exception as e:
            print(f"⚠️  App Store stats hatası: {e}")

        return stats

    def _get_app_store_rank(
        self, country: str, app_id: str, genre_id: str,
    ) -> Tuple[Optional[int], int]:
        """Uygulamanın 'top free' kategori listesindeki sırasını bul (yoksa None)."""
        url = (
            f'https://itunes.apple.com/{country}/rss/topfreeapplications/'
            f'limit=200/genre={genre_id}/json'
        )
        try:
            data = requests.get(url, timeout=15).json()
            entries = data.get('feed', {}).get('entry', [])
            if isinstance(entries, dict):
                entries = [entries]
            for idx, entry in enumerate(entries, 1):
                entry_id = (
                    entry.get('id', {}).get('attributes', {}).get('im:id')
                )
                if str(entry_id) == app_id:
                    return idx, len(entries)
            return None, len(entries)
        except Exception as e:
            print(f"⚠️  App Store ranking hatası: {e}")
            return None, 0

    def get_google_play_stats(self) -> Dict:
        """Android ortalama rating ve oy sayısını çek (ranking public API'de yok)."""
        stats = {
            'platform': 'Android',
            'avg_rating': None,
            'rating_count': None,
            'rank_category': None,
            'rank_position': None,
        }
        try:
            from google_play_scraper import app as gp_app

            country = (
                self.config.GOOGLE_PLAY_COUNTRY
                if self.config.GOOGLE_PLAY_COUNTRY != 'all'
                else 'tr'
            )
            info = gp_app(
                self.config.GOOGLE_PLAY_APP_ID, lang='tr', country=country
            )
            stats['avg_rating'] = info.get('score')
            stats['rating_count'] = info.get('ratings')
        except Exception as e:
            print(f"⚠️  Google Play stats hatası: {e}")
        return stats

    def collect_and_store_stats(self) -> Dict[str, Dict]:
        """iOS + Android istatistiklerini çek ve DB'ye günlük snapshot olarak yaz."""
        print("📊 Uygulama istatistikleri toplanıyor (rating + ranking)...")
        ios = self.get_app_store_stats()
        android = self.get_google_play_stats()

        for stats in (ios, android):
            try:
                self.db.save_stats(
                    platform=stats['platform'],
                    avg_rating=stats['avg_rating'],
                    rating_count=stats['rating_count'],
                    rank_category=stats['rank_category'],
                    rank_position=stats['rank_position'],
                )
            except Exception as e:
                print(f"⚠️  {stats['platform']} stats DB kaydı hatası: {e}")

        return {'iOS': ios, 'Android': android}

    def _format_stat_block(self, stats: Dict) -> List[str]:
        """Tek platform için Slack özet satırları (girintisiz, düzgün hizalı)."""
        emoji = '🍎' if stats['platform'] == 'iOS' else '🤖'
        avg = stats.get('avg_rating')
        count = stats.get('rating_count')

        avg_str = f"{avg:.2f}" if isinstance(avg, (int, float)) else "—"
        count_str = f"{int(count):,}".replace(',', '.') if count else "—"

        # Önceki günün verisini bir kez al (rating + sıralama trendi için)
        prev = None
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            prev = self.db.get_previous_stats(stats['platform'], today)
        except Exception:
            prev = None

        # Rating trendi (düne göre) — değişim olmasa bile göster.
        # Trend, ekranda gösterilen 2 ondalıklı puanlara göre hesaplanır ki
        # gösterim 4.53 -> 4.54 arttığında "sabit" değil artış görünsün.
        rating_trend = ""
        if prev and prev.get('avg_rating') is not None and isinstance(avg, (int, float)):
            delta = round(round(avg, 2) - round(prev['avg_rating'], 2), 2)
            if delta > 0:
                rating_trend = f"  (🟢 +{delta:.2f} vs dün)"
            elif delta < 0:
                rating_trend = f"  (🔴 {delta:.2f} vs dün)"
            else:
                rating_trend = "  (➡️ sabit)"

        block = [
            f"{emoji} *{stats['platform']}*",
            f"⭐ Puan: *{avg_str}*{rating_trend}  ·  {count_str} oy",
        ]
        return block

    def send_daily_summary(self) -> bool:
        """Günlük istatistik özetini topla, DB'ye yaz ve Slack'e gönder."""
        stats = self.collect_and_store_stats()

        date_str = datetime.now().strftime('%d.%m.%Y')

        lines = [f"📊 *Günlük Uygulama Özeti* — {date_str}", ""]
        lines += self._format_stat_block(stats['iOS'])
        lines.append("")
        lines += self._format_stat_block(stats['Android'])
        message = "\n".join(lines)

        print("📤 Günlük özet Slack'e gönderiliyor...")
        return self.send_to_slack(message)

    # ===================================================================
    # Backfill: tüm geçmişi DB'ye doldur
    # ===================================================================

    def backfill_database(
        self, start_date: Optional[datetime] = None,
        platforms: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """Geçmiş yorumları çekip DB'ye yaz (Slack'e göndermeden).

        start_date None ise erişilebilen tüm geçmiş çekilir.
        """
        if start_date is None:
            start_date = datetime(2008, 1, 1)
        if platforms is None:
            platforms = ['app_store', 'google_play']

        print(f"🗃️  Backfill başlıyor (platformlar={platforms})...")
        reviews_data = self.get_historical_reviews(start_date, platforms=platforms)

        written = 0
        for review in reviews_data:
            try:
                # Backfill geçmiş arşividir; bu yorumlar Slack'e ASLA gönderilmemeli.
                # sent=True işaretleyerek tekrar bildirim gitmesini kesin olarak engelliyoruz.
                self.db.upsert_review(review, sent=True)
                written += 1
            except Exception as e:
                print(f"⚠️  Backfill kayıt hatası: {e}")

        ios = sum(1 for r in reviews_data if r.get('source') == 'App Store')
        android = sum(1 for r in reviews_data if r.get('source') == 'Google Play')
        print(
            f"✅ Backfill tamamlandı: {written} kayıt DB'ye yazıldı "
            f"(iOS {ios}, Android {android})"
        )
        return {'total': written, 'ios': ios, 'android': android}