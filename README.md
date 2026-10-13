# Facebook UIT Scraper & Sentiment Analyzer

## Mô tả
Crawl bài viết từ Facebook pages của trường UIT và phân loại sentiment (tích cực / tiêu cực / trung lập).

**Pages target:**
- [UIT.Fanpage](https://www.facebook.com/UIT.Fanpage) - Fanpage chính thức
- [UITconfess](https://www.facebook.com/UITconfess) - Confession UIT

## Cách chạy

```bash
# Chạy toàn bộ (cài thư viện + crawl + phân tích)
py main.py

# Chỉ cài thư viện
py main.py install

# Chỉ crawl
py main.py scrape

# Dùng fallback scraper (nếu bị block)
py main.py fallback

# Chỉ phân tích sentiment (cần crawl trước)
py main.py analyze
```

## Cấu trúc thư mục

```
CrawDataFacebook/
├── main.py                 # Entry point - chạy toàn bộ pipeline
├── scraper.py              # Scraper chính (facebook-scraper library)
├── scraper_fallback.py     # Fallback scraper (mbasic.facebook.com)
├── sentiment_analyzer.py   # Phân tích sentiment tiếng Việt
├── requirements.txt        # Thư viện cần cài
├── README.md               # File này
├── data/                   # Dữ liệu output
│   ├── raw_posts_latest.json
│   ├── raw_posts_latest.csv
│   ├── classified_posts_latest.json
│   ├── classified_posts_latest.csv
│   └── report_*.txt
└── logs/                   # Log files
    ├── scraper.log
    ├── fallback_scraper.log
    └── sentiment.log
```

## Biện pháp an toàn

- ✅ **Không cần đăng nhập** - Chỉ crawl public pages
- ✅ **Random delay** (3-10 giây) giữa mỗi request
- ✅ **User-Agent rotation** - Đổi browser fingerprint
- ✅ **Rate limiting** tự động
- ✅ **Không lưu cookies** cá nhân

## Phương pháp phân tích

Hybrid approach:
1. **underthesea NLP** (60% weight) - Thư viện NLP tiếng Việt
2. **Keyword-based** (40% weight) - Từ điển tích cực/tiêu cực

## Lưu ý

- Nếu bị Facebook block, thử:
  1. Tăng delay trong config
  2. Dùng VPN đổi IP
  3. Chờ 30 phút - 1 giờ rồi thử lại
  4. Dùng fallback scraper: `py main.py fallback`
