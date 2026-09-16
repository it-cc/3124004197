"""使用 cProfile 进行本地性能分析的小型基准程序。"""

from __future__ import annotations

import cProfile
import pstats

from plagiarism_checker import similarity_from_text


def run() -> None:
    original = "软件工程课程要求进行需求分析、设计、编码和测试。" * 5000
    modified = "软件工程课程要求进行需求分析、设计、编码和测试，并记录测试结果。" * 5000
    for _ in range(20):
        similarity_from_text(original, modified)


if __name__ == "__main__":
    profiler = cProfile.Profile()
    profiler.enable()
    run()
    profiler.disable()
    pstats.Stats(profiler).sort_stats("cumulative").print_stats(12)
