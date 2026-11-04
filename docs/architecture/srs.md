# SRS: cách tính lịch ôn

Hàm duy nhất quyết định lịch là `backend/app/srs.py:schedule(state, grade, now)`.
Đổi tham số ở đây, không rải logic sang router.

Trạng thái mới: `ease = 2.5`, `reps = 0`, `lapses = 0`, `interval_days = 0`, `due_at = now`.

| Lần chấm | `interval_days` | `ease` | `reps` | `lapses` | `due_at` |
|---|---|---|---|---|---|
| `again` | 0 | `max(1.3, ease - 0.2)` | 0 | +1 | `now + 10 phút` |
| `hard` | `max(1, round(interval_days * 1.2))` | `max(1.3, ease - 0.15)` | giữ | giữ | `now + interval_days` |
| `good` | `1` nếu `reps = 0`, `3` nếu `reps = 1`, còn lại `round(interval_days * ease)` | giữ | +1 | giữ | `now + interval_days` |
| `easy` | `max(g + 1, round(g * 1.3))` với `g` là interval của `good` | +0.15 | +1 | giữ | `now + interval_days` |

`round` là làm tròn nửa lên (`12.5 -> 13`), không phải banker's rounding của Python.

Câu quiz chỉ nhận `good` (đúng) hoặc `again` (sai); `hard`/`easy` chỉ dành cho thẻ.

Đổi sang FSRS sau này chỉ cần thay thân `schedule` và thêm migration cho cột mới.
