# -*- coding: utf-8 -*-
"""
=============================================================================
Facebook Page Scraper - UIT Fanpage & UIT Confessions
=============================================================================
Crawl bài viết từ Facebook pages công khai KHÔNG cần đăng nhập.
Phân loại sentiment (tích cực / tiêu cực / trung lập) về trường UIT.

Tác giả: Auto-generated cho bài tập
Ngày: 2026-10-13
=============================================================================
"""

import json
import csv
import time
import random
import os
import re
import sys
import io
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Fix Windows console encoding (cp1252 -> utf-8)
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

# Các page cần crawl
PAGES = [
    "UIT.Fanpage",
    "UITconfess",
]

# Chỉ lấy bài trong 2 tuần gần nhất
DAYS_BACK = 14

# Delay giữa các request (giây) - quan trọng để tránh bị block
MIN_DELAY = 3
MAX_DELAY = 7

# Số bài tối đa mỗi page (an toàn)
MAX_POSTS_PER_PAGE = 200

# Proxy (nếu có) - để None nếu không dùng proxy
# Format: "http://user:pass@host:port" hoặc "http://host:port"
PROXY = None

# Cookie file (nếu có) - để None nếu không cần đăng nhập
COOKIE_FILE = None


def safe_import():
    """Import thư viện và kiểm tra."""
    try:
        import facebook_scraper
        return facebook_scraper
    except ImportError:
        logger.error(
            "Chưa cài facebook-scraper. Chạy: pip install facebook-scraper"
        )
        sys.exit(1)


def get_cutoff_date(days_back: int) -> datetime:
    """Tính ngày bắt đầu lấy dữ liệu."""
    return datetime.now(timezone.utc) - timedelta(days=days_back)


def random_delay():
    """Delay ngẫu nhiên giữa các request để tránh bị phát hiện."""
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    logger.debug(f"Waiting {delay:.1f}s ...")
    time.sleep(delay)


def clean_text(text: str) -> str:
    """Làm sạch text bài viết."""
    if not text:
        return ""
    # Bỏ nhiều dòng trống liên tiếp
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Bỏ khoảng trắng thừa
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def scrape_page(page_id: str, cutoff_date: datetime) -> list[dict]:
    """
    Crawl bài viết từ 1 Facebook page.

    Sử dụng facebook-scraper (không cần đăng nhập cho page công khai).
    """
    fb = safe_import()

    posts = []
    logger.info(f"🔍 Bắt đầu crawl page: {page_id}")
    logger.info(f"   Cutoff date: {cutoff_date.strftime('%Y-%m-%d %H:%M')}")

    options = {
        "allow_extra_requests": True,
        "posts_per_page": 4,  # Số bài mỗi lần request (nhỏ = an toàn hơn)
    }

    try:
        # get_posts không cần đăng nhập cho public pages
        gen = fb.get_posts(
            page_id,
            pages=50,  # Số "trang" tối đa
            options=options,
            timeout=30,
        )

        count = 0
        for post in gen:
            try:
                # Kiểm tra ngày
                post_time = post.get("time")
                if post_time:
                    # Đảm bảo timezone aware
                    if post_time.tzinfo is None:
                        post_time = post_time.replace(tzinfo=timezone.utc)
                    
                    if post_time < cutoff_date:
                        logger.info(
                            f"   ⏹ Đã đến bài cũ hơn cutoff ({post_time.strftime('%Y-%m-%d')}). Dừng."
                        )
                        break

                post_data = {
                    "post_id": post.get("post_id", ""),
                    "page": page_id,
                    "time": str(post_time) if post_time else "",
                    "text": clean_text(post.get("text", "") or post.get("post_text", "")),
                    "shared_text": clean_text(post.get("shared_text", "")),
                    "likes": post.get("likes", 0) or 0,
                    "comments": post.get("comments", 0) or 0,
                    "shares": post.get("shares", 0) or 0,
                    "reactions": json.dumps(post.get("reactions", {}), ensure_ascii=False),
                    "post_url": post.get("post_url", ""),
                    "image_urls": json.dumps(post.get("images", []), ensure_ascii=False),
                    "video_url": post.get("video", ""),
                    "is_shared": bool(post.get("shared_text")),
                }

                # Chỉ lấy bài có nội dung
                if post_data["text"] or post_data["shared_text"]:
                    posts.append(post_data)
                    count += 1
                    logger.info(
                        f"   ✅ [{count}] {post_data['time'][:19]} | "
                        f"👍{post_data['likes']} 💬{post_data['comments']} | "
                        f"{post_data['text'][:80]}..."
                    )

                if count >= MAX_POSTS_PER_PAGE:
                    logger.info(f"   ⏹ Đã đạt giới hạn {MAX_POSTS_PER_PAGE} bài.")
                    break

                # Delay giữa các bài
                random_delay()

            except Exception as e:
                logger.warning(f"   ⚠️ Lỗi xử lý 1 bài: {e}")
                continue

    except Exception as e:
        logger.error(f"❌ Lỗi crawl page {page_id}: {e}")
        logger.error(
            "   💡 Nếu bị block, thử:\n"
            "      1. Tăng MIN_DELAY/MAX_DELAY\n"
            "      2. Dùng VPN/proxy\n"
            "      3. Chờ vài giờ rồi thử lại"
        )

    logger.info(f"📊 Tổng cộng {len(posts)} bài từ {page_id}")
    return posts


def save_to_json(posts: list[dict], filename: str):
    """Lưu dữ liệu ra file JSON."""
    filepath = OUTPUT_DIR / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    logger.info(f"💾 Đã lưu {len(posts)} bài -> {filepath}")
    return filepath


def save_to_csv(posts: list[dict], filename: str):
    """Lưu dữ liệu ra file CSV."""
    if not posts:
        logger.warning("Không có dữ liệu để lưu CSV.")
        return None

    filepath = OUTPUT_DIR / filename
    fieldnames = posts[0].keys()

    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(posts)

    logger.info(f"💾 Đã lưu {len(posts)} bài -> {filepath}")
    return filepath


def main():
    """Hàm chính - crawl tất cả pages."""
    logger.info("=" * 60)
    logger.info("🚀 BẮT ĐẦU CRAWL FACEBOOK PAGES")
    logger.info(f"   Pages: {PAGES}")
    logger.info(f"   Lấy bài trong {DAYS_BACK} ngày gần nhất")
    logger.info("=" * 60)

    cutoff = get_cutoff_date(DAYS_BACK)
    all_posts = []

    for page_id in PAGES:
        logger.info(f"\n{'─' * 40}")
        posts = scrape_page(page_id, cutoff)
        all_posts.extend(posts)

        # Delay giữa các page
        if page_id != PAGES[-1]:
            wait = random.uniform(10, 20)
            logger.info(f"⏳ Chờ {wait:.0f}s trước khi crawl page tiếp...")
            time.sleep(wait)

    # Lưu kết quả
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if all_posts:
        save_to_json(all_posts, f"raw_posts_{timestamp}.json")
        save_to_csv(all_posts, f"raw_posts_{timestamp}.csv")

        # Lưu thêm file "latest" để dễ dùng
        save_to_json(all_posts, "raw_posts_latest.json")
        save_to_csv(all_posts, "raw_posts_latest.csv")
    else:
        logger.warning("⚠️ Không crawl được bài nào!")

    logger.info("\n" + "=" * 60)
    logger.info(f"✅ HOÀN TẤT - Tổng cộng {len(all_posts)} bài viết")
    logger.info("=" * 60)

    return all_posts


if __name__ == "__main__":
    main()
