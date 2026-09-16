"""论文查重的核心文本相似度计算函数。

实现只使用 Python 标准库，保证程序可以在干净的 Python 3 环境中运行。
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

_TOKEN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+|[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_CJK_SEPARATOR_PATTERN = re.compile(
    r"(?<=[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])[\s\W_]+"
    r"(?=[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])"
)
def normalize_text(text: str) -> str:
    """统一兼容的 Unicode 表示形式和英文字母大小写。"""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return unicodedata.normalize("NFKC", text).casefold()


def _tokens_from_cjk_run(run: str) -> Iterable[str]:
    if len(run) == 1:
        yield run
        return
    for index in range(len(run) - 1):
        yield run[index : index + 2]


def tokenize(text: str) -> list[str]:
    """生成可比较的词元，同时忽略空白和标点。

    中文使用重叠的字符二元片段表示。中文字符之间的分隔符会被移除，
    因此排版变化不会影响比较结果。
    """

    normalized = normalize_text(text)
    # 中文字符之间的空格和标点属于排版分隔符，不是比较所需的内容。
    normalized = _CJK_SEPARATOR_PATTERN.sub("", normalized)
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(normalized):
        token = match.group(0)
        if _CJK_PATTERN.fullmatch(token[0]):
            tokens.extend(_tokens_from_cjk_run(token))
        else:
            tokens.append(token)
    return tokens


def term_frequencies(text: str) -> Counter[str]:
    """构造一个文档的稀疏词频向量。"""

    return Counter(tokenize(text))


def cosine_similarity(first: Counter[str], second: Counter[str]) -> float:
    """计算两个稀疏词频向量的余弦相似度。"""

    if not first or not second:
        return 0.0

    common_terms = first.keys() & second.keys()
    dot_product = sum(first[token] * second[token] for token in common_terms)
    first_norm = math.sqrt(sum(value * value for value in first.values()))
    second_norm = math.sqrt(sum(value * value for value in second.values()))
    if first_norm == 0.0 or second_norm == 0.0:
        return 0.0
    return dot_product / (first_norm * second_norm)


def similarity_from_text(first: str, second: str) -> float:
    """计算两段文本未经四舍五入的重复率。"""

    return cosine_similarity(term_frequencies(first), term_frequencies(second))


def calculate_similarity(original_path: str | Path, plagiarism_path: str | Path) -> float:
    """读取两个 UTF-8 文本文件并返回重复率。"""

    original = Path(original_path).read_text(encoding="utf-8-sig")
    plagiarism = Path(plagiarism_path).read_text(encoding="utf-8-sig")
    return similarity_from_text(original, plagiarism)


def format_similarity(value: float) -> str:
    """按照题目要求将重复率格式化为两位小数。"""

    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("similarity must be between 0 and 1")
    return f"{value:.2f}"
