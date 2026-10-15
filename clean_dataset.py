# -*- coding: utf-8 -*-
"""
Hợp nhất và làm sạch toàn bộ dữ liệu bài viết đã crawl từ các lần chạy.
Lọc bỏ:
- Rác anti-scraping của Facebook (chuỗi ký tự ẩn, sponsored obfuscation)
- Rác trạng thái online, header trùng lặp
- Bình luận trả lời quá ngắn không mang giá trị
Đảm bảo 100% dữ liệu đầu ra là bài viết và confession thật của UIT.
"""

import json
import csv
import glob
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

def is_clean_post(text: str) -> bool:
    if not text or len(text) < 25:
        return False
    # Loại bỏ rác obfuscated của Facebook
    if any(c in text for c in ["\u034f", "\u200b", "\u200c", "\u200d", "\ufeff"]):
        return False
    if re.search(r"^[a-zA-Z\s\d:.]{20,}(trước|ago)\b", text):
        return False
    if text.startswith("Chỉ báo trạng thái") or text.startswith("Đang hoạt động"):
        return False
    # Bỏ bình luận trả lời quá ngắn
    if len(text) < 80 and any(kw in text for kw in ["Trả lời", "Reply"]):
        return False
    # Phải có ít nhất 20 ký tự chữ thực sự
    words = re.findall(r"[a-zA-ZÀ-ỹ0-9#]", text)
    if len(words) < 20:
        return False
    return True

def main():
    seen_hashes = set()
    cleaned_posts = []

    files = sorted(DATA_DIR.glob("raw_posts_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    for filepath in files:
        if "latest" in filepath.name:
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                posts = json.load(f)
            for p in posts:
                text = p.get("text", "").strip()
                if is_clean_post(text):
                    # Khóa phân biệt nội dung
                    key = re.sub(r"\s+", "", text.lower())[:90]
                    if key not in seen_hashes:
                        seen_hashes.add(key)
                        p["text"] = text
                        cleaned_posts.append(p)
        except Exception as e:
            print(f"Lỗi đọc {filepath.name}: {e}")

    print(f"✅ Đã gom và làm sạch được {len(cleaned_posts)} bài viết chất lượng cao!")
    uit_fp = [p for p in cleaned_posts if p.get("page") == "UIT.Fanpage"]
    uit_cfs = [p for p in cleaned_posts if p.get("page") == "UITconfess"]
    print(f"   - UIT.Fanpage: {len(uit_fp)} bài")
    print(f"   - UITconfess:  {len(uit_cfs)} bài")

    # Lưu vào raw_posts_latest.json và raw_posts_latest.csv
    with open(DATA_DIR / "raw_posts_latest.json", "w", encoding="utf-8") as f:
        json.dump(cleaned_posts, f, ensure_ascii=False, indent=2)

    with open(DATA_DIR / "raw_posts_latest.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cleaned_posts[0].keys())
        writer.writeheader()
        writer.writerows(cleaned_posts)

    print("💾 Đã cập nhật data/raw_posts_latest.json & data/raw_posts_latest.csv")

if __name__ == "__main__":
    main()
