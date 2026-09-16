from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from plagiarism_checker import (
    cosine_similarity,
    format_similarity,
    normalize_text,
    similarity_from_text,
    term_frequencies,
    tokenize,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_identical_chinese_text_has_full_similarity():
    assert similarity_from_text("今天是星期天。", "今天是星期天。") == pytest.approx(1.0)


def test_punctuation_and_whitespace_do_not_change_similarity():
    assert similarity_from_text("天气 晴，今天去看电影", "天气晴! 今天去看电影。") == pytest.approx(1.0)


def test_completely_different_text_has_zero_similarity():
    assert similarity_from_text("苹果香蕉", "计算机网络") == pytest.approx(0.0)


def test_empty_documents_have_zero_similarity():
    assert similarity_from_text("", "") == 0.0
    assert similarity_from_text("有内容", "") == 0.0


def test_single_chinese_character_is_a_valid_token():
    assert tokenize("啊") == ["啊"]


def test_chinese_edit_retains_partial_similarity():
    value = similarity_from_text("今天是星期天，天气晴。", "今天是周天，天气晴朗。")
    assert 0.0 < value < 1.0


def test_addition_reduces_but_does_not_remove_similarity():
    value = similarity_from_text("软件工程需要测试。", "软件工程需要测试，并且需要持续集成。")
    assert 0.0 < value < 1.0


def test_english_is_case_insensitive_and_tokenized_by_word():
    assert tokenize("Python-based API, API!") == ["python-based", "api", "api"]
    assert similarity_from_text("Python is useful", "python IS useful") == pytest.approx(1.0)


def test_numbers_are_compared_as_tokens():
    assert similarity_from_text("版本 2024", "版本 2024") == pytest.approx(1.0)
    assert similarity_from_text("版本 2024", "版本 2025") < 1.0


def test_term_frequency_counts_repeated_terms():
    frequencies = term_frequencies("测试测试")
    assert frequencies["测试"] == 2
    assert frequencies["试测"] == 1
    assert len(frequencies) == 2


def test_cosine_similarity_handles_sparse_vectors():
    assert cosine_similarity(term_frequencies("abc abc"), term_frequencies("abc")) == pytest.approx(1.0)
    assert cosine_similarity(term_frequencies("abc"), term_frequencies("xyz")) == 0.0
    assert cosine_similarity({"abc": 0}, {"abc": 0}) == 0.0


def test_output_is_rounded_to_two_decimal_places():
    assert format_similarity(1.0) == "1.00"
    assert format_similarity(0.1239) == "0.12"
    assert format_similarity(0.9999) == "1.00"


def test_invalid_output_value_is_rejected():
    with pytest.raises(ValueError):
        format_similarity(float("nan"))
    with pytest.raises(ValueError):
        format_similarity(1.1)


def test_text_normalization_rejects_non_string_values():
    with pytest.raises(TypeError):
        normalize_text(None)  # type: ignore[arg-type]  # 验证非字符串输入保护


def test_command_line_entry_point_reads_and_writes_files(tmp_path: Path):
    original = tmp_path / "original.txt"
    plagiarism = tmp_path / "plagiarism.txt"
    answer = tmp_path / "answer.txt"
    original.write_text("今天是星期天，天气晴。", encoding="utf-8")
    plagiarism.write_text("今天是周天，天气晴朗。", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), str(original), str(plagiarism), str(answer)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert answer.read_text(encoding="utf-8") == "0.62"


def test_command_line_reports_missing_input_without_crashing(tmp_path: Path):
    answer = tmp_path / "answer.txt"
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), str(tmp_path / "missing.txt"), "x.txt", str(answer)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "处理失败" in result.stderr
    assert not answer.exists()
