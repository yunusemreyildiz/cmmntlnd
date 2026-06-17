"""SQLite veri katmanı.

Tüm yorumları ve günlük uygulama istatistiklerini (ortalama rating, oy sayısı,
mağaza sıralaması) kalıcı olarak saklar. Bu sayede:
  - Aynı yorum Slack'e bir kez gönderilir (sent_to_slack bayrağı ile spam biter).
  - Geçmiş yorumlar kaybolmaz; export DB'den anında çekilir.
  - Günlük rating/ranking trendi takip edilebilir.
"""

import os
import sqlite3
import threading
from datetime import datetime
from typing import Dict, List, Optional, Set

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(_BASE_DIR, 'reviews.db')


def _to_iso(value) -> Optional[str]:
    """datetime/str değeri ISO string'e çevir (DB'de tutarlı saklama)."""
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)
        return value.isoformat()
    return str(value)


class Database:
    """Thread-safe SQLite sarmalayıcı.

    Her işlem için kısa ömürlü bir bağlantı açılır; bu sayede monitor thread'i,
    günlük özet job'ı ve Flask istekleri aynı dosyaya güvenle erişebilir.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reviews (
                    review_id     TEXT PRIMARY KEY,
                    platform      TEXT,
                    source        TEXT,
                    author        TEXT,
                    rating        INTEGER,
                    title         TEXT,
                    content       TEXT,
                    review_date   TEXT,
                    version       TEXT,
                    url           TEXT,
                    country       TEXT,
                    sent_to_slack INTEGER NOT NULL DEFAULT 0,
                    fetched_at    TEXT,
                    sent_at       TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(review_date)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reviews_platform ON reviews(platform)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reviews_sent ON reviews(sent_to_slack)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_stats (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform      TEXT NOT NULL,
                    captured_date TEXT NOT NULL,
                    avg_rating    REAL,
                    rating_count  INTEGER,
                    rank_category TEXT,
                    rank_position INTEGER,
                    captured_at   TEXT,
                    UNIQUE(platform, captured_date)
                )
                """
            )

    # ---- reviews -------------------------------------------------------

    def upsert_review(self, review: Dict, sent: Optional[bool] = None) -> None:
        """Yorumu ekle veya güncelle. sent=None ise gönderim durumu korunur."""
        platform = review.get('platform')
        if not platform:
            source = review.get('source')
            if source == 'App Store':
                platform = 'iOS'
            elif source == 'Google Play':
                platform = 'Android'
            else:
                platform = ''
        review_id = str(review.get('review_id', '')).strip()
        if not review_id:
            return

        fields = {
            'review_id': review_id,
            'platform': platform,
            'source': review.get('source', ''),
            'author': review.get('author', ''),
            'rating': review.get('rating'),
            'title': review.get('title', ''),
            'content': review.get('content', ''),
            'review_date': _to_iso(review.get('date')),
            'version': review.get('version', ''),
            'url': review.get('url', ''),
            'country': review.get('country', ''),
            'fetched_at': datetime.now().isoformat(),
        }

        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT review_id FROM reviews WHERE review_id = ?", (review_id,)
            ).fetchone()

            if existing is None:
                fields['sent_to_slack'] = 1 if sent else 0
                fields['sent_at'] = datetime.now().isoformat() if sent else None
                cols = ', '.join(fields.keys())
                placeholders = ', '.join('?' for _ in fields)
                conn.execute(
                    f"INSERT INTO reviews ({cols}) VALUES ({placeholders})",
                    tuple(fields.values()),
                )
            else:
                update_fields = {k: v for k, v in fields.items() if k != 'review_id'}
                if sent is not None:
                    update_fields['sent_to_slack'] = 1 if sent else 0
                    if sent:
                        update_fields['sent_at'] = datetime.now().isoformat()
                set_clause = ', '.join(f"{k} = ?" for k in update_fields)
                conn.execute(
                    f"UPDATE reviews SET {set_clause} WHERE review_id = ?",
                    (*update_fields.values(), review_id),
                )

    def is_sent(self, review_id: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT sent_to_slack FROM reviews WHERE review_id = ?",
                (str(review_id),),
            ).fetchone()
        return bool(row and row['sent_to_slack'])

    def mark_sent(self, review_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE reviews SET sent_to_slack = 1, sent_at = ? WHERE review_id = ?",
                (datetime.now().isoformat(), str(review_id)),
            )

    def get_sent_ids(self) -> Set[str]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT review_id FROM reviews WHERE sent_to_slack = 1"
            ).fetchall()
        return {row['review_id'] for row in rows}

    def get_reviews_since(
        self, start_date: datetime, platforms: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Belirtilen tarihten sonraki yorumları DB'den getir (export için)."""
        query = "SELECT * FROM reviews WHERE review_date >= ?"
        params: List = [_to_iso(start_date)]

        if platforms:
            source_map = {'app_store': 'App Store', 'google_play': 'Google Play'}
            sources = [source_map[p] for p in platforms if p in source_map]
            if sources:
                query += " AND source IN (%s)" % ','.join('?' for _ in sources)
                params.extend(sources)

        query += " ORDER BY review_date DESC"

        with self._lock, self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_review(row) for row in rows]

    def query_reviews(
        self,
        platform: Optional[str] = None,
        rating: Optional[int] = None,
        search: Optional[str] = None,
        sent: Optional[bool] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> Dict:
        """Filtreli + sayfalı yorum sorgusu. {'total': N, 'items': [...]} döner."""
        where = []
        params: List = []

        if platform in ('iOS', 'Android'):
            where.append("platform = ?")
            params.append(platform)
        if rating in (1, 2, 3, 4, 5):
            where.append("rating = ?")
            params.append(rating)
        if sent is not None:
            where.append("sent_to_slack = ?")
            params.append(1 if sent else 0)
        if search:
            where.append("(content LIKE ? OR author LIKE ? OR title LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])

        # Migration kayıtları (içeriksiz, platformsuz "gönderildi" işaretleri) listede gösterilmesin
        where.append("(content != '' OR platform != '')")

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        with self._lock, self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM reviews{where_sql}", params
            ).fetchone()['c']
            rows = conn.execute(
                f"""
                SELECT * FROM reviews{where_sql}
                ORDER BY review_date DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()

        items = []
        for row in rows:
            review = self._row_to_review(row)
            date_val = review['date']
            if isinstance(date_val, datetime):
                review['date'] = date_val.strftime('%Y-%m-%d %H:%M')
            review['sent_to_slack'] = bool(row['sent_to_slack'])
            items.append(review)

        return {'total': int(total), 'items': items}

    def count_reviews(self, platform: Optional[str] = None) -> int:
        with self._lock, self._connect() as conn:
            if platform:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM reviews WHERE platform = ?", (platform,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM reviews").fetchone()
        return int(row['c']) if row else 0

    @staticmethod
    def _row_to_review(row: sqlite3.Row) -> Dict:
        date_val = row['review_date']
        parsed_date = date_val
        if date_val:
            try:
                parsed_date = datetime.fromisoformat(date_val)
            except (ValueError, TypeError):
                parsed_date = date_val
        return {
            'review_id': row['review_id'],
            'platform': row['platform'],
            'source': row['source'],
            'author': row['author'],
            'rating': row['rating'],
            'title': row['title'],
            'content': row['content'],
            'date': parsed_date,
            'version': row['version'],
            'url': row['url'],
            'country': row['country'],
        }

    # ---- app_stats -----------------------------------------------------

    def save_stats(
        self,
        platform: str,
        avg_rating: Optional[float],
        rating_count: Optional[int],
        rank_category: Optional[str] = None,
        rank_position: Optional[int] = None,
        captured_date: Optional[str] = None,
    ) -> None:
        """Günlük istatistik snapshot'ı kaydet (aynı gün varsa günceller)."""
        captured_date = captured_date or datetime.now().strftime('%Y-%m-%d')
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_stats
                    (platform, captured_date, avg_rating, rating_count,
                     rank_category, rank_position, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, captured_date) DO UPDATE SET
                    avg_rating    = excluded.avg_rating,
                    rating_count  = excluded.rating_count,
                    rank_category = excluded.rank_category,
                    rank_position = excluded.rank_position,
                    captured_at   = excluded.captured_at
                """,
                (
                    platform, captured_date, avg_rating, rating_count,
                    rank_category, rank_position, datetime.now().isoformat(),
                ),
            )

    def get_latest_stats(self, platform: str) -> Optional[Dict]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM app_stats WHERE platform = ?
                ORDER BY captured_date DESC LIMIT 1
                """,
                (platform,),
            ).fetchone()
        return dict(row) if row else None

    def get_previous_stats(self, platform: str, before_date: str) -> Optional[Dict]:
        """Verilen günden önceki en son snapshot (trend karşılaştırması için)."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM app_stats WHERE platform = ? AND captured_date < ?
                ORDER BY captured_date DESC LIMIT 1
                """,
                (platform, before_date),
            ).fetchone()
        return dict(row) if row else None
