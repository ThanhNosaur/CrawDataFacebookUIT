# -*- coding: utf-8 -*-
"""
=============================================================================
Fallback Scraper - Dùng khi facebook-scraper bị block
=============================================================================
Phương pháp: Dùng Facebook Mobile site (mbasic.facebook.com) + requests
Facebook mobile site đơn giản hơn, ít bị chặn hơn.

KHÔNG cần đăng nhập - chỉ lấy bài viết PUBLIC.
=============================================================================
"""

import json
import csv
import time
import random
import re
import sys
import io
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, quote

import requests
from bs4 import BeautifulSoup

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

try:
    from fake_useragent import UserAgent
    ua_gen = UserAgent()
except ImportError:
    ua_gen = None

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "fallback_scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

BASE_URL = "https://mbasic.facebook.com"

PAGES = ["UIT.Fanpage", "UITconfess"]
DAYS_BACK = 14
MIN_DELAY = 4
MAX_DELAY = 10
MAX_POSTS_PER_PAGE = 200

# User agents cho mobile
MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 12; SM-A525F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
]


def get_session() -> requests.Session:
    """Tạo session với headers giả lập trình duyệt mobile."""
    session = requests.Session()
    ua = random.choice(MOBILE_USER_AGENTS)
    session.headers.update({
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    })
    return session


def random_delay():
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    time.sleep(delay)


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def parse_relative_time(time_str: str) -> datetime | None:
    """Parse thời gian tương đối từ Facebook (VD: '2 giờ', '3 ngày')."""
    if not time_str:
        return None
    
    now = datetime.now(timezone.utc)
    time_str = time_str.lower().strip()
    
    # Pattern: "X hrs", "X mins", "X days", etc.
    patterns = [
        (r"(\d+)\s*(phút|mins?|minutes?)", "minutes"),
        (r"(\d+)\s*(giờ|hrs?|hours?)", "hours"),
        (r"(\d+)\s*(ngày|days?)", "days"),
        (r"(\d+)\s*(tuần|weeks?)", "weeks"),
        (r"just now|vừa xong", "now"),
        (r"yesterday|hôm qua", "yesterday"),
    ]
    
    for pattern, unit in patterns:
        match = re.search(pattern, time_str)
        if match:
            if unit == "now":
                return now
            if unit == "yesterday":
                return now - timedelta(days=1)
            value = int(match.group(1))
            if unit == "minutes":
                return now - timedelta(minutes=value)
            elif unit == "hours":
                return now - timedelta(hours=value)
            elif unit == "days":
                return now - timedelta(days=value)
            elif unit == "weeks":
                return now - timedelta(weeks=value)
    
    # Thử parse date format: "October 10", "10 tháng 10", etc.
    try:
        # Thử nhiều format
        for fmt in ["%B %d, %Y", "%B %d", "%d %B %Y", "%d %B", "%Y-%m-%d"]:
            try:
                dt = datetime.strptime(time_str, fmt)
                if dt.year == 1900:  # Nếu không có năm
                    dt = dt.replace(year=now.year)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    except Exception:
        pass
    
    return None


def scrape_mbasic_page(page_id: str, cutoff_date: datetime) -> list[dict]:
    """Crawl page từ mbasic.facebook.com."""
    session = get_session()
    posts = []
    url = f"{BASE_URL}/{page_id}"
    
    logger.info(f"🔍 Crawl (mbasic): {page_id}")
    logger.info(f"   URL: {url}")
    
    page_num = 0
    max_pages = 30
    
    while url and page_num < max_pages and len(posts) < MAX_POSTS_PER_PAGE:
        page_num += 1
        logger.info(f"   📄 Trang {page_num}...")
        
        try:
            random_delay()
            resp = session.get(url, timeout=30)
            
            if resp.status_code == 404:
                logger.error(f"   ❌ Page không tồn tại: {page_id}")
                break
            
            if resp.status_code != 200:
                logger.warning(f"   ⚠️ HTTP {resp.status_code}")
                if resp.status_code == 429:
                    logger.warning("   ⏳ Rate limited! Chờ 60s...")
                    time.sleep(60)
                    continue
                break
            
            soup = BeautifulSoup(resp.text, "lxml")
            
            # Tìm các bài viết trên mbasic
            # Mbasic Facebook thường dùng div với class cụ thể
            articles = soup.find_all("article") or soup.find_all("div", {"role": "article"})
            
            if not articles:
                # Fallback: tìm div chứa bài viết
                # mbasic thường có structure: div#structured_composer_async_container
                # hoặc div với data-ft attribute
                articles = soup.find_all("div", attrs={"data-ft": True})
            
            if not articles:
                # Thêm một fallback nữa cho mbasic
                story_divs = soup.find_all("div", class_=re.compile(r"(story|post|feed)"))
                if story_divs:
                    articles = story_divs
            
            if not articles:
                logger.warning(f"   ⚠️ Không tìm thấy bài viết nào ở trang {page_num}")
                # Có thể bị redirect đến login page
                if "login" in resp.url.lower():
                    logger.error("   ❌ Bị redirect đến trang đăng nhập. Dừng.")
                    break
            
            for article in articles:
                try:
                    # Lấy text
                    text_parts = []
                    for p in article.find_all(["p", "span", "div"], recursive=True):
                        t = p.get_text(strip=True)
                        if t and len(t) > 10:  # Bỏ qua text quá ngắn (buttons, etc.)
                            text_parts.append(t)
                    
                    text = "\n".join(dict.fromkeys(text_parts))  # Unique, giữ thứ tự
                    text = clean_text(text)
                    
                    if not text or len(text) < 20:
                        continue
                    
                    # Lấy thời gian
                    time_elem = article.find("abbr") or article.find("time")
                    time_str = ""
                    post_time = None
                    if time_elem:
                        time_str = time_elem.get_text(strip=True)
                        # Thử lấy từ attribute
                        time_attr = time_elem.get("data-utime") or time_elem.get("datetime")
                        if time_attr:
                            try:
                                post_time = datetime.fromtimestamp(
                                    int(time_attr), tz=timezone.utc
                                )
                            except (ValueError, TypeError):
                                try:
                                    post_time = datetime.fromisoformat(time_attr)
                                except (ValueError, TypeError):
                                    pass
                        
                        if not post_time:
                            post_time = parse_relative_time(time_str)
                    
                    # Kiểm tra cutoff
                    if post_time and post_time < cutoff_date:
                        logger.info(f"   ⏹ Bài quá cũ ({time_str}). Dừng page này.")
                        return posts  # Dừng luôn
                    
                    # Lấy link bài
                    post_url = ""
                    link = article.find("a", href=re.compile(r"/story\.php|/permalink"))
                    if link:
                        post_url = urljoin(BASE_URL, link["href"])
                    
                    # Lấy reactions/likes (trên mbasic thường hiển thị số đơn giản)
                    likes = 0
                    like_elem = article.find(string=re.compile(r"\d+\s*(like|thích|react)"))
                    if like_elem:
                        m = re.search(r"(\d+)", like_elem)
                        if m:
                            likes = int(m.group(1))
                    
                    # Comment count
                    comments = 0
                    comment_elem = article.find(
                        string=re.compile(r"\d+\s*(comment|bình luận)")
                    )
                    if comment_elem:
                        m = re.search(r"(\d+)", comment_elem)
                        if m:
                            comments = int(m.group(1))
                    
                    post_data = {
                        "post_id": f"mbasic_{page_id}_{len(posts)}",
                        "page": page_id,
                        "time": str(post_time) if post_time else time_str,
                        "text": text,
                        "shared_text": "",
                        "likes": likes,
                        "comments": comments,
                        "shares": 0,
                        "reactions": "{}",
                        "post_url": post_url,
                        "image_urls": "[]",
                        "video_url": "",
                        "is_shared": False,
                    }
                    
                    posts.append(post_data)
                    logger.info(
                        f"   ✅ [{len(posts)}] {time_str} | "
                        f"👍{likes} 💬{comments} | "
                        f"{text[:80]}..."
                    )
                
                except Exception as e:
                    logger.debug(f"   ⚠️ Lỗi parse 1 bài: {e}")
                    continue
            
            # Tìm link "Xem thêm" / "See more" để sang trang tiếp
            next_link = None
            for a in soup.find_all("a"):
                href = a.get("href", "")
                text_a = a.get_text(strip=True).lower()
                if any(kw in text_a for kw in ["xem thêm", "see more", "show more"]):
                    next_link = urljoin(BASE_URL, href)
                    break
                # Hoặc tìm link pagination
                if "/pages_reaction_units/" in href or "cursor=" in href:
                    next_link = urljoin(BASE_URL, href)
                    break
            
            if next_link and next_link != url:
                url = next_link
                logger.info(f"   ➡️ Sang trang tiếp...")
            else:
                logger.info(f"   ⏹ Không còn trang tiếp.")
                break
        
        except requests.exceptions.RequestException as e:
            logger.error(f"   ❌ Lỗi request: {e}")
            break
    
    logger.info(f"📊 Tổng: {len(posts)} bài từ {page_id} (mbasic)")
    return posts


def save_results(all_posts: list[dict]):
    """Lưu kết quả."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if not all_posts:
        logger.warning("⚠️ Không có dữ liệu để lưu!")
        return
    
    # JSON
    json_path = OUTPUT_DIR / f"raw_posts_mbasic_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_posts, f, ensure_ascii=False, indent=2)
    logger.info(f"💾 JSON: {json_path}")
    
    # CSV
    csv_path = OUTPUT_DIR / f"raw_posts_mbasic_{timestamp}.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_posts[0].keys())
        writer.writeheader()
        writer.writerows(all_posts)
    logger.info(f"💾 CSV: {csv_path}")
    
    # Latest
    json_latest = OUTPUT_DIR / "raw_posts_latest.json"
    with open(json_latest, "w", encoding="utf-8") as f:
        json.dump(all_posts, f, ensure_ascii=False, indent=2)
    
    csv_latest = OUTPUT_DIR / "raw_posts_latest.csv"
    with open(csv_latest, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_posts[0].keys())
        writer.writeheader()
        writer.writerows(all_posts)


def main():
    logger.info("=" * 60)
    logger.info("🚀 FALLBACK SCRAPER (mbasic.facebook.com)")
    logger.info("   Dùng khi facebook-scraper library bị block")
    logger.info("=" * 60)
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    all_posts = []
    
    for page_id in PAGES:
        posts = scrape_mbasic_page(page_id, cutoff)
        all_posts.extend(posts)
        
        if page_id != PAGES[-1]:
            wait = random.uniform(15, 30)
            logger.info(f"⏳ Chờ {wait:.0f}s...")
            time.sleep(wait)
    
    save_results(all_posts)
    
    logger.info(f"\n✅ TỔNG: {len(all_posts)} bài viết")
    return all_posts


if __name__ == "__main__":
    main()
