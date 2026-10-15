# Facebook UIT Scraper & Sentiment Analyzer

Hệ thống tự động thu thập bài viết từ Facebook của **Trường Đại học Công nghệ Thông tin - ĐHQG TP.HCM (UIT)** và phân loại cảm xúc (Tích cực / Tiêu cực / Trung lập) phục vụ bài tập môn học / đề tài nghiên cứu.

---

## 📌 1. KẾT QUẢ ĐƯỢC LƯU Ở ĐÂU?

Tất cả kết quả xử lý và phân loại được lưu trữ trong thư mục [`data/`](data/):

| Tên file kết quả | Định dạng | Nội dung chi tiết |
| :--- | :---: | :--- |
| **`data/classified_posts_latest.csv`** | **Excel / CSV** | **Bảng dữ liệu kết quả phân loại chi tiết** cho từng bài viết. Bao gồm các cột quan trọng:<br>• `page`: Nguồn (`UIT.Fanpage` hoặc `UITconfess`)<br>• `text`: Nội dung bài viết / confession<br>• `likes`, `comments`, `shares`: Chỉ số tương tác<br>• **`sentiment`**: Nhãn sắc thái (**`positive`**, **`negative`**, **`neutral`**)<br>• **`sentiment_score`**: Điểm số cảm xúc (từ `-1.0` đến `+1.0`)<br>• **`matched_keywords`**: Các từ khóa khen / chê phát hiện được<br>• **`is_about_uit`**: Đánh giá bài viết có liên quan trực tiếp đến UIT không (`True`/`False`) |
| **`data/classified_posts_latest.json`** | **JSON** | Toàn bộ dữ liệu đã phân loại ở định dạng JSON để tiện tích hợp API / lập trình web. |
| **`data/report_20261015_083048.txt`** | **Báo cáo Text** | **Báo cáo tổng kết thống kê**: Tỷ lệ phần trăm các nhóm bài viết, chi tiết theo từng page, danh sách **Top 5 bài viết tích cực nhất** và **Top bài viết tiêu cực nhất**. |
| **`data/raw_posts_latest.csv`** | **CSV** | Dữ liệu bài viết thô sau khi thu thập từ Facebook (đã lọc rác anti-bot). |
| **`data/raw_posts_latest.json`** | **JSON** | Dữ liệu bài viết thô dạng JSON. |

---

## 📊 2. TỔNG KẾT KẾT QUẢ ĐÃ PHÂN LOẠI

Dữ liệu mới nhất gồm **48 bài viết & confession thực tế** sau khi được làm sạch:

| Nhóm sắc thái | Số lượng | Tỷ lệ (%) | Ví dụ nội dung tiêu biểu |
| :--- | :---: | :---: | :--- |
| ✅ **Tích cực (Positive)** | **18 bài** | **37.5%** | • **CFS #3376** (+0.820): Khen áo UIT Job Fair đẹp.<br>• **CFS #3684** (+0.820): Lời cảm ơn bạn bè làm chung đồ án & khóa luận tốt nghiệp.<br>• Phong trào thể thao chạy bộ rèn luyện sinh viên UIT. |
| ❌ **Tiêu cực (Negative)** | **4 bài** | **8.3%** | • **CFS #3346** (-0.400): Bức xúc việc làm bài tập nhóm, nhóm trưởng giao việc sát deadline.<br>• **CFS #3344** (-0.340): Phàn nàn về sự bất công trong lớp học. |
| ⚪ **Trung lập (Neutral)** | **26 bài** | **54.2%** | • Thông báo khai khóa, ngày hội việc làm UIT Career Day.<br>• Hỏi đáp thủ tục xét điểm rèn luyện, đăng ký môn học, tìm đồ rơi ở cổng trường. |

---

## 🎯 3. TARGET PAGES

1. **UIT Fanpage**: [https://www.facebook.com/UIT.Fanpage](https://www.facebook.com/UIT.Fanpage) (Thông tin chính thức từ nhà trường)
2. **UIT Confessions**: [https://www.facebook.com/UITconfess](https://www.facebook.com/UITconfess) (Tâm sự, ý kiến sinh viên)

---

## ⚙️ 4. HƯỚNG DẪN CÀI ĐẶT & CHẠY

### Bước 1: Cài đặt thư viện
```bash
py -m pip install -r requirements.txt
py -m playwright install chromium
```

### Bước 2: Chạy toàn bộ chương trình
```bash
py main.py
```
*Chương trình sẽ tự động kiểm tra tài khoản trong `.env` để chạy Scraper V3 (nếu có), hoặc tự động chạy Scraper V2 (ẩn danh) nếu không có tài khoản, sau đó tự động chạy phân loại sentiment và xuất báo cáo.*

### Các lệnh chạy riêng lẻ:
```bash
py main.py scrape     # Chỉ thu thập dữ liệu bài viết mới
py clean_dataset.py   # Lọc rác và làm sạch dữ liệu
py main.py analyze    # Chỉ chạy phân tích sentiment trên dữ liệu hiện có
```

---

## 🛡️ 5. CƠ CHẾ AN TOÀN & BẢO MẬT (ANTI-BAN)

- **Bảo mật tài khoản tuyệt đối**: Thông tin đăng nhập được lưu tại file `.env` và session cookies tại thư mục `cookies/`. Cả hai đã được cấu hình trong `.gitignore`, **không bao giờ bị đưa lên GitHub**.
- **Playwright Stealth**: Tự động vô hiệu hóa cờ nhận diện bot (`navigator.webdriver`), giả lập danh sách plugin và kích thước màn hình người dùng thật.
- **Vượt Login Wall không cần tương tác**: Tự động triệt tiêu các popup bắt đăng nhập bằng DOM injection và mở khóa thuộc tính cuộn trang.
- **Random Human Delay**: Thêm độ trễ ngẫu nhiên (2 - 4 giây) giữa các lần cuộn để mô phỏng hành vi đọc của người thật, tránh kích hoạt rate limit của Facebook.

---

## 🧠 6. PHƯƠNG PHÁP PHÂN TÍCH SENTIMENT (HYBRID MODEL)

Điểm cảm xúc được tính theo công thức lai:

$$\text{Final Score} = (\text{NLP Score} \times 0.6) + (\text{Keyword Score} \times 0.4)$$

1. **Mô hình NLP `underthesea` (Trọng số 60%)**: Phân tích cú pháp và ngữ nghĩa câu tiếng Việt chuẩn.
2. **Bộ từ điển đặc thù UIT (Trọng số 40%)**: Tập luật từ vựng học đường (khen giảng viên, khen cơ sở vật chất, học bổng vs. rớt môn, nợ môn, bất công, áp lực...).
