# Tài liệu dự án

`docs/` là nguồn sự thật duy nhất (SSOT) của dự án.

| Thư mục | Nội dung |
|---|---|
| `product/` | Mục tiêu và phạm vi |
| `architecture/` | Kiến trúc, mô hình dữ liệu, SRS, triển khai, `openapi.json` |
| `decisions/` | Quyết định kiến trúc ngắn, mỗi quyết định một file |
| `specs/` | Spec thiết kế |
| `plans/` | Kế hoạch triển khai |

Thư mục nào chưa có thì tạo khi có tài liệu đầu tiên.

## Quy ước

- Thay đổi hành vi, schema hay deploy thì cập nhật tài liệu trong cùng commit.
- Hợp đồng API lấy từ OpenAPI của FastAPI: chạy `cd backend && uv run python -m scripts.export_openapi` rồi commit `architecture/openapi.json`. Không sửa tay.
- Tài liệu lệch code thì tài liệu là chuẩn cho tới khi có quyết định mới được ghi lại.

## Mục lục

- [Triển khai](architecture/deploy.md)
