# -*- coding: utf-8 -*-
"""
=============================================================================
Playwright Scraper V3 - Đăng nhập Facebook để crawl nhiều bài hơn
=============================================================================
Sử dụng tài khoản phụ (chuyên dùng crawl) để:
  - Vượt hoàn toàn Login Wall
  - Scroll vô hạn tải thêm bài
  - Lấy đầy đủ nội dung, reactions, comments

An toàn:
  - Đọc credentials từ .env (KHÔNG push lên GitHub)
  - Lưu cookies để không phải login lại mỗi lần
  - Random delay mô phỏng hành vi người
  - Stealth mode chống phát hiện bot
=============================================================================
"""

import json
import csv
import time
import random
import re
import sys
import io
import hashlib
import logging
import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
DEBUG_DIR = BASE_DIR / "debug"
DEBUG_DIR.mkdir(exist_ok=True)
COOKIE_DIR = BASE_DIR / "cookies"
COOKIE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = BASE_DIR / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "scraper_v3.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PAGES = [
    {"id": "UIT.Fanpage", "url": "https://www.facebook.com/UIT.Fanpage", "days_back": 14},
    {"id": "UITconfess", "url": "https://www.facebook.com/UITconfess", "days_back": 90},
]

MAX_SCROLLS = 70
SCROLL_PAUSE_MS = 2000
MAX_POSTS = 500
COOKIE_FILE = COOKIE_DIR / "fb_cookies.json"


def load_env():
    """Đọc credentials từ .env file."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        logger.error("❌ Không tìm thấy file .env!")
        logger.error("   Tạo file .env với nội dung:")
        logger.error("   FB_EMAIL=your@email.com")
        logger.error("   FB_PASSWORD=yourpassword")
        sys.exit(1)

    env = {}
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()

    email = env.get("FB_EMAIL")
    password = env.get("FB_PASSWORD")
    if not email or not password:
        logger.error("❌ FB_EMAIL hoặc FB_PASSWORD chưa có trong .env!")
        sys.exit(1)

    return email, password


def clean_text(text: str) -> str:
    if not text:
        return ""
    # Loại bỏ zero-width characters và combining grapheme joiner của Facebook
    text = re.sub(r"[\u034f\u200b-\u200f\ufeff\u00ad]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*(See more|Xem thêm|See More)\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def text_hash(text: str) -> str:
    cleaned = re.sub(r"\s+", "", text.lower())[:200]
    return hashlib.md5(cleaned.encode("utf-8")).hexdigest()


async def facebook_login(page, email: str, password: str) -> bool:
    """Đăng nhập Facebook. Trả về True nếu thành công."""

    # Kiểm tra đã đăng nhập chưa (qua cookies)
    try:
        url = page.url
        if "facebook.com" in url:
            # Kiểm tra xem có đang ở trang chính (đã login)
            is_logged = await page.evaluate("""
                () => {
                    return document.querySelector('[aria-label="Your profile"], [aria-label="Trang cá nhân của bạn"]') !== null
                        || document.querySelector('[aria-label="Account"], [aria-label="Tài khoản"]') !== null;
                }
            """)
            if is_logged:
                logger.info("   ✅ Đã đăng nhập sẵn (từ cookies)")
                return True
    except Exception:
        pass

    logger.info("   🔐 Đang đăng nhập Facebook...")

    try:
        # Vào trang login
        await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Điền email
        email_input = page.locator('#email, input[name="email"]').first
        await email_input.click()
        await page.wait_for_timeout(random.randint(300, 600))
        # Gõ từng ký tự (giống người thật)
        for char in email:
            await email_input.press(char)
            await page.wait_for_timeout(random.randint(50, 150))

        await page.wait_for_timeout(random.randint(500, 1000))

        # Điền password
        pass_input = page.locator('#pass, input[name="pass"]').first
        await pass_input.click()
        await page.wait_for_timeout(random.randint(300, 600))
        for char in password:
            await pass_input.press(char)
            await page.wait_for_timeout(random.randint(50, 150))

        await page.wait_for_timeout(random.randint(500, 1000))

        # Bấm Login hoặc nhấn Enter
        try:
            btn = page.locator(
                'button:has-text("Đăng nhập"), button:has-text("Log In"), '
                'div[role="button"]:has-text("Đăng nhập"), div[role="button"]:has-text("Log In"), '
                'button[name="login"], button[type="submit"], #loginbutton, [aria-label="Đăng nhập"], [aria-label="Log In"]'
            ).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
            else:
                await pass_input.press("Enter")
        except Exception:
            await pass_input.press("Enter")

        # Chờ redirect sau khi đăng nhập
        logger.info("   ⏳ Đang gửi thông tin đăng nhập, chờ phản hồi...")
        await page.wait_for_timeout(6000)

        # Kiểm tra thành công
        current_url = page.url
        if "login" in current_url.lower() or "checkpoint" in current_url.lower():
            # Có thể bị checkpoint / 2FA
            logger.warning(f"   ⚠️ Có thể bị checkpoint: {current_url}")
            await page.screenshot(path=str(DEBUG_DIR / "login_checkpoint.png"))

            # Thử đóng dialog nếu có
            try:
                continue_btn = page.locator('button:has-text("Continue"), button:has-text("Tiếp tục")').first
                if await continue_btn.is_visible(timeout=3000):
                    await continue_btn.click()
                    await page.wait_for_timeout(3000)
            except Exception:
                pass

            # Kiểm tra lại
            current_url = page.url
            if "login" in current_url.lower():
                logger.error("   ❌ Đăng nhập thất bại! Kiểm tra email/password trong .env")
                return False

        logger.info("   ✅ Đăng nhập thành công!")
        await page.screenshot(path=str(DEBUG_DIR / "login_success.png"))
        return True

    except Exception as e:
        logger.error(f"   ❌ Lỗi đăng nhập: {e}")
        try:
            await page.screenshot(path=str(DEBUG_DIR / "login_error.png"))
        except Exception:
            pass
        return False


async def save_cookies(context):
    """Lưu cookies ra file để dùng lại."""
    try:
        cookies = await context.cookies()
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2)
        logger.info(f"   🍪 Đã lưu {len(cookies)} cookies -> {COOKIE_FILE}")
    except Exception as e:
        logger.warning(f"   ⚠️ Lỗi lưu cookies: {e}")


async def load_cookies(context) -> bool:
    """Load cookies từ file (để không phải login lại)."""
    try:
        if COOKIE_FILE.exists():
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            await context.add_cookies(cookies)
            logger.info(f"   🍪 Đã load {len(cookies)} cookies từ file")
            return True
    except Exception as e:
        logger.warning(f"   ⚠️ Cookies hết hạn/lỗi: {e}")
    return False


async def extract_posts_logged_in(page, page_id: str, cutoff_date: datetime) -> list[dict]:
    """Extract bài viết khi đã đăng nhập - lấy được nhiều hơn."""
    posts = []
    seen_hashes = set()

    # Khi đã login, Facebook render bài trong div[role="article"]
    # hoặc các div có class đặc biệt
    # Khi đã login, Facebook render bài trong feed hoặc article
    article_selectors = [
        'div[data-pagelet*="FeedUnit"]',
        'div[role="feed"] > div',
        'div[role="article"]',
        'div.x1yztbdb.x1n2onr6.xh8yej3.x1ja2u2z',
    ]

    all_articles = []
    for sel in article_selectors:
        try:
            elements = await page.query_selector_all(sel)
            if elements:
                all_articles.extend(elements)
        except Exception:
            pass

    logger.info(f"   📊 Tìm thấy {len(all_articles)} phần tử bài viết")

    for idx, article in enumerate(all_articles):
        try:
            # Lấy toàn bộ text
            full_text = await article.inner_text()
            if not full_text or len(full_text) < 30:
                continue

            # Bỏ qua sidebar / ads
            skip_patterns = [
                r"^(Chỉ báo trạng thái|Online status|Đang hoạt động)",
                r"^(Tạo trang|Create|Đăng nhập|Log In|Sign Up)",
                r"^(Pages liked|Trang đã thích|Groups|Nhóm|Marketplace)",
                r"^Sponsored$",
                r"^(People You May Know|Những người bạn có thể biết)",
            ]
            first_line = full_text.strip().split("\n")[0].strip()
            if any(re.match(p, first_line, re.IGNORECASE) for p in skip_patterns):
                continue

            # ===== PARSE NỘI DUNG =====
            lines = full_text.split("\n")
            
            # Tìm tên page/người đăng (thường ở dòng 1-2)
            poster_name = ""
            if lines:
                poster_name = lines[0].strip()

            # Tìm thời gian (dòng có chứa pattern thời gian)
            time_str = ""
            post_time = None
            now = datetime.now(timezone.utc)
            
            for line in lines[:8]:  # Thời gian thường ở 8 dòng đầu
                line = line.strip()
                # Relative time patterns
                rel_patterns = [
                    (r"(\d+)\s*(phút|min|m)\b", "minutes"),
                    (r"(\d+)\s*(giờ|hour|h)\b", "hours"),
                    (r"(\d+)\s*(ngày|day|d)\b", "days"),
                    (r"(\d+)\s*(tuần|week|w)\b", "weeks"),
                    (r"(hôm qua|yesterday)", "yesterday"),
                    (r"(vừa xong|just now)", "now"),
                ]
                for pattern, unit in rel_patterns:
                    m = re.search(pattern, line, re.IGNORECASE)
                    if m:
                        time_str = line
                        if unit == "now":
                            post_time = now
                        elif unit == "yesterday":
                            post_time = now - timedelta(days=1)
                        else:
                            val = int(m.group(1))
                            deltas = {
                                "minutes": timedelta(minutes=val),
                                "hours": timedelta(hours=val),
                                "days": timedelta(days=val),
                                "weeks": timedelta(weeks=val),
                            }
                            post_time = now - deltas[unit]
                        break

                # Vietnamese absolute date: "14 Tháng 8" / "1 tháng 10"
                if not post_time:
                    m = re.search(r"(\d{1,2})\s+[Tt]háng\s+(\d{1,2})", line)
                    if m:
                        day_n = int(m.group(1))
                        month_n = int(m.group(2))
                        time_str = line
                        try:
                            post_time = datetime(now.year, month_n, day_n, tzinfo=timezone.utc)
                            if post_time > now:
                                post_time = post_time.replace(year=now.year - 1)
                        except ValueError:
                            pass
                        break

                # English: "October 13" / "October 13, 2026"
                if not post_time:
                    m = re.search(
                        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})",
                        line, re.IGNORECASE
                    )
                    if m:
                        time_str = line
                        try:
                            year_match = re.search(r",\s*(\d{4})", line)
                            year = int(year_match.group(1)) if year_match else now.year
                            post_time = datetime.strptime(f"{m.group(1)} {m.group(2)} {year}", "%B %d %Y")
                            post_time = post_time.replace(tzinfo=timezone.utc)
                        except ValueError:
                            pass
                        break

                if post_time:
                    break

            # Kiểm tra cutoff date
            if post_time and post_time < cutoff_date:
                logger.info(f"   ⏹ Bài cũ hơn {DAYS_BACK} ngày ({time_str}). Bỏ qua.")
                continue

            # ===== EXTRACT NỘI DUNG CHÍNH =====
            content_lines = []
            in_content = False
            footer_patterns = [
                r"^(Like|Thích|Haha|Wow|Love|Buồn|Phẫn nộ|Angry|Sad)$",
                r"^(Comment|Bình luận|Share|Chia sẻ|Send|Gửi)$",
                r"^(All comments|Tất cả bình luận|Most relevant|Phù hợp nhất)",
                r"^(Write a comment|Viết bình luận)",
                r"^\d+[.,]?\d*\s*(K|k|M|m)?$",  # Chỉ số like/share
                r"^(Bạn|You) và \d+ người khác",
            ]

            for i, line in enumerate(lines):
                line_stripped = line.strip()
                if not line_stripped:
                    if in_content:
                        content_lines.append("")
                    continue

                # Skip header (poster name, time, ...)
                if not in_content:
                    if (line_stripped.startswith("#") or
                        len(line_stripped) > 50 or
                        (i > 2 and len(line_stripped) > 20 and
                         not any(re.match(p, line_stripped, re.IGNORECASE) for p in footer_patterns))):
                        in_content = True
                        content_lines.append(line_stripped)
                else:
                    if any(re.match(p, line_stripped, re.IGNORECASE) for p in footer_patterns):
                        continue
                    content_lines.append(line_stripped)

            text = clean_text("\n".join(content_lines))

            # Loại bỏ rác từ header (chỉ báo online, tên trường lặp lại...)
            text = re.sub(r"^Chỉ báo trạng thái online[^\n]*\n*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"^Đang hoạt động[^\n]*\n*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"^Trường Đại học Công nghệ Thông tin - Đại học Quốc gia TP\.HCM[^\n]*\n*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"^[a-zA-Z͏\s\d:.]+(trước|ago)\s*", "", text, flags=re.IGNORECASE)
            text = text.strip()

            if len(text) < 25:
                continue

            # Bỏ qua bình luận trả lời ngắn
            if len(text) < 80 and any(kw in text for kw in ["Trả lời", "Reply", "Xem thêm câu trả lời"]):
                continue

            # Bỏ qua chuỗi ký tự rác ẩn danh của FB (như 'o͏ s͏ o͏ t͏ e͏...')
            if len(re.sub(r"[\s͏a-zA-Z]", "", text)) < 5 and len(text) < 60:
                continue

            # Deduplicate
            h = text_hash(text)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)

            # ===== EXTRACT INTERACTIONS =====
            likes = 0
            comments_count = 0
            shares = 0
            try:
                like_m = re.search(r"(\d[\d,.]*)\s*(K|k)?\s*(lượt thích|like|react)", full_text, re.IGNORECASE)
                if like_m:
                    val = like_m.group(1).replace(",", "").replace(".", "")
                    likes = int(val)
                    if like_m.group(2) and like_m.group(2).lower() == "k":
                        likes *= 1000

                comment_m = re.search(r"(\d[\d,.]*)\s*(K|k)?\s*(bình luận|comment)", full_text, re.IGNORECASE)
                if comment_m:
                    val = comment_m.group(1).replace(",", "").replace(".", "")
                    comments_count = int(val)

                share_m = re.search(r"(\d[\d,.]*)\s*(K|k)?\s*(chia sẻ|share|lượt chia sẻ)", full_text, re.IGNORECASE)
                if share_m:
                    val = share_m.group(1).replace(",", "").replace(".", "")
                    shares = int(val)
            except Exception:
                pass

            # Lấy post URL
            post_url = ""
            try:
                link = await article.query_selector('a[href*="/posts/"], a[href*="story_fbid"], a[href*="/permalink/"]')
                if link:
                    href = await link.get_attribute("href")
                    if href:
                        post_url = href if href.startswith("http") else "https://www.facebook.com" + href
            except Exception:
                pass

            post_data = {
                "post_id": f"v3_{page_id}_{len(posts)}",
                "page": page_id,
                "time": str(post_time) if post_time else time_str,
                "text": text[:8000],
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
                f"   ✅ [{len(posts)}] {time_str[:25]} | "
                f"👍{likes} 💬{comments_count} 🔁{shares} | "
                f"{text[:80]}..."
            )

            if len(posts) >= MAX_POSTS:
                break

        except Exception as e:
            logger.debug(f"   ⚠️ Lỗi parse element {idx}: {e}")
            continue

    return posts


async def extract_posts_from_source(page, page_id: str, seen_hashes: set) -> list[dict]:
    """Extract bài viết từ page source JSON (Facebook embed data trong script tags)."""
    posts = []
    try:
        content = await page.content()
        message_pattern = re.compile(
            r'"message"\s*:\s*\{\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',
            re.DOTALL
        )
        matches = message_pattern.findall(content)
        for match in matches:
            try:
                decoded = match.encode("utf-8").decode("unicode_escape")
            except Exception:
                decoded = match
            decoded = clean_text(decoded)
            if len(decoded) < 30:
                continue
            h = text_hash(decoded)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            posts.append({
                "post_id": f"v3_src_{page_id}_{len(posts)}",
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
            logger.info(f"   ✅ [SRC] {decoded[:80]}...")
    except Exception as e:
        logger.debug(f"   ⚠️ Lỗi extract source: {e}")
    return posts


async def scrape_page_v3(page_info: dict, context, cutoff_date: datetime) -> list[dict]:
    """Crawl 1 Facebook page khi đã đăng nhập."""
    page_id = page_info["id"]
    page_url = page_info["url"]

    logger.info(f"\n{'━' * 50}")
    logger.info(f"🔍 Crawl V3 (Logged In): {page_id}")
    logger.info(f"   URL: {page_url}")

    page = await context.new_page()

    try:
        # Vào trang
        logger.info("   📄 Đang tải trang...")
        await page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(4000)

        # Screenshot
        await page.screenshot(path=str(DEBUG_DIR / f"v3_{page_id}_loaded.png"))
        logger.info(f"   📸 Screenshot: debug/v3_{page_id}_loaded.png")

        # ===== SCROLL XUỐNG ĐỂ LOAD BÀI =====
        logger.info("   📜 Bắt đầu scroll để load bài viết...")
        prev_height = 0
        stale_count = 0
        total_scrolls = 0

        for scroll_num in range(MAX_SCROLLS):
            # Đóng modal/popup nếu vô tình bị mở ra
            try:
                close_btn = page.locator('div[role="dialog"] [aria-label="Đóng"], div[role="dialog"] [aria-label="Close"]').first
                if await close_btn.is_visible(timeout=200):
                    await close_btn.click()
                    await page.wait_for_timeout(300)
            except Exception:
                pass

            # Scroll mượt mà
            scroll_distance = random.randint(900, 1500)
            await page.evaluate(f"window.scrollBy(0, {scroll_distance})")
            
            # Random delay
            delay = SCROLL_PAUSE_MS + random.randint(-400, 800)
            await page.wait_for_timeout(delay)

            total_scrolls += 1

            # Check đã hết bài chưa
            curr_height = await page.evaluate("document.body.scrollHeight")
            if curr_height == prev_height:
                stale_count += 1
                if stale_count >= 4:
                    logger.info(f"   ⏹ Không load thêm bài sau {total_scrolls} scrolls")
                    break
                # Scroll thử xa hơn
                await page.evaluate("window.scrollBy(0, 2000)")
                await page.wait_for_timeout(2500)
            else:
                stale_count = 0
            prev_height = curr_height

            if (scroll_num + 1) % 10 == 0:
                logger.info(f"   📜 Scroll #{scroll_num + 1} | Height: {curr_height}")

        # Screenshot sau scroll
        await page.screenshot(path=str(DEBUG_DIR / f"v3_{page_id}_scrolled.png"))

        # ===== EXTRACT BÀI VIẾT =====
        logger.info("   🔍 Đang extract bài viết...")
        posts = await extract_posts_logged_in(page, page_id, cutoff_date)
        seen_hashes = {text_hash(p["text"]) for p in posts}

        # Trích xuất thêm từ embedded source JSON
        src_posts = await extract_posts_from_source(page, page_id, seen_hashes)
        posts.extend(src_posts)

        logger.info(f"📊 Tổng: {len(posts)} bài từ {page_id}")

    except Exception as e:
        logger.error(f"   ❌ Lỗi: {e}")
        import traceback
        traceback.print_exc()
        try:
            await page.screenshot(path=str(DEBUG_DIR / f"v3_{page_id}_error.png"))
        except Exception:
            pass
        posts = []

    finally:
        await page.close()

    return posts


def save_results(all_posts: list[dict]):
    """Lưu kết quả."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not all_posts:
        logger.warning("⚠️ Không có dữ liệu!")
        return

    # JSON
    json_path = OUTPUT_DIR / f"raw_posts_v3_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_posts, f, ensure_ascii=False, indent=2)
    logger.info(f"💾 JSON: {json_path}")

    # CSV
    csv_path = OUTPUT_DIR / f"raw_posts_v3_{timestamp}.csv"
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

    logger.info("💾 Latest files updated")


async def async_main():
    from playwright.async_api import async_playwright

    logger.info("=" * 60)
    logger.info("🚀 PLAYWRIGHT SCRAPER V3 (Đăng nhập Facebook)")
    logger.info("=" * 60)

    # Load credentials
    email, password = load_env()
    logger.info(f"   📧 Account: {email}")
    all_posts = []

    async with async_playwright() as p:
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
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
        )

        # Stealth injection
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
            const origQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (params) =>
                params.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : origQuery(params);
        """)

        # Block ảnh/video để tăng tốc
        await context.route("**/*.{png,jpg,jpeg,gif,svg,mp4,webm,webp,woff,woff2,ttf,eot}",
                           lambda route: route.abort())

        # Thử load cookies cũ
        has_cookies = await load_cookies(context)

        # Mở trang chính để kiểm tra login state
        login_page = await context.new_page()
        await login_page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=30000)
        await login_page.wait_for_timeout(3000)

        # Login nếu cần
        logged_in = await facebook_login(login_page, email, password)
        await login_page.close()

        if not logged_in:
            logger.error("❌ Không đăng nhập được. Dừng.")
            await browser.close()
            return []

        # Lưu cookies sau khi login thành công
        await save_cookies(context)

        # Crawl từng page
        for page_info in PAGES:
            days = page_info.get("days_back", 14)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            logger.info(f"   📅 Lấy bài {page_info['id']} trong {days} ngày gần nhất (từ {cutoff.strftime('%Y-%m-%d')})")
            posts = await scrape_page_v3(page_info, context, cutoff)
            all_posts.extend(posts)

            if page_info != PAGES[-1]:
                wait = random.uniform(8, 15)
                logger.info(f"⏳ Chờ {wait:.0f}s trước khi crawl page tiếp...")
                await asyncio.sleep(wait)

        await browser.close()

    # Lưu kết quả
    save_results(all_posts)
    logger.info(f"\n✅ TỔNG: {len(all_posts)} bài viết (unique)")
    return all_posts


def main():
    return asyncio.run(async_main())


if __name__ == "__main__":
    main()
