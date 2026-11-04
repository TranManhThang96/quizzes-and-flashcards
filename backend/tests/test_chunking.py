import pytest

from app.chunking import chunk_text, distribute, plan_chunks


def test_chunks_respect_the_size_limit_and_keep_every_paragraph():
    text = "\n\n".join(f"Đoạn {index} " + "x" * 60 for index in range(20))

    chunks = chunk_text(text, 200)

    assert all(len(chunk) <= 200 for chunk in chunks)
    joined = " ".join(chunks)
    for index in range(20):
        assert f"Đoạn {index}" in joined


def test_a_paragraph_longer_than_the_size_is_split_at_word_boundaries():
    text = "từ " * 500

    chunks = chunk_text(text, 100)

    assert all(len(chunk) <= 100 for chunk in chunks)
    assert all(chunk == chunk.strip() for chunk in chunks)
    assert "".join(chunks).replace(" ", "") == "từ" * 500


def test_short_text_is_one_chunk():
    assert chunk_text("một đoạn ngắn", 8000) == ["một đoạn ngắn"]


def test_blank_text_has_no_chunks():
    assert chunk_text("   \n\n  ", 100) == []


def test_invalid_size_is_rejected():
    with pytest.raises(ValueError):
        chunk_text("abc", 0)


def test_counts_are_split_without_losing_any_item():
    assert distribute(7, 3) == [3, 2, 2]
    assert distribute(2, 4) == [1, 1, 0, 0]
    assert distribute(0, 3) == [0, 0, 0]


def test_plan_keeps_the_total_per_level():
    plan = plan_chunks({"easy": 5, "hard": 1}, 3)

    assert len(plan) == 3
    assert sum(chunk.get("easy", 0) for chunk in plan) == 5
    assert sum(chunk.get("hard", 0) for chunk in plan) == 1
