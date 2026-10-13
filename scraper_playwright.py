# -*- coding: utf-8 -*-
"""
=============================================================================
Playwright-based Facebook Scraper (Phương pháp mạnh nhất)
=============================================================================
Dùng headless browser thật (Chromium) để render Facebook page.
Ưu điểm: Facebook thấy như trình duyệt thật -> ít bị block.
Không cần đăng nhập - chỉ crawl public content.

Cài đặt:
    pip install playwright
    playwright install chromium
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
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Fix Windows console encoding
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
        logging.FileHandler(LOG_DIR / "playwright_scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

PAGES = [
    {"id": "UIT.Fanpage", "url": "https://www.facebook.com/UIT.Fanpage"},
    {"id": "UITconfess", "url": "https://www.facebook.com/UITconfess"},
]

DAYS_BACK = 14
SCROLL_PAUSE = 3  # Giây giữa mỗi lần scroll
MAX_SCROLLS = 30  # Số lần scroll tối đa
MAX_POSTS = 200


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    # Bỏ "See more" / "Xem thêm" ở cuối
    text = re.sub(r"\s*(See more|Xem thêm)\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def parse_fb_time(time_str: str) -> datetime | None:
    """Parse thời gian từ Facebook post."""
    if not time_str:
        return None

    now = datetime.now(timezone.utc)
    time_str = time_str.strip().lower()

    patterns = [
        (r"(\d+)\s*(m|min|phút)", "minutes"),
        (r"(\d+)\s*(h|hr|giờ)", "hours"),
        (r"(\d+)\s*(d|day|ngày)", "days"),
        (r"(\d+)\s*(w|week|tuần)", "weeks"),
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
            delta_map = {
                "minutes": timedelta(minutes=value),
                "hours": timedelta(hours=value),
                "days": timedelta(days=value),
                "weeks": timedelta(weeks=value),
            }
            return now - delta_map[unit]

    # Thử parse date trực tiếp
    for fmt in [
        "%B %d, %Y",
        "%B %d",
        "%b %d, %Y",
        "%b %d",
        "%d %B %Y",
        "%d %B",
        "%d tháng %m, %Y",
        "%d tháng %m",
        "%Y-%m-%d",
    ]:
        try:
            dt = datetime.strptime(time_str, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=now.year)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


async def scrape_page_playwright(page_info: dict, cutoff_date: datetime) -> list[dict]:
    """Crawl 1 Facebook page bằng Playwright."""
    from playwright.async_api import async_playwright

    page_id = page_info["id"]
    page_url = page_info["url"]
    posts = []

    logger.info(f"🔍 Crawl (Playwright): {page_id}")
    logger.info(f"   URL: {page_url}")

    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--lang=vi-VN",
            ],
        )

        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
        )

        # Block unnecessary resources to speed up
        await context.route(
            "**/*.{png,jpg,jpeg,gif,svg,mp4,webm,woff,woff2,ttf}",
            lambda route: route.abort(),
        )

        page = await context.new_page()

        try:
            # Navigate to page
            logger.info("   📄 Đang tải trang...")
            await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # Đóng popup đăng nhập nếu có
            try:
                close_btn = page.locator('[aria-label="Close"]').first
                if await close_btn.is_visible(timeout=2000):
                    await close_btn.click()
                    logger.info("   ✅ Đã đóng popup đăng nhập")
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            # Thử đóng cookie consent
            try:
                cookie_btns = page.locator(
                    'button:has-text("Allow"), button:has-text("Accept"), '
                    'button:has-text("Cho phép"), button:has-text("Đồng ý")'
                )
                if await cookie_btns.first.is_visible(timeout=2000):
                    await cookie_btns.first.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            # Scroll xuống để load thêm bài
            logger.info("   📜 Đang scroll để load bài viết...")
            prev_height = 0

            for scroll_num in range(MAX_SCROLLS):
                # Scroll xuống cuối trang
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(int(SCROLL_PAUSE * 1000))

                # Kiểm tra đã load thêm chưa
                curr_height = await page.evaluate("document.body.scrollHeight")
                if curr_height == prev_height:
                    logger.info(f"   ⏹ Không còn bài mới sau {scroll_num + 1} lần scroll")
                    break
                prev_height = curr_height

                # Click "See more" / "Xem thêm" buttons trên các bài
                try:
                    see_more_btns = page.locator(
                        'div[role="button"]:has-text("See more"), '
                        'div[role="button"]:has-text("Xem thêm")'
                    )
                    count = await see_more_btns.count()
                    for i in range(min(count, 5)):
                        try:
                            await see_more_btns.nth(i).click(timeout=1000)
                            await page.wait_for_timeout(300)
                        except Exception:
                            pass
                except Exception:
                    pass

                if (scroll_num + 1) % 5 == 0:
                    logger.info(f"   📜 Đã scroll {scroll_num + 1} lần...")

            # Extract posts
            logger.info("   🔍 Đang extract bài viết...")

            # Facebook posts thường nằm trong div[role="article"] hoặc
            # div có data-ad-preview hoặc các structure khác
            post_elements = await page.query_selector_all(
                'div[role="article"], '
                'div[data-ad-preview], '
                'div.x1yztbdb.x1n2onr6.xh8yej3.x1ja2u2z'
            )

            if not post_elements:
                # Fallback: tìm theo structure khác
                post_elements = await page.query_selector_all(
                    'div.x1lliihq.x1n2onr6'
                )

            logger.info(f"   📊 Tìm thấy {len(post_elements)} phần tử bài viết")

            for idx, elem in enumerate(post_elements):
                try:
                    # Lấy text content
                    text_content = await elem.inner_text()
                    text_content = clean_text(text_content)

                    if not text_content or len(text_content) < 30:
                        continue

                    # Tìm thời gian trong bài
                    time_elem = await elem.query_selector(
                        'a[href*="/posts/"] span, '
                        'a[role="link"] span, '
                        'span.x4k7w5x, '
                        'abbr'
                    )

                    post_time = None
                    time_str = ""
                    if time_elem:
                        time_str = (await time_elem.inner_text()).strip()
                        # Cũng thử lấy aria-label / title
                        title = await time_elem.get_attribute("title")
                        if title:
                            time_str = title
                        post_time = parse_fb_time(time_str)

                    # Kiểm tra cutoff
                    if post_time and post_time < cutoff_date:
                        logger.info(f"   ⏹ Bài quá cũ: {time_str}")
                        continue

                    # Lấy link bài
                    post_url = ""
                    link_elem = await elem.query_selector(
                        'a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"]'
                    )
                    if link_elem:
                        post_url = await link_elem.get_attribute("href")
                        if post_url and not post_url.startswith("http"):
                            post_url = "https://www.facebook.com" + post_url

                    # Lấy reactions
                    likes = 0
                    reaction_elem = await elem.query_selector(
                        'span[role="toolbar"] span, '
                        'span.x1e558r4'
                    )
                    if reaction_elem:
                        reaction_text = await reaction_elem.inner_text()
                        m = re.search(r"(\d+)", reaction_text.replace(",", ""))
                        if m:
                            likes = int(m.group(1))

                    # Comments count
                    comments_count = 0
                    comment_elem = await elem.query_selector(
                        'span:has-text("comment"), span:has-text("bình luận")'
                    )
                    if comment_elem:
                        ct = await comment_elem.inner_text()
                        m = re.search(r"(\d+)", ct.replace(",", ""))
                        if m:
                            comments_count = int(m.group(1))

                    # Shares count
                    shares = 0
                    share_elem = await elem.query_selector(
                        'span:has-text("share"), span:has-text("chia sẻ")'
                    )
                    if share_elem:
                        st = await share_elem.inner_text()
                        m = re.search(r"(\d+)", st.replace(",", ""))
                        if m:
                            shares = int(m.group(1))

                    post_data = {
                        "post_id": f"pw_{page_id}_{idx}",
                        "page": page_id,
                        "time": str(post_time) if post_time else time_str,
                        "text": text_content[:5000],  # Giới hạn 5000 ký tự
                        "shared_text": "",
                        "likes": likes,
                        "comments": comments_count,
                        "shares": shares,
                        "reactions": "{}",
                        "post_url": post_url,
                        "image_urls": "[]",
                        "video_url": "",
                        "is_shared": False,
                    }

                    posts.append(post_data)
                    logger.info(
                        f"   ✅ [{len(posts)}] {time_str[:20]} | "
                        f"👍{likes} 💬{comments_count} | "
                        f"{text_content[:80]}..."
                    )

                    if len(posts) >= MAX_POSTS:
                        break

                except Exception as e:
                    logger.debug(f"   ⚠️ Lỗi parse bài {idx}: {e}")
                    continue

            # Nếu không tìm được bài bằng selectors, thử extract từ page source
            if not posts:
                logger.info("   🔄 Thử extract từ page source...")
                content = await page.content()

                # Tìm JSON data trong page source
                # Facebook thường embed dữ liệu trong script tags
                scripts = await page.query_selector_all("script")
                for script in scripts:
                    try:
                        script_text = await script.inner_text()
                        if "creation_story" in script_text or "message" in script_text:
                            # Thử extract text từ JSON
                            text_matches = re.findall(
                                r'"text"\s*:\s*"([^"]{30,})"', script_text
                            )
                            for match in text_matches:
                                # Decode unicode escapes
                                try:
                                    decoded = match.encode().decode("unicode_escape")
                                except Exception:
                                    decoded = match

                                decoded = clean_text(decoded)
                                if len(decoded) > 30:
                                    posts.append({
                                        "post_id": f"pw_json_{page_id}_{len(posts)}",
                                        "page": page_id,
                                        "time": "",
                                        "text": decoded[:5000],
                                        "shared_text": "",
                                        "likes": 0,
                                        "comments": 0,
                                        "shares": 0,
                                        "reactions": "{}",
                                        "post_url": "",
                                        "image_urls": "[]",
                                        "video_url": "",
                                        "is_shared": False,
                                    })
                                    logger.info(
                                        f"   ✅ [JSON] {decoded[:80]}..."
                                    )
                    except Exception:
                        continue

        except Exception as e:
            logger.error(f"   ❌ Lỗi: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await browser.close()

    logger.info(f"📊 Tổng: {len(posts)} bài từ {page_id}")
    return posts


def save_results(all_posts: list[dict]):
    """Lưu kết quả."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not all_posts:
        logger.warning("⚠️ Không có dữ liệu!")
        return

    # JSON
    json_path = OUTPUT_DIR / f"raw_posts_playwright_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_posts, f, ensure_ascii=False, indent=2)
    logger.info(f"💾 JSON: {json_path}")

    # CSV
    csv_path = OUTPUT_DIR / f"raw_posts_playwright_{timestamp}.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_posts[0].keys())
        writer.writeheader()
        writer.writerows(all_posts)
    logger.info(f"💾 CSV: {csv_path}")

    # Latest
    latest_json = OUTPUT_DIR / "raw_posts_latest.json"
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump(all_posts, f, ensure_ascii=False, indent=2)

    latest_csv = OUTPUT_DIR / "raw_posts_latest.csv"
    with open(latest_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_posts[0].keys())
        writer.writeheader()
        writer.writerows(all_posts)

    logger.info(f"💾 Latest files updated")


async def async_main():
    logger.info("=" * 60)
    logger.info("🚀 PLAYWRIGHT SCRAPER (Headless Browser)")
    logger.info("=" * 60)

    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    all_posts = []

    for page_info in PAGES:
        posts = await scrape_page_playwright(page_info, cutoff)
        all_posts.extend(posts)

        if page_info != PAGES[-1]:
            wait = random.uniform(5, 10)
            logger.info(f"⏳ Chờ {wait:.0f}s...")
            await asyncio.sleep(wait)

    save_results(all_posts)

    logger.info(f"\n✅ TỔNG: {len(all_posts)} bài viết")
    return all_posts


def main():
    return asyncio.run(async_main())


if __name__ == "__main__":
    main()
