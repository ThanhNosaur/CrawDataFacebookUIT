# -*- coding: utf-8 -*-
"""
=============================================================================
Main Runner - Chạy toàn bộ pipeline
=============================================================================
Thứ tự:
1. Cài thư viện (nếu chưa có)
2. Crawl bài viết từ Facebook
3. Phân loại sentiment
4. Tạo báo cáo

Cách dùng:
    py main.py          # Chạy toàn bộ
    py main.py scrape   # Chỉ crawl
    py main.py analyze  # Chỉ phân tích (cần có data trước)
    py main.py fallback # Dùng fallback scraper
=============================================================================
"""

import subprocess
import sys
import os
from pathlib import Path


def install_requirements():
    """Cài đặt thư viện từ requirements.txt."""
    req_file = Path(__file__).parent / "requirements.txt"
    
    if not req_file.exists():
        print("❌ Không tìm thấy requirements.txt")
        return False
    
    print("📦 Đang cài đặt thư viện...")
    print("=" * 50)
    
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
        capture_output=False,
    )
    
    if result.returncode != 0:
        print("⚠️ Một số thư viện có thể chưa cài được.")
        print("   Thử cài thủ công: pip install -r requirements.txt")
        return False
    
    print("✅ Đã cài xong thư viện!\n")
    return True


def run_scraper():
    """Chạy scraper chính (Playwright Stealth V2 vượt Login Wall)."""
    print("\n" + "=" * 60)
    print("🕷️ BƯỚC 1: CRAWL DỮ LIỆU TỪ FACEBOOK (PLAYWRIGHT V2)")
    print("=" * 60 + "\n")
    
    try:
        from scraper_v2 import main as scrape_v2_main
        posts = scrape_v2_main()
        if posts:
            return posts
        print("⚠️ Playwright V2 không trích xuất được bài, thử scraper cơ bản...")
    except Exception as e:
        print(f"\n⚠️ Playwright V2 gặp lỗi: {e}")
        print("🔄 Chuyển sang fallback scraper...\n")

    return run_fallback_scraper()


def run_fallback_scraper():
    """Chạy fallback scraper."""
    print("\n" + "=" * 60)
    print("🕷️ FALLBACK SCRAPER (mbasic.facebook.com)")
    print("=" * 60 + "\n")
    
    try:
        from scraper_fallback import main as fallback_main
        posts = fallback_main()
        return posts
    except Exception as e:
        print(f"❌ Fallback scraper cũng lỗi: {e}")
        print("\n💡 GỢI Ý:")
        print("   1. Kiểm tra kết nối internet / proxy")
        print("   2. Thử bật VPN nếu IP bị rate limit")
        print("   3. Chờ 15-30 phút rồi thử lại")
        return None


def run_analyzer():
    """Chạy phân tích sentiment."""
    print("\n" + "=" * 60)
    print("🧠 BƯỚC 2: PHÂN TÍCH SENTIMENT")
    print("=" * 60 + "\n")
    
    data_file = Path(__file__).parent / "data" / "raw_posts_latest.json"
    if not data_file.exists():
        print(f"❌ Chưa có dữ liệu: {data_file}")
        print("   Hãy chạy scraper trước!")
        return None
    
    try:
        from sentiment_analyzer import main as analyze_main
        classified = analyze_main()
        return classified
    except Exception as e:
        print(f"❌ Lỗi phân tích: {e}")
        import traceback
        traceback.print_exc()
        return None


def show_help():
    """Hiện hướng dẫn."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║        FACEBOOK UIT SCRAPER & SENTIMENT ANALYZER            ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Cách dùng:                                                  ║
║    py main.py              Chạy toàn bộ pipeline             ║
║    py main.py scrape       Chỉ crawl dữ liệu                ║
║    py main.py analyze      Chỉ phân tích sentiment           ║
║    py main.py fallback     Dùng fallback scraper             ║
║    py main.py install      Chỉ cài thư viện                  ║
║    py main.py help         Hiện hướng dẫn này                ║
║                                                              ║
║  Output:                                                     ║
║    data/raw_posts_latest.json       Dữ liệu thô             ║
║    data/classified_posts_latest.csv Đã phân loại             ║
║    data/report_*.txt                Báo cáo tổng hợp         ║
║    logs/                            Log files                 ║
║                                                              ║
║  An toàn:                                                    ║
║    ✅ Không cần đăng nhập Facebook                           ║
║    ✅ Random delay giữa các request                          ║
║    ✅ User-Agent rotation                                    ║
║    ✅ Chỉ crawl page PUBLIC                                  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)


def main():
    # Parse arguments
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    command = args[0].lower() if args else "all"
    
    if command == "help":
        show_help()
        return
    
    if command == "install":
        install_requirements()
        return
    
    # Luôn cài thư viện trước
    print("🔧 Kiểm tra và cài đặt thư viện...")
    install_requirements()
    
    if command == "scrape":
        run_scraper()
    elif command == "fallback":
        run_fallback_scraper()
    elif command == "analyze":
        run_analyzer()
    elif command == "all":
        # Chạy toàn bộ pipeline
        posts = run_scraper()
        
        if posts:
            classified = run_analyzer()
            
            if classified:
                print("\n" + "=" * 60)
                print("🎉 HOÀN TẤT TOÀN BỘ PIPELINE!")
                print("=" * 60)
                print(f"   📄 Dữ liệu thô:    data/raw_posts_latest.json")
                print(f"   📊 Đã phân loại:    data/classified_posts_latest.csv")
                print(f"   📋 Báo cáo:         data/report_*.txt")
                print(f"   📝 Logs:            logs/")
        else:
            print("\n⚠️ Không crawl được dữ liệu.")
            print("💡 Thử chạy: py main.py fallback")
    else:
        print(f"❌ Lệnh không hợp lệ: {command}")
        show_help()


if __name__ == "__main__":
    main()
