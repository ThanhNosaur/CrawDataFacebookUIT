# -*- coding: utf-8 -*-
"""
=============================================================================
Sentiment Analyzer - Phân loại bài viết tích cực / tiêu cực về trường UIT
=============================================================================
Sử dụng:
1. underthesea (NLP tiếng Việt) cho sentiment analysis
2. Keyword-based analysis (fallback + boost)
3. Kết hợp cả 2 phương pháp cho kết quả chính xác hơn

Input: data/raw_posts_latest.json
Output: data/classified_posts_*.csv + data/classified_posts_*.json
        data/report_*.txt
=============================================================================
"""

import json
import csv
import re
import sys
import io
import logging
from datetime import datetime
from pathlib import Path
from collections import Counter

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
        logging.FileHandler(LOG_DIR / "sentiment.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# File input
INPUT_FILE = DATA_DIR / "raw_posts_latest.json"

# ---------------------------------------------------------------------------
# Từ khóa phân loại (tiếng Việt, liên quan đến trường UIT)
# ---------------------------------------------------------------------------

# Từ khóa TÍCH CỰC
POSITIVE_KEYWORDS = [
    # Khen trường
    "yêu trường", "tự hào", "hãnh diện", "vinh dự", "tuyệt vời",
    "xuất sắc", "giỏi", "hay", "tốt", "đẹp", "chất lượng",
    "top", "hàng đầu", "uy tín", "chuyên nghiệp",
    # Khen giảng viên
    "thầy giỏi", "cô giỏi", "giảng viên tốt", "dạy hay", "dạy tốt",
    "tận tâm", "nhiệt tình", "hết lòng",
    # Khen môi trường
    "vui", "thích", "yêu", "hạnh phúc", "may mắn", "biết ơn",
    "cảm ơn", "thank", "grateful", "amazing", "awesome",
    "love uit", "love trường", "proud",
    # Hoạt động tích cực
    "đạt giải", "chiến thắng", "thành công", "đỗ", "trúng tuyển",
    "học bổng", "khen thưởng", "vinh danh", "tốt nghiệp",
    "sự kiện hay", "hoạt động bổ ích",
    # Cơ sở vật chất tốt
    "phòng máy đẹp", "cơ sở vật chất tốt", "hiện đại", "sạch sẽ",
    "canteen ngon", "thư viện đẹp",
    # Cảm xúc tích cực
    "haha", "hihi", "ưng", "oke", "good", "nice", "great",
    "recommend", "worth", "xứng đáng",
    # Emoji text
    "❤️", "🥰", "😍", "💪", "🎉", "👍", "💯", "🔥",
]

# Từ khóa TIÊU CỰC
NEGATIVE_KEYWORDS = [
    # Chê trường
    "chán", "tệ", "dở", "kém", "tồi", "thất vọng", "bực",
    "phí tiền", "phí thời gian", "hối hận", "lãng phí",
    "rác", "trash", "worst", "terrible", "bad",
    # Chê giảng viên
    "thầy dở", "cô dở", "dạy dở", "dạy tệ", "không biết dạy",
    "vô trách nhiệm", "thiên vị", "bất công", "khó tính",
    # Phàn nàn
    "phàn nàn", "than", "khóc", "buồn", "stress", "áp lực",
    "mệt mỏi", "kiệt sức", "nản", "bỏ học", "nghỉ học",
    # Cơ sở vật chất kém
    "nóng", "chật", "bẩn", "hỏng", "cũ kỹ", "xuống cấp",
    "wifi chậm", "wifi yếu", "wifi tệ", "mạng chậm",
    "phòng máy hỏng", "máy lạnh hỏng", "toilet bẩn",
    "canteen dở", "đắt",
    # Hành chính kém
    "hành chính", "quan liêu", "thủ tục rườm rà", "chậm trễ",
    "đăng ký khó", "hết chỗ", "không đăng ký được",
    # Điểm số
    "rớt", "trượt", "fail", "điểm thấp", "điểm kém",
    # An ninh
    "mất đồ", "trộm", "mất xe", "không an toàn",
    # Cảm xúc tiêu cực
    "😢", "😭", "😡", "🤬", "💔", "😤", "😞", "😔",
    # Confession phàn nàn
    "lừa đảo", "scam", "nợ môn", "học lại",
]

# Từ khóa TRUNG LẬP (giảm weight khi gặp)
NEUTRAL_INDICATORS = [
    "hỏi", "cho mình hỏi", "ai biết", "giúp mình",
    "tìm", "cần", "bán", "mua", "share", "chia sẻ",
    "deadline", "lịch thi", "thời khóa biểu",
]


def load_posts(filepath: Path) -> list[dict]:
    """Load bài viết từ JSON file."""
    if not filepath.exists():
        logger.error(f"❌ Không tìm thấy file: {filepath}")
        logger.info("   Hãy chạy scraper.py hoặc scraper_fallback.py trước!")
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as f:
        posts = json.load(f)

    logger.info(f"📂 Đã load {len(posts)} bài từ {filepath}")
    return posts


def keyword_sentiment(text: str) -> tuple[str, float, list[str]]:
    """
    Phân loại sentiment dựa trên từ khóa.
    
    Returns:
        (label, score, matched_keywords)
        label: "positive" / "negative" / "neutral"
        score: -1.0 đến 1.0
        matched_keywords: danh sách từ khóa tìm thấy
    """
    text_lower = text.lower()
    
    pos_matches = []
    neg_matches = []
    neutral_matches = []
    
    for kw in POSITIVE_KEYWORDS:
        if kw.lower() in text_lower:
            pos_matches.append(kw)
    
    for kw in NEGATIVE_KEYWORDS:
        if kw.lower() in text_lower:
            neg_matches.append(kw)
    
    for kw in NEUTRAL_INDICATORS:
        if kw.lower() in text_lower:
            neutral_matches.append(kw)
    
    pos_score = len(pos_matches)
    neg_score = len(neg_matches)
    
    # Giảm score nếu có nhiều indicator trung lập
    if neutral_matches:
        pos_score *= 0.7
        neg_score *= 0.7
    
    total = pos_score + neg_score
    if total == 0:
        return "neutral", 0.0, []
    
    score = (pos_score - neg_score) / total  # -1.0 đến 1.0
    
    if score > 0.2:
        label = "positive"
    elif score < -0.2:
        label = "negative"
    else:
        label = "neutral"
    
    matched = pos_matches + [f"[-]{kw}" for kw in neg_matches]
    return label, score, matched


def underthesea_sentiment(text: str) -> tuple[str, float]:
    """
    Phân loại sentiment dùng underthesea NLP.
    
    Returns:
        (label, confidence)
    """
    try:
        from underthesea import sentiment
        result = sentiment(text)
        
        # underthesea trả về: "positive", "negative", hoặc "neutral"
        label = result.lower() if isinstance(result, str) else "neutral"
        
        # Map confidence
        confidence_map = {"positive": 0.7, "negative": -0.7, "neutral": 0.0}
        score = confidence_map.get(label, 0.0)
        
        return label, score
    
    except ImportError:
        logger.warning("⚠️ underthesea chưa cài. Dùng keyword-based analysis.")
        return "unknown", 0.0
    except Exception as e:
        logger.debug(f"   underthesea error: {e}")
        return "unknown", 0.0


def classify_post(post: dict) -> dict:
    """
    Phân loại 1 bài viết.
    Kết hợp keyword-based và NLP-based sentiment.
    """
    text = post.get("text", "") + " " + post.get("shared_text", "")
    text = text.strip()
    
    if not text:
        return {
            **post,
            "sentiment": "neutral",
            "sentiment_score": 0.0,
            "sentiment_method": "empty",
            "matched_keywords": "",
            "is_about_uit": False,
        }
    
    # Kiểm tra bài có liên quan đến UIT không
    uit_keywords = [
        "uit", "đại học công nghệ thông tin", "cntt", "trường",
        "university of information technology", "khu a", "khu b",
        "linh trung", "thủ đức", "thu duc",
    ]
    is_about_uit = any(kw in text.lower() for kw in uit_keywords)
    
    # 1. Keyword-based
    kw_label, kw_score, kw_matches = keyword_sentiment(text)
    
    # 2. NLP-based (underthesea)
    nlp_label, nlp_score = underthesea_sentiment(text)
    
    # 3. Kết hợp
    if nlp_label == "unknown":
        # Chỉ dùng keyword
        final_label = kw_label
        final_score = kw_score
        method = "keyword"
    else:
        # Weighted average: NLP 60%, keyword 40%
        final_score = nlp_score * 0.6 + kw_score * 0.4
        
        if final_score > 0.15:
            final_label = "positive"
        elif final_score < -0.15:
            final_label = "negative"
        else:
            final_label = "neutral"
        method = "hybrid"
    
    return {
        **post,
        "sentiment": final_label,
        "sentiment_score": round(final_score, 3),
        "sentiment_method": method,
        "matched_keywords": ", ".join(kw_matches) if kw_matches else "",
        "is_about_uit": is_about_uit,
    }


def generate_report(classified: list[dict]) -> str:
    """Tạo báo cáo tổng hợp."""
    total = len(classified)
    if total == 0:
        return "Không có dữ liệu."
    
    # Đếm sentiment
    sentiments = Counter(p["sentiment"] for p in classified)
    pos = sentiments.get("positive", 0)
    neg = sentiments.get("negative", 0)
    neu = sentiments.get("neutral", 0)
    
    # Đếm theo page
    page_stats = {}
    for p in classified:
        page = p.get("page", "unknown")
        if page not in page_stats:
            page_stats[page] = Counter()
        page_stats[page][p["sentiment"]] += 1
    
    # Bài về UIT
    uit_posts = [p for p in classified if p.get("is_about_uit")]
    uit_sentiments = Counter(p["sentiment"] for p in uit_posts)
    
    # Top bài tương tác cao nhất
    top_engaged = sorted(
        classified,
        key=lambda x: (x.get("likes", 0) or 0) + (x.get("comments", 0) or 0),
        reverse=True,
    )[:10]
    
    # Tạo báo cáo
    lines = [
        "=" * 70,
        "📊 BÁO CÁO PHÂN TÍCH SENTIMENT - FACEBOOK UIT",
        f"   Ngày tạo: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 70,
        "",
        "📈 TỔNG QUAN",
        f"   Tổng số bài viết: {total}",
        f"   ✅ Tích cực:  {pos:>4} ({pos/total*100:.1f}%)",
        f"   ❌ Tiêu cực:  {neg:>4} ({neg/total*100:.1f}%)",
        f"   ⚪ Trung lập: {neu:>4} ({neu/total*100:.1f}%)",
        "",
    ]
    
    # Thống kê theo page
    lines.append("📊 THỐNG KÊ THEO PAGE")
    for page, stats in page_stats.items():
        page_total = sum(stats.values())
        lines.append(f"   📄 {page} ({page_total} bài)")
        lines.append(f"      ✅ Tích cực:  {stats.get('positive', 0)}")
        lines.append(f"      ❌ Tiêu cực:  {stats.get('negative', 0)}")
        lines.append(f"      ⚪ Trung lập: {stats.get('neutral', 0)}")
    lines.append("")
    
    # Bài liên quan UIT
    lines.append("🎓 BÀI VIẾT LIÊN QUAN ĐẾN UIT")
    lines.append(f"   Tổng: {len(uit_posts)} / {total} bài")
    if uit_posts:
        lines.append(f"   ✅ Tích cực:  {uit_sentiments.get('positive', 0)}")
        lines.append(f"   ❌ Tiêu cực:  {uit_sentiments.get('negative', 0)}")
        lines.append(f"   ⚪ Trung lập: {uit_sentiments.get('neutral', 0)}")
    lines.append("")
    
    # Top tương tác
    lines.append("🔥 TOP 10 BÀI TƯƠNG TÁC CAO NHẤT")
    for i, post in enumerate(top_engaged, 1):
        text_preview = (post.get("text", "")[:100] + "...") if len(post.get("text", "")) > 100 else post.get("text", "")
        sentiment_emoji = {"positive": "✅", "negative": "❌", "neutral": "⚪"}.get(post["sentiment"], "?")
        lines.append(
            f"   {i:>2}. {sentiment_emoji} [{post['page']}] "
            f"👍{post.get('likes', 0)} 💬{post.get('comments', 0)} | "
            f"{text_preview}"
        )
    lines.append("")
    
    # Top bài tiêu cực
    neg_posts = [p for p in classified if p["sentiment"] == "negative"]
    if neg_posts:
        neg_sorted = sorted(
            neg_posts,
            key=lambda x: x.get("sentiment_score", 0),
        )[:5]
        lines.append("⚠️ TOP BÀI TIÊU CỰC NHẤT")
        for i, post in enumerate(neg_sorted, 1):
            text_preview = post.get("text", "")[:120]
            lines.append(
                f"   {i}. Score: {post['sentiment_score']:.3f} | "
                f"Keywords: {post.get('matched_keywords', '')[:60]}"
            )
            lines.append(f"      \"{text_preview}...\"")
        lines.append("")
    
    # Top bài tích cực
    pos_posts = [p for p in classified if p["sentiment"] == "positive"]
    if pos_posts:
        pos_sorted = sorted(
            pos_posts,
            key=lambda x: x.get("sentiment_score", 0),
            reverse=True,
        )[:5]
        lines.append("🌟 TOP BÀI TÍCH CỰC NHẤT")
        for i, post in enumerate(pos_sorted, 1):
            text_preview = post.get("text", "")[:120]
            lines.append(
                f"   {i}. Score: {post['sentiment_score']:.3f} | "
                f"Keywords: {post.get('matched_keywords', '')[:60]}"
            )
            lines.append(f"      \"{text_preview}...\"")
        lines.append("")
    
    lines.append("=" * 70)
    lines.append("📝 Phương pháp: Hybrid (underthesea NLP + Keyword-based)")
    lines.append("   NLP weight: 60% | Keyword weight: 40%")
    lines.append("=" * 70)
    
    return "\n".join(lines)


def save_classified(classified: list[dict]):
    """Lưu kết quả phân loại."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # JSON
    json_path = DATA_DIR / f"classified_posts_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(classified, f, ensure_ascii=False, indent=2)
    logger.info(f"💾 JSON: {json_path}")
    
    # CSV
    csv_path = DATA_DIR / f"classified_posts_{timestamp}.csv"
    if classified:
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=classified[0].keys())
            writer.writeheader()
            writer.writerows(classified)
        logger.info(f"💾 CSV: {csv_path}")
    
    # Latest
    json_latest = DATA_DIR / "classified_posts_latest.json"
    with open(json_latest, "w", encoding="utf-8") as f:
        json.dump(classified, f, ensure_ascii=False, indent=2)
    
    csv_latest = DATA_DIR / "classified_posts_latest.csv"
    if classified:
        with open(csv_latest, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=classified[0].keys())
            writer.writeheader()
            writer.writerows(classified)
    
    return json_path, csv_path


def main():
    logger.info("=" * 60)
    logger.info("🧠 BẮT ĐẦU PHÂN TÍCH SENTIMENT")
    logger.info("=" * 60)
    
    # Load dữ liệu
    posts = load_posts(INPUT_FILE)
    
    if not posts:
        logger.warning("⚠️ Không có bài viết nào để phân tích!")
        return
    
    # Phân loại
    logger.info(f"\n🔄 Đang phân loại {len(posts)} bài viết...")
    classified = []
    for i, post in enumerate(posts):
        result = classify_post(post)
        classified.append(result)
        
        emoji = {"positive": "✅", "negative": "❌", "neutral": "⚪"}.get(
            result["sentiment"], "?"
        )
        if (i + 1) % 10 == 0 or i == len(posts) - 1:
            logger.info(f"   Đã xử lý {i + 1}/{len(posts)} bài...")
    
    # Lưu kết quả
    save_classified(classified)
    
    # Tạo báo cáo
    report = generate_report(classified)
    
    # Lưu báo cáo
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = DATA_DIR / f"report_{timestamp}.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"📊 Báo cáo: {report_path}")
    
    # In báo cáo ra console
    print("\n")
    print(report)
    
    return classified


if __name__ == "__main__":
    main()
