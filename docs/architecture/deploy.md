# Triển khai

Cập nhật lần cuối cùng với plan nền tảng backend. Hiện có hai container: `db` (PostgreSQL 17.11) và `api`. `web` và `worker` được thêm bởi các plan sau.

## Biến môi trường

Sao `deploy/.env.example` thành `deploy/.env` và điền. File này không được commit.

| Biến | Ý nghĩa |
|---|---|
| `POSTGRES_PASSWORD` | Mật khẩu DB. Dùng `openssl rand -hex 24` (chỉ hex vì nó nằm trong URL) |
| `QUIZZ_APP_ORIGIN` | Origin công khai, ví dụ `https://quizz.thangtm.io.vn`. Request ghi có `Origin` khác sẽ bị 403 |
| `QUIZZ_ENVIRONMENT` | `prod` tắt docs và `/api/openapi.json` |
| `QUIZZ_COOKIE_SECURE` | `true` ở production. Chỉ đặt `false` khi thử qua HTTP thuần |
| `FORWARDED_ALLOW_IPS` | Các peer mà uvicorn tin `X-Forwarded-*`. `*` chỉ an toàn khi `api` là container duy nhất trong mạng compose (cổng chỉ publish ở `127.0.0.1`, peer còn lại duy nhất là nginx trên host). Plan nào thêm `web` hoặc `worker` phải thay `*` bằng địa chỉ gateway của bridge, nếu không container khác giả được IP client |

## Chạy lần đầu

```bash
cd deploy
docker compose build
docker compose up -d db
docker compose run --rm api alembic upgrade head
docker compose up -d api
docker compose exec api python -m app.cli create-admin --username <tên>
```

Lệnh cuối hỏi mật khẩu bằng `getpass`, cần terminal tương tác. Đã kiểm chứng đường `QUIZZ_ADMIN_PASSWORD`; đường `getpass` chưa chạy thử.

Cập nhật phiên bản mới: `docker compose build`, `docker compose run --rm api alembic upgrade head`, rồi `docker compose up -d api`.

## nginx

Hai file mẫu nằm trong `deploy/nginx/`:

- `quizz-limit.conf` thuộc ngữ cảnh `http {}`. Đặt vào `/etc/nginx/conf.d/`. Nó khai báo vùng `limit_req` cho trang đăng nhập.
- `quizz-api.conf` thuộc ngữ cảnh `server {}` của `quizz.thangtm.io.vn`. Thêm `include` vào server block có TLS sẵn.

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
