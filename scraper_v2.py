# -*- coding: utf-8 -*-
"""
=============================================================================
Playwright Scraper V2 - Xử lý Login Wall + Scroll sâu
=============================================================================
Cải tiến:
- Dismiss login popup liên tục
- Scroll sâu hơn, nhiều lần hơn
- Deduplicate posts
- Screenshot để debug
- Extract text từ JSON embedded trong page source
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
DEBUG_DIR = Path(__file__).parent / "debug"
DEBUG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "scraper_v2.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

PAGES = [
    {"id": "UIT.Fanpage", "url": "https://www.facebook.com/UIT.Fanpage"},
    {"id": "UITconfess", "url": "https://www.facebook.com/UITconfess"},
]

DAYS_BACK = 14
MAX_SCROLLS = 60
SCROLL_PAUSE_MS = 2500
MAX_POSTS = 300


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*(See more|Xem thêm|See More)\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def text_hash(text: str) -> str:
    """Hash text để phát hiện duplicate."""
    cleaned = re.sub(r"\s+", "", text.lower())[:200]
    return hashlib.md5(cleaned.encode("utf-8")).hexdigest()


async def dismiss_login_wall(page):
    """Đóng tất cả popup/dialog đăng nhập Facebook."""
    dismissed = False
    
    # Danh sách selector cho các popup login
    close_selectors = [
        '[aria-label="Close"]',
        '[aria-label="Đóng"]',
        'div[role="dialog"] [aria-label="Close"]',
        'div[role="dialog"] [aria-label="Đóng"]',
        'div[role="banner"] [aria-label="Close"]',
        'i.x1b0d499',  # Close icon class
    ]
    
    for selector in close_selectors:
        try:
            btns = page.locator(selector)
            count = await btns.count()
            for i in range(count):
                btn = btns.nth(i)
                if await btn.is_visible(timeout=500):
                    await btn.click(timeout=1000)
                    dismissed = True
                    await page.wait_for_timeout(500)
        except Exception:
            pass
    
    # Nhấn Escape
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
    except Exception:
        pass
    
    # Ẩn overlay login bằng JS
    try:
        await page.evaluate("""
            // Ẩn login dialog
            document.querySelectorAll('div[role="dialog"]').forEach(d => d.style.display = 'none');
            // Ẩn overlay
            document.querySelectorAll('div[data-visualcompletion="ignore"]').forEach(d => {
                if (d.style.position === 'fixed' || getComputedStyle(d).position === 'fixed') {
                    d.style.display = 'none';
                }
            });
            // Cho phép scroll
            document.body.style.overflow = 'auto';
            document.documentElement.style.overflow = 'auto';
        """)
        dismissed = True
    except Exception:
        pass
    
    return dismissed


async def extract_posts_from_dom(page, page_id: str) -> list[dict]:
    """Extract bài viết từ DOM."""
    posts = []
    seen_hashes = set()
    
    # Thử nhiều selector khác nhau
    selectors = [
        'div[role="article"]',
        'div[data-ad-preview]',
        'div.x1yztbdb.x1n2onr6.xh8yej3.x1ja2u2z',
    ]
    
    all_elements = []
    for sel in selectors:
        try:
            elements = await page.query_selector_all(sel)
            all_elements.extend(elements)
        except Exception:
            pass
    
    logger.info(f"   📊 Tìm thấy {len(all_elements)} phần tử DOM")
    
    for idx, elem in enumerate(all_elements):
        try:
            # Lấy toàn bộ text
            full_text = await elem.inner_text()
            
            if not full_text or len(full_text) < 30:
                continue
            
            # Skip status indicators, sidebar content
            skip_patterns = [
                r"^Chỉ báo trạng thái",
                r"^Đang hoạt động",
                r"^Online status",
                r"^Tạo trang",
                r"^Create a Page",
                r"^Đăng nhập",
                r"^Log In",
                r"^Sign Up",
            ]
            if any(re.match(p, full_text.strip(), re.IGNORECASE) for p in skip_patterns):
                continue
            
            # Extract phần text chính (bỏ header/footer noise)
            lines = full_text.split("\n")
            # Tìm phần content chính - bỏ dòng đầu (tên page, thời gian)
            # và dòng cuối (Like, Comment, Share buttons)
            content_lines = []
            skip_end_patterns = [
                r"^\d+$",  # Chỉ số
                r"^(Like|Thích|Comment|Bình luận|Share|Chia sẻ|Send|Gửi)$",
                r"^(All comments|Tất cả bình luận)",
                r"^(Most relevant|Phù hợp nhất)",
                r"^(Write a comment|Viết bình luận)",
            ]
            
            in_content = False
            for line in lines:
                line = line.strip()
                if not line:
                    if in_content:
                        content_lines.append("")
                    continue
                
                # Skip header noise
                if not in_content:
                    # Bắt đầu content khi thấy hashtag hoặc text đủ dài
                    if (line.startswith("#") or 
                        len(line) > 40 or 
                        (len(line) > 15 and not any(re.match(p, line, re.IGNORECASE) for p in skip_end_patterns))):
                        in_content = True
                        content_lines.append(line)
                else:
                    # Check if we hit footer
                    if any(re.match(p, line, re.IGNORECASE) for p in skip_end_patterns):
                        continue
                    content_lines.append(line)
            
            text = clean_text("\n".join(content_lines))
            
            if len(text) < 25:
                continue
            
            # Deduplicate
            h = text_hash(text)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            
            # Tìm thời gian
            time_str = ""
            post_time = None
            try:
                time_elements = await elem.query_selector_all("a span, abbr, time")
                for te in time_elements:
                    t = (await te.inner_text()).strip()
                    # Check if it looks like a time
                    if re.search(r"(giờ|phút|ngày|tuần|tháng|hr|min|day|week|ago|trước)", t, re.IGNORECASE):
                        time_str = t
                        break
                    if re.search(r"(Tháng|January|February|March|April|May|June|July|August|September|October|November|December)", t, re.IGNORECASE):
                        time_str = t
                        break
            except Exception:
                pass
            
            # Parse Vietnamese date: "14 Tháng 8" etc
            if time_str:
                vn_months = {
                    "tháng 1": "January", "tháng 2": "February", "tháng 3": "March",
                    "tháng 4": "April", "tháng 5": "May", "tháng 6": "June",
                    "tháng 7": "July", "tháng 8": "August", "tháng 9": "September",
                    "tháng 10": "October", "tháng 11": "November", "tháng 12": "December",
                }
                ts_lower = time_str.lower()
                for vn, en in vn_months.items():
                    ts_lower = ts_lower.replace(vn, en.lower())
                
                # Try relative times
                now = datetime.now(timezone.utc)
                rel_patterns = [
                    (r"(\d+)\s*(phút|min)", "minutes"),
                    (r"(\d+)\s*(giờ|hr|hour)", "hours"),
                    (r"(\d+)\s*(ngày|day)", "days"),
                    (r"(\d+)\s*(tuần|week)", "weeks"),
                ]
                for pattern, unit in rel_patterns:
                    m = re.search(pattern, ts_lower)
                    if m:
                        val = int(m.group(1))
                        deltas = {"minutes": timedelta(minutes=val), "hours": timedelta(hours=val),
                                  "days": timedelta(days=val), "weeks": timedelta(weeks=val)}
                        post_time = now - deltas[unit]
                        break
                
                # Try absolute date
                if not post_time:
                    m = re.search(r"(\d+)\s+(january|february|march|april|may|june|july|august|september|october|november|december)", ts_lower)
                    if m:
                        day_num = int(m.group(1))
                        month_name = m.group(2).capitalize()
                        try:
                            post_time = datetime.strptime(f"{day_num} {month_name} {now.year}", "%d %B %Y")
                            post_time = post_time.replace(tzinfo=timezone.utc)
                        except ValueError:
                            pass
            
            # Lấy interactions
            likes = 0
            comments_count = 0
            shares = 0
            try:
                all_text = full_text
                # Tìm pattern "X likes/thích", "X comments/bình luận"
                like_m = re.search(r"(\d[\d,.]*)\s*(like|thích|react|lượt thích)", all_text, re.IGNORECASE)
                if like_m:
                    likes = int(like_m.group(1).replace(",", "").replace(".", ""))
                
                comment_m = re.search(r"(\d[\d,.]*)\s*(comment|bình luận)", all_text, re.IGNORECASE)
                if comment_m:
                    comments_count = int(comment_m.group(1).replace(",", "").replace(".", ""))
                
                share_m = re.search(r"(\d[\d,.]*)\s*(share|chia sẻ|lượt chia sẻ)", all_text, re.IGNORECASE)
                if share_m:
                    shares = int(share_m.group(1).replace(",", "").replace(".", ""))
            except Exception:
                pass
            
            post_data = {
                "post_id": f"pw2_{page_id}_{len(posts)}",
                "page": page_id,
                "time": str(post_time) if post_time else time_str,
                "text": text[:5000],
                "shared_text": "",
                "likes": likes,
                "comments": comments_count,
                "shares": shares,
                "reactions": "{}",
                "post_url": "",
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
        
        except Exception as e:
            logger.debug(f"   ⚠️ Lỗi parse DOM element {idx}: {e}")
            continue
    
    return posts


async def extract_posts_from_source(page, page_id: str, seen_hashes: set) -> list[dict]:
    """Extract bài viết từ page source JSON (Facebook embed data trong script tags)."""
    posts = []
    
    try:
        content = await page.content()
        
        # Facebook embeds post data as JSON in the page
        # Look for "message":{"text":"..."} patterns
        message_pattern = re.compile(
            r'"message"\s*:\s*\{\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',
            re.DOTALL
        )
        
        matches = message_pattern.findall(content)
        logger.info(f"   📝 Tìm thấy {len(matches)} text blocks từ source")
        
        for match in matches:
            try:
                # Decode unicode escapes
                decoded = match.encode("utf-8").decode("unicode_escape")
            except Exception:
                decoded = match
            
            decoded = clean_text(decoded)
            
            if len(decoded) < 25:
                continue
            
            h = text_hash(decoded)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            
            posts.append({
                "post_id": f"pw2_src_{page_id}_{len(posts)}",
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
        
        # Also try "story" / "creation_story" / "comet_sections" patterns
        text_pattern = re.compile(
            r'"text"\s*:\s*"((?:[^"\\]|\\[^u]|\\u[0-9a-fA-F]{4}){30,})"'
        )
        for match in text_pattern.findall(content):
            try:
                decoded = match.encode("utf-8").decode("unicode_escape")
            except Exception:
                decoded = match
            
            decoded = clean_text(decoded)
            if len(decoded) < 30:
                continue
            
            # Skip non-post content
            if any(kw in decoded.lower() for kw in [
                "log in", "sign up", "create account", "đăng nhập", "đăng ký",
                "copyright", "privacy", "terms", "cookie"
            ]):
                continue
            
            h = text_hash(decoded)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            
            posts.append({
                "post_id": f"pw2_txt_{page_id}_{len(posts)}",
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
            logger.info(f"   ✅ [TXT] {decoded[:80]}...")
    
    except Exception as e:
        logger.error(f"   ❌ Lỗi extract source: {e}")
    
    return posts


async def scrape_page_v2(page_info: dict, cutoff_date: datetime) -> list[dict]:
    """Crawl 1 Facebook page - Version 2."""
    from playwright.async_api import async_playwright

    page_id = page_info["id"]
    page_url = page_info["url"]

    logger.info(f"🔍 Crawl V2: {page_id}")
    logger.info(f"   URL: {page_url}")

    all_posts = []
    seen_hashes = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-web-security",
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
            # Giả lập người dùng thật
            java_script_enabled=True,
            has_touch=False,
            is_mobile=False,
            device_scale_factor=1,
        )

        # Inject stealth scripts
        await context.add_init_script("""
            // Override navigator.webdriver
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            // Override chrome.runtime
            window.chrome = { runtime: {} };
            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) =>
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(parameters);
            // Override plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['vi-VN', 'vi', 'en-US', 'en'],
            });
        """)

        # Block heavy resources
        await context.route("**/*.{png,jpg,jpeg,gif,svg,mp4,webm,webp,woff,woff2,ttf,eot}", 
                           lambda route: route.abort())

        page = await context.new_page()

        try:
            logger.info("   📄 Đang tải trang...")
            response = await page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
            logger.info(f"   HTTP Status: {response.status if response else 'N/A'}")
            await page.wait_for_timeout(4000)

            # Screenshot debug
            await page.screenshot(path=str(DEBUG_DIR / f"{page_id}_initial.png"), full_page=False)
            logger.info(f"   📸 Screenshot saved: debug/{page_id}_initial.png")

            # Dismiss login wall nhiều lần
            for attempt in range(5):
                dismissed = await dismiss_login_wall(page)
                if dismissed:
                    logger.info(f"   🔓 Dismissed login wall (attempt {attempt + 1})")
                await page.wait_for_timeout(500)

            # Scroll xuống - aggressive
            logger.info("   📜 Bắt đầu scroll...")
            prev_height = 0
            stale_count = 0
            
            for scroll_num in range(MAX_SCROLLS):
                # Dismiss login wall mỗi lần scroll
                if scroll_num % 3 == 0:
                    await dismiss_login_wall(page)

                # Scroll xuống
                await page.evaluate("""
                    window.scrollBy(0, window.innerHeight * 2);
                """)
                await page.wait_for_timeout(SCROLL_PAUSE_MS + random.randint(0, 1500))

                # Check height
                curr_height = await page.evaluate("document.body.scrollHeight")
                if curr_height == prev_height:
                    stale_count += 1
                    if stale_count >= 3:
                        logger.info(f"   ⏹ Page không load thêm sau {scroll_num + 1} scrolls")
                        break
                    # Try harder
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(3000)
                    await dismiss_login_wall(page)
                else:
                    stale_count = 0
                prev_height = curr_height

                if (scroll_num + 1) % 5 == 0:
                    logger.info(f"   📜 Scroll #{scroll_num + 1} (height: {curr_height})")

            # Final screenshot
            await page.screenshot(path=str(DEBUG_DIR / f"{page_id}_after_scroll.png"), full_page=False)

            # STEP 1: Extract từ DOM
            logger.info("   🔍 Extract từ DOM...")
            dom_posts = await extract_posts_from_dom(page, page_id)
            for post in dom_posts:
                h = text_hash(post["text"])
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    all_posts.append(post)

            # STEP 2: Extract từ page source JSON
            logger.info("   🔍 Extract từ page source...")
            src_posts = await extract_posts_from_source(page, page_id, seen_hashes)
            all_posts.extend(src_posts)

        except Exception as e:
            logger.error(f"   ❌ Lỗi: {e}")
            import traceback
            traceback.print_exc()
            # Save error screenshot
            try:
                await page.screenshot(path=str(DEBUG_DIR / f"{page_id}_error.png"))
            except Exception:
                pass

        finally:
            await browser.close()

    # Filter cutoff
    cutoff_filtered = []
    for post in all_posts:
        # Nếu có timestamp, kiểm tra cutoff
        if post.get("time") and not post["time"].startswith("pw"):
            try:
                pt = datetime.fromisoformat(post["time"])
                if pt.tzinfo is None:
                    pt = pt.replace(tzinfo=timezone.utc)
                if pt < cutoff_date:
                    continue
            except (ValueError, TypeError):
                pass
        cutoff_filtered.append(post)

    logger.info(f"📊 Tổng: {len(cutoff_filtered)} bài từ {page_id} (sau dedupe & filter)")
    return cutoff_filtered


def save_results(all_posts: list[dict]):
    """Lưu kết quả."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not all_posts:
        logger.warning("⚠️ Không có dữ liệu!")
        return

    for fname, latest in [
        (f"raw_posts_v2_{timestamp}.json", "raw_posts_latest.json"),
    ]:
        path = OUTPUT_DIR / fname
        with open(path, "w", encoding="utf-8") as f:
            json.dump(all_posts, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 {path}")
        # Latest
        with open(OUTPUT_DIR / latest, "w", encoding="utf-8") as f:
            json.dump(all_posts, f, ensure_ascii=False, indent=2)

    for fname, latest in [
        (f"raw_posts_v2_{timestamp}.csv", "raw_posts_latest.csv"),
    ]:
        path = OUTPUT_DIR / fname
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_posts[0].keys())
            writer.writeheader()
            writer.writerows(all_posts)
        logger.info(f"💾 {path}")
        with open(OUTPUT_DIR / latest, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_posts[0].keys())
            writer.writeheader()
            writer.writerows(all_posts)

    logger.info("💾 Latest files updated")


async def async_main():
    logger.info("=" * 60)
    logger.info("🚀 PLAYWRIGHT SCRAPER V2 (Login Wall Handler)")
    logger.info("=" * 60)

    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    all_posts = []

    for page_info in PAGES:
        posts = await scrape_page_v2(page_info, cutoff)
        all_posts.extend(posts)

        if page_info != PAGES[-1]:
            wait = random.uniform(5, 10)
            logger.info(f"⏳ Chờ {wait:.0f}s...")
            await asyncio.sleep(wait)

    save_results(all_posts)
    logger.info(f"\n✅ TỔNG: {len(all_posts)} bài viết (unique)")
    return all_posts


def main():
    return asyncio.run(async_main())


if __name__ == "__main__":
    main()
