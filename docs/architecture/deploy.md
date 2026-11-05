# Triển khai

Cập nhật lần cuối cùng với plan pipeline nội dung AI. Có ba container: `db` (PostgreSQL 17.11), `api` (FastAPI) và `worker` (cùng image với `api`, lệnh `python -m app.worker`). `web` được thêm bởi plan 4.

## Biến môi trường

Sao `deploy/.env.example` thành `deploy/.env` và điền. File này không được commit.

| Biến | Ý nghĩa |
|---|---|
| `POSTGRES_PASSWORD` | Mật khẩu DB. Dùng `openssl rand -hex 24` (chỉ hex vì nó nằm trong URL) |
| `QUIZZ_APP_ORIGIN` | Origin công khai, ví dụ `https://quizz.thangtm.io.vn`. Request ghi có `Origin` khác sẽ bị 403 |
| `QUIZZ_ENVIRONMENT` | `prod` tắt docs và `/api/openapi.json` |
| `QUIZZ_COOKIE_SECURE` | `true` ở production. Chỉ đặt `false` khi thử qua HTTP thuần |
| `QUIZZ_APP_TIMEZONE` | Múi giờ tính ngày của hàng đợi và streak. Mặc định `Asia/Ho_Chi_Minh` |
| `FORWARDED_ALLOW_IPS` | Bắt buộc. Peer mà uvicorn tin `X-Forwarded-*`; phải là gateway của bridge compose. Xem mục dưới |
| `QUIZZ_LLM_BASE_URL` | Base URL của gateway tương thích OpenAI, ví dụ `https://gateway.example/v1`. Chỉ `worker` nhận |
| `QUIZZ_LLM_API_KEY` | Key gateway. Không lưu DB, không ra frontend |
| `QUIZZ_LLM_MODEL` | Tên model mà gateway chấp nhận |

Các biến tinh chỉnh (không cần khai báo, có mặc định): `QUIZZ_LLM_CHUNK_CHARS` (8000), `QUIZZ_LLM_TIMEOUT_SECONDS` (120), `QUIZZ_MAX_SOURCE_CHARS` (200000), `QUIZZ_MAX_PDF_BYTES` (20971520), `QUIZZ_MAX_URL_BYTES` (5242880), `QUIZZ_URL_TIMEOUT_SECONDS` (15), `QUIZZ_URL_MAX_REDIRECTS` (3), `QUIZZ_MAX_JOB_ITEMS` (50), `QUIZZ_WORKER_POLL_SECONDS` (2), `QUIZZ_WORKER_HEARTBEAT_SECONDS` (30), `QUIZZ_WORKER_STALE_SECONDS` (300), `QUIZZ_WORKER_MAX_ATTEMPTS` (3). Compose chỉ truyền các biến được liệt kê trong `environment:` của từng service; muốn đổi một biến tinh chỉnh, thêm nó vào `environment:` của `api` hoặc `worker` (đừng dựa vào `deploy/.env` một mình). `PDF_TIMEOUT_SECONDS` (60) là hằng trong `app/extract.py`, không đọc từ env.

## `FORWARDED_ALLOW_IPS`

Cổng của `api` chỉ publish ở `127.0.0.1`, nên kết nối từ nginx trên host đi vào container qua gateway của bridge chứ không phải `127.0.0.1`. uvicorn chỉ đọc `X-Forwarded-For`/`X-Forwarded-Proto` từ peer nằm trong danh sách này. Khi chỉ có `db` và `api`, giá trị `*` còn chấp nhận được; từ plan này có thêm container `worker` trên cùng mạng nên `*` sẽ cho phép container bất kỳ giả IP client, phá giới hạn đăng nhập theo IP. `docker-compose.yml` vì thế đặt `${FORWARDED_ALLOW_IPS:?...}`: không có giá trị thì Compose dừng, không lặng lẽ dùng `*`.

Lấy giá trị thật:

    cd deploy
    docker compose up -d db
    docker network inspect quizz_default \
      --format '{{(index .IPAM.Config 0).Gateway}}'

Tên mạng là `quizz_default` vì `docker-compose.yml` đặt `name: quizz`. Mạng bị xoá và tạo lại khi `docker compose down` (không có `-v`) rồi `up`; gateway thường giữ nguyên nhưng **phải đọc lại**, nhất là khi máy có nhiều mạng Docker.

Kiểm chứng sau khi dựng stack (đã làm ở plan 1 với `FORWARDED_ALLOW_IPS=*`, chưa làm với giá trị gateway):

    # 1) Từ host: X-Forwarded-For phải được tin.
    curl -s -o /dev/null -X POST http://127.0.0.1:8000/api/auth/login \
      -H 'Origin: https://quizz.thangtm.io.vn' -H 'Content-Type: application/json' \
      -H 'X-Forwarded-For: 198.51.100.77' \
      --data '{"username":"nobody","password":"wrong-password"}'
    docker compose exec -T db psql -U quizz -d quizz \
      -c "select ip from login_attempts order by id desc limit 1"
    # Kỳ vọng: 198.51.100.77

    # 2) Từ container khác (worker): X-Forwarded-For phải bị bỏ qua.
    docker compose exec -T worker python - <<'PY'
    import urllib.request
    req = urllib.request.Request(
        "http://api:8000/api/auth/login",
        data=b'{"username":"nobody","password":"wrong-password"}',
        headers={"Origin": "https://quizz.thangtm.io.vn",
                 "Content-Type": "application/json",
                 "X-Forwarded-For": "203.0.113.9"},
    )
    try:
        urllib.request.urlopen(req)
    except Exception as exc:
        print(exc.code)
    PY
    docker compose exec -T db psql -U quizz -d quizz \
      -c "select ip from login_attempts order by id desc limit 1"
    # Kỳ vọng: IP của container worker (172.x), KHÔNG phải 203.0.113.9

Hai lệnh trên ghi vào `login_attempts`; xoá sau khi thử: `delete from login_attempts where username = 'nobody'`.

## Chạy lần đầu

```bash
cd deploy
docker compose build
docker compose up -d db
docker compose run --rm api alembic upgrade head
docker compose up -d api worker
docker compose exec api python -m app.cli create-admin --username <tên>
```

Lệnh cuối hỏi mật khẩu bằng `getpass`, cần terminal tương tác. Đã kiểm chứng đường `QUIZZ_ADMIN_PASSWORD`; đường `getpass` chưa chạy thử.

Cập nhật phiên bản mới: `docker compose build`, `docker compose run --rm api alembic upgrade head`, rồi `docker compose up -d api worker`. `worker` không tự chạy migration.

## Worker

`worker` poll bảng `generation_jobs` mỗi 2 giây, claim job bằng `SELECT ... FOR UPDATE SKIP LOCKED`, gửi heartbeat mỗi 30 giây và ghi kết quả vào `result`/`error`. Job `running` có heartbeat cũ hơn 5 phút bị đưa về `queued` với `attempts + 1`; đủ 3 lần thì `failed`. SIGTERM dừng vòng lặp sau khi job hiện tại xong.

```bash
docker compose logs -f worker
docker compose ps worker
```

Xem nhanh hàng đợi:

```bash
docker compose exec -T db psql -U quizz -d quizz -c \
  "select id, status, attempts, left(coalesce(error, ''), 80) as error from generation_jobs order by id desc limit 10"
```

Đưa một job `failed` về hàng đợi để chạy lại (kết quả trùng vẫn bị chặn theo `content_hash`, nên chạy lại không tạo bản sao):

```bash
docker compose exec -T db psql -U quizz -d quizz -c \
  "update generation_jobs set status = 'queued', attempts = 0, error = null where id = <id>"
```

## nginx

Hai file mẫu nằm trong `deploy/nginx/`:

- `quizz-limit.conf` thuộc ngữ cảnh `http {}`. Đặt vào `/etc/nginx/conf.d/`. Nó khai báo vùng `limit_req` cho trang đăng nhập.
- `quizz-api.conf` thuộc ngữ cảnh `server {}` của `quizz.thangtm.io.vn`. Thêm `include` vào server block có TLS sẵn.

Plan này không sửa nginx: location `/api/` đã có `client_max_body_size 25m` (đủ cho PDF 20 MB cộng overhead multipart) và `proxy_read_timeout 120s` (đủ cho việc tải URL và trích PDF trong một request). Job sinh nội dung chạy ở `worker`, không đi qua nginx.

Điểm quan trọng: `X-Forwarded-For` được **ghi đè** bằng `$remote_addr`, không nối thêm. API lấy phần tử đầu làm IP client cho việc khóa đăng nhập, nên header do client gửi phải bị bỏ. Đã kiểm chứng với nginx 1.29 trong container: header giả `198.51.100.77, 203.0.113.10` không xuất hiện trong `login_attempts.ip`. Cấu hình trên nginx thật của VPS chưa được thử.

Sau khi sửa nginx: `nginx -t` rồi mới `nginx -s reload`.

## Mở khóa đăng nhập

Khóa thử sai tính theo cả username lẫn IP, nên người lạ đoán sai 5 lần với username của admin là khóa được admin 15 phút. Khóa tự mở sau 15 phút kể từ lần sai cuối. Muốn mở ngay:

```bash
cd deploy
docker compose exec -T db psql -U quizz -d quizz -c "delete from login_attempts where username = '<tên>'"
```

Bị khóa theo IP thì thay điều kiện bằng `ip = '<địa chỉ>'`.

## Sao lưu và khôi phục

`deploy/backup/backup.sh` ghi `pg_dump` dạng custom vào `BACKUP_DIR` (mặc định `/var/backups/quizz`, nên đặt ngoài volume Docker, tốt nhất khác ổ đĩa) và giữ `KEEP` bản gần nhất (mặc định 14). Dump lỗi hoặc rỗng không để lại file hợp lệ.

Bảng `sources` chứa văn bản đã trích (tới 200.000 ký tự mỗi nguồn), nên dump sẽ lớn dần; script không cần đổi, chỉ cần để ý dung lượng đĩa. `worker` không giữ trạng thái riêng: mọi thứ nằm trong DB, khôi phục xong là job `queued` tự chạy tiếp.

Ví dụ cron (chưa chạy thử), chạy bằng user có quyền dùng Docker:

```
0 3 * * * /đường/dẫn/repo/deploy/backup/backup.sh >> /var/log/quizz-backup.log 2>&1
```

Khôi phục vào một database mới (quy trình này đã được kiểm chứng):

```bash
cd deploy
docker compose exec -T db psql -U quizz -d postgres -c "create database quizz_restore"
docker compose exec -T db pg_restore -U quizz -d quizz_restore --no-owner < /var/backups/quizz/quizz-<thời điểm>.dump
docker compose exec -T db psql -U quizz -d quizz_restore -c "select count(*) from users"
```

Khôi phục đè lên database đang chạy **chưa** được kiểm chứng. Cách an toàn là khôi phục vào database mới như trên, kiểm tra, rồi mới quyết định chuyển.

## Hợp đồng API

`docs/architecture/openapi.json` được sinh từ code, không viết tay:

```bash
cd backend && uv run python -m scripts.export_openapi
```
