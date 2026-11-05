# Pipeline nội dung AI

Nguồn: spec mục 9. Code: `backend/app/extract.py`, `chunking.py`, `llm.py`, `generation.py`, `jobs.py`, `worker.py`.

## Luồng

1. Admin tạo nguồn: dán văn bản, tải PDF hoặc nhập URL. `api` trích văn bản ngay trong request và trả `preview` 500 ký tự để admin kiểm tra.
2. Admin tạo job: chọn nguồn, chủ đề, loại nội dung (`flashcard`/`vocab`/`question`) và số item theo từng level. `api` ghi `generation_jobs` rồi trả ngay.
3. `worker` claim job, chia văn bản thành chunk, gọi LLM tuần tự, validate, chèn item `draft`.
4. Admin duyệt: `POST /api/admin/items/{id}/publish`. Không có đường nào tự publish.

## Trích văn bản

| Nguồn | Cách làm | Lỗi |
|---|---|---|
| Văn bản dán | `clean_text` bỏ NUL, chuẩn hoá `\r\n`, cắt khoảng trắng cuối dòng | rỗng → 422; quá 200.000 ký tự → 413 |
| PDF | `pypdf` trong threadpool, ghép text từng trang | không có text layer (bản scan) → 422 nói rõ không hỗ trợ OCR; tệp hỏng → 422; quá 20 MB → 413 |
| URL | `httpx` tải, `trafilatura` bóc nội dung chính | xem mục chống SSRF |

Byte NUL bị bỏ vì PostgreSQL không nhận `\x00` trong cột `text`; nếu để lọt, mọi lần lưu nguồn sẽ là lỗi 500.

## Chống SSRF cho URL

- Chỉ `http`/`https`; URL có userinfo bị từ chối.
- Phân giải DNS, kiểm tra **mọi** địa chỉ: từ chối loopback, private, link-local, reserved, multicast, kể cả dạng IPv4-mapped IPv6 (`::ffff:10.0.0.1`). Một địa chỉ nội bộ là cả URL bị từ chối.
- Kết nối tới đúng IP đã kiểm tra, gửi `Host` của host gốc và SNI của host gốc, nên chứng chỉ TLS vẫn được kiểm tra đúng tên miền còn DNS rebinding không đổi được đích.
- `trust_env=False`: biến `HTTP_PROXY`/`HTTPS_PROXY` trong môi trường không lái được kết nối.
- Redirect theo tay, tối đa 3 lần, mỗi lần kiểm tra lại từ đầu. Timeout 15 giây cho cả quá trình, trần 5 MB khi đang đọc.
- Chỉ nhận `text/html` và `application/xhtml+xml`.

## Prompt và schema

Một lần gọi cho mỗi chunk. Prompt nói rõ chủ đề, loại nội dung, số item từng level, thang level và schema `content`; văn bản nguồn nằm giữa `<<<` và `>>>`. Client ép `response_format={"type": "json_object"}`; nếu gateway trả 400 vì không hỗ trợ tham số này, client thử lại một lần không kèm nó rồi mới dựa vào prompt + validate + retry (spec mục 14).

Đầu ra phải là:

```json
{"items": [{"level": "easy|medium|hard|expert", "content": {"...": "..."}}]}
```

`content` theo `kind`, đúng schema pydantic của plan 2:

| kind | Trường |
|---|---|
| `flashcard` | `front`, `back` |
| `vocab` | `word`, `part_of_speech`, `meaning`, `ipa`, `examples[]` |
| `question` | `type` (`mcq`/`true_false`), `prompt`, `options[]`, `answer`, `explanation` |

Quy tắc validate: `level` phải nằm trong yêu cầu; `content` qua `parse_content`; item vượt số lượng bị bỏ; sai schema thì retry đúng một lần kèm thông báo lỗi, sai nữa thì job `failed` với lý do. Lỗi mạng/SDK không retry ở tầng này (SDK đặt `max_retries=0`): job `failed`, admin tạo job mới.

## Giới hạn mặc định

| Giới hạn | Giá trị | Biến |
|---|---|---|
| Ký tự nguồn | 200.000 | `QUIZZ_MAX_SOURCE_CHARS` |
| PDF | 20 MB | `QUIZZ_MAX_PDF_BYTES` |
| Trang tải từ URL | 5 MB | `QUIZZ_MAX_URL_BYTES` |
| Timeout URL | 15 giây | `QUIZZ_URL_TIMEOUT_SECONDS` |
| Redirect | 3 | `QUIZZ_URL_MAX_REDIRECTS` |
| Item mỗi job | 50 | `QUIZZ_MAX_JOB_ITEMS` |
| Ký tự mỗi chunk | 8.000 | `QUIZZ_LLM_CHUNK_CHARS` |

## Trùng lặp và chạy lại

Khoá chống trùng là `(topic_id, content_hash)` của plan 2. Việc chèn dùng `ON CONFLICT DO NOTHING`, nên hai worker chạy song song cũng không tạo bản thứ hai, và item `archived` vẫn chặn nội dung cũ quay lại. `result` ghi `{"created": n, "skipped": m}`.

Mỗi chunk commit riêng kèm cập nhật `result` và `heartbeat_at`. Nếu worker chết giữa đường, job bị thu hồi và chạy lại từ chunk đầu; phần đã ghi chỉ tăng `skipped`. Đổi lại, một job bị thu hồi sẽ gọi LLM lại cho các chunk đã xong.

## Hàng đợi

- Claim: `SELECT ... WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED`, rồi đặt `running` và commit ngay.
- Heartbeat mỗi 30 giây. Job `running` có heartbeat cũ hơn 5 phút bị đưa về `queued` và `attempts + 1`; đủ 3 lần thì `failed`.
- `finish` chỉ áp dụng cho job đang `running`, nên job đã bị thu hồi không bị ghi đè kết quả.
