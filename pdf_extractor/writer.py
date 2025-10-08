"""
输出模块

职责：
- 格式化输出到 JSON/CSV/JSONL
- 统一输出接口，不包含业务逻辑
"""

import os
import csv
import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger("pdf_text")


def write_json(data: Any, file_path: str) -> None:
    """
    输出 JSON 文件。

    Args:
        data: 要输出的数据
        file_path: 输出文件路径

    Raises:
        IOError: 写入失败
    """
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Wrote JSON: {file_path}")


def write_jsonl(rows: List[Dict], file_path: str) -> None:
    """
    输出 JSONL 文件（每行一个 JSON 对象）。

    Args:
        rows: 要输出的行列表
        file_path: 输出文件路径

    Raises:
        IOError: 写入失败
    """
    with open(file_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info(f"Wrote JSONL: {file_path} ({len(rows)} rows)")


def write_csv(rows: List[Dict], file_path: str, fieldnames: List[str] = None) -> None:
    """
    输出 CSV 文件。

    Args:
        rows: 要输出的行列表
        file_path: 输出文件路径
        fieldnames: 列名列表，不指定则自动从第一行推断

    Raises:
        IOError: 写入失败
    """
    if not rows:
        logger.warning(f"No data to write to CSV: {file_path}")
        return

    if fieldnames is None:
        fieldnames = list(rows[0].keys())

    with open(file_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    logger.info(f"Wrote CSV: {file_path} ({len(rows)} rows)")


def print_json(data: Any) -> None:
    """
    输出 JSON 到 stdout。

    Args:
        data: 要输出的数据
    """
    print(json.dumps(data, ensure_ascii=False, indent=2))


def print_jsonl(rows: List[Dict], limit: int = 50) -> None:
    """
    输出 JSONL 到 stdout（预览模式）。

    Args:
        rows: 要输出的行列表
        limit: 最多输出行数
    """
    for r in rows[:limit]:
        print(json.dumps(r, ensure_ascii=False))

    if len(rows) > limit:
        print(f"... ({len(rows) - limit} more rows, use --out to save all)")


def write_auto(data: Any, file_path: str) -> None:
    """
    根据文件扩展名自动选择输出格式。

    Args:
        data: 要输出的数据
        file_path: 输出文件路径

    Raises:
        ValueError: 不支持的文件格式
        IOError: 写入失败
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".json":
        write_json(data, file_path)
    elif ext == ".jsonl":
        if isinstance(data, list):
            write_jsonl(data, file_path)
        else:
            raise ValueError(f"JSONL format requires list data, got {type(data)}")
    elif ext == ".csv":
        if isinstance(data, list):
            write_csv(data, file_path)
        else:
            raise ValueError(f"CSV format requires list data, got {type(data)}")
    else:
        raise ValueError(f"Unsupported file format: {ext}")


def print_auto(data: Any, mode: str = "json") -> None:
    """
    根据模式自动选择输出格式到 stdout。

    Args:
        data: 要输出的数据
        mode: "json" 或 "jsonl"
    """
    if mode == "jsonl" and isinstance(data, list):
        print_jsonl(data)
    else:
        print_json(data)
