"""论文查重程序的命令行入口。"""

from __future__ import annotations

import argparse
import sys

from plagiarism_checker import calculate_similarity, format_similarity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="计算两个 UTF-8 文本文件的重复率。"
    )
    parser.add_argument("original", help="原文文件的绝对路径")
    parser.add_argument("plagiarism", help="抄袭版文件的绝对路径")
    parser.add_argument("answer", help="答案文件的绝对路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        similarity = calculate_similarity(args.original, args.plagiarism)
        with open(args.answer, "w", encoding="utf-8", newline="\n") as answer_file:
            answer_file.write(format_similarity(similarity))
    except (OSError, UnicodeError, TypeError, ValueError) as error:
        print(f"处理失败: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
