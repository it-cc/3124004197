# 论文查重

本项目使用 Python 3 实现论文原文和抄袭版之间的文本相似度计算，入口文件符合题目要求：

```bash
python main.py [原文文件] [抄袭版论文文件] [答案文件]
```

例如：

```bash
python main.py "测试文本/orig.txt" "测试文本/orig_0.8_add.txt" answer.txt
```

程序读取 UTF-8/UTF-8 with BOM 文本，并在答案文件中写入一个保留两位小数的 `0~1` 浮点数。运行时只使用 Python 标准库；`requirements.txt` 中的 pytest 仅用于开发测试。

## 算法

1. 使用 Unicode NFKC 和大小写折叠进行规范化。
2. 对中文连续文本生成重叠的二元字符片段；英文单词和数字作为整体词元。
3. 统计两个文件的词元频次，构造稀疏向量。
4. 使用余弦相似度作为重复率：`dot(A, B) / (|A| * |B|)`。

中文二元片段对增删改有一定容错能力，同时不需要分词词典。设两个文件总长度为 `n`，词元数为 `t`，整体时间复杂度为 `O(n + t)`，额外空间复杂度为 `O(t)`。

## 测试

运行全部测试：

```bash
pytest -q
pytest --cov=plagiarism_checker --cov=main --cov-report=term-missing -q
```

当前包含 16 个测试用例，覆盖完全相同、完全不同、增删改、中文、英文、数字、重复词、空文件、输出格式、命令行和缺失文件等情况。

性能分析：

```bash
python benchmark.py > profile.txt
```

`profile.txt` 是 Python `cProfile` 输出，可在博客中截图作为性能分析结果。
