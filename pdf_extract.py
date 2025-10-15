"""
命令行接口模块（主入口）

职责：
- 解析命令行参数
- 协调各模块完成任务
- 数据流：reader → preprocessor → extractor → validator → writer
"""

import sys
import logging
import argparse

from pdf_extractor.reader import (
    prepare_ocr_pdf,
    read_pdf_elements,
    ensure_file_exists,
)
from pdf_extractor.preprocessor import merge_adjacent_lines, clean_text, split_abnormal_height_lines, split_wide_lines
from pdf_extractor.extractor import (
    truncate_at_marker,
    extract_by_rules,
    extract_invoice_items,
)
from pdf_extractor.validator import validate_invoice_data
from pdf_extractor.writer import write_auto, print_auto, print_jsonl

logger = logging.getLogger("pdf_text")
DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def parse_pages_arg(pages_str: str) -> list[int] | None:
    """
    解析页码参数字符串。

    Args:
        pages_str: 页码字符串，如 "1,3,5" 或 "1-3"

    Returns:
        页码列表（1-based），或 None 表示全部
    """
    if not pages_str:
        return None

    out = []
    for part in pages_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
            out.extend(list(range(a, b + 1)))
        else:
            out.append(int(part))

    return sorted(set(out))


def setup_parser() -> argparse.ArgumentParser:
    """设置命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description="HS Code Audit Tool - PDF Invoice Text Extraction and Validation",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # 通用参数函数
    def add_common_args(p):
        """添加通用参数"""
        p.add_argument("pdf", help="PDF file path")
        p.add_argument(
            "--out",
            default="",
            help="Output file path, stdout if not specified"
        )
        p.add_argument(
            "--truncate",
            default="SAY U.S.DOLLARS",
            help="Truncate marker (default: 'SAY U.S.DOLLARS', use empty string to disable)"
        )
        p.add_argument(
            "--column-config",
            default="default",
            help="Column configuration key name in column_config.json (default: 'default')"
        )

    # extract subcommand
    extract_parser = subparsers.add_parser(
        "extract",
        help="Extract fields by page+line using rules file"
    )
    add_common_args(extract_parser)
    extract_parser.add_argument(
        "--rules",
        required=True,
        help="Rules file path (JSON)"
    )

    # auto subcommand
    auto_parser = subparsers.add_parser(
        "auto",
        help="Auto extract invoice items with 3-layer validation"
    )
    add_common_args(auto_parser)
    auto_parser.add_argument(
        "--debug",
        type=int,
        default=-1,
        choices=[-1, 0, 1, 2, 3],
        help="Debug mode with preprocessing level: -1=off, 0=raw, 1=truncated, 2=split, 3=merged (default: -1)"
    )

    return parser


def run_extract(args) -> None:
    """执行 extract 子命令"""
    import json

    # 1. 读取规则文件
    ensure_file_exists(args.rules)
    with open(args.rules, "r", encoding="utf-8") as f:
        rules = json.load(f)

    # 2. 读取 PDF（自动 OCR 兜底）
    rows = read_pdf_elements(args.pdf, mode="lines")

    # 如果内容为空，尝试 OCR
    if not rows or all(not r.get("text", "").strip() for r in rows):
        logger.info("PDF content is empty, trying OCR...")
        src = prepare_ocr_pdf(args.pdf, "chi_sim+eng")
        rows = read_pdf_elements(src, mode="lines")

    # 3. 预处理（截断 + 拆分异常行高 + 智能合并）
    if args.truncate:
        rows = truncate_at_marker(rows, args.truncate)
    rows = split_abnormal_height_lines(rows)
    rows = merge_adjacent_lines(rows)
    rows = split_wide_lines(rows)

    # 4. 提取字段
    results = extract_by_rules(rows, rules)
    data = {"file": args.pdf, "results": results}

    # 5. 输出
    if args.out:
        write_auto(data, args.out)
        print(f"Wrote: {args.out}")
    else:
        print_auto(data, mode="json")


def run_auto(args) -> None:
    """执行 auto 子命令"""
    # 1. 读取 PDF（自动 OCR 兜底）
    rows = read_pdf_elements(args.pdf, mode="lines")

    # 如果内容为空，尝试 OCR
    if not rows or all(not r.get("text", "").strip() for r in rows):
        logger.info("PDF content is empty, trying OCR...")
        src = prepare_ocr_pdf(args.pdf, "chi_sim+eng")
        rows = read_pdf_elements(src, mode="lines")

    # Debug: 输出 level 0 (raw) - 在任何处理之前
    if args.debug == 0:
        debug_file = args.pdf.replace(".pdf", "_debug_raw.csv")
        write_auto(rows, debug_file)
        logger.info(f"[DEBUG] Level 0 (raw): {len(rows)} lines -> {debug_file}")
        return  # level 0 只输出 raw 数据，不执行后续处理

    # 2. 截断（可选）
    if args.truncate:
        rows = truncate_at_marker(rows, args.truncate)

    # Debug: 输出 level 1 (truncated)
    if args.debug == 1:
        debug_file = args.pdf.replace(".pdf", "_debug_truncated.csv")
        write_auto(rows, debug_file)
        logger.info(f"[DEBUG] Level 1 (truncated): {len(rows)} lines -> {debug_file}")
        return  # level 1 只输出截断后数据，不执行后续处理

    # 3. 预处理（拆分异常行高）
    rows = split_abnormal_height_lines(rows)
    rows = split_wide_lines(rows)

    # Debug: 输出 level 2 (split)
    if args.debug == 2:
        debug_file = args.pdf.replace(".pdf", "_debug_split.csv")
        write_auto(rows, debug_file)
        logger.info(f"[DEBUG] Level 2 (split): {len(rows)} lines -> {debug_file}")
        return  # level 2 只输出拆分后数据，不执行后续处理

    # 4. 合并相邻行
    rows = merge_adjacent_lines(rows)

    # Debug: 输出 level 3 (merged)
    if args.debug == 3:
        debug_file = args.pdf.replace(".pdf", "_debug_merged.csv")
        write_auto(rows, debug_file)
        logger.info(f"[DEBUG] Level 3 (merged): {len(rows)} lines -> {debug_file}")
        return  # level 3 只输出合并后数据，不执行后续处理

    lines = [r["text"] for r in rows]

    # 5. 提取发票货物信息（传入 pdf_path 和 rows 以启用表格提取）
    groups, global_qty, global_usd, extraction_errors = extract_invoice_items(
        lines,
        debug=False,
        pdf_path=args.pdf,
        rows=rows,
        column_config=args.column_config
    )

    # 5. 校验
    validation_errors = validate_invoice_data(groups, global_qty, global_usd)

    # 6. 统一所有错误
    all_errors = extraction_errors + validation_errors
    for error in all_errors:
        logger.warning(error)

    # 7. 输出
    total_items = sum(len(g["items"]) for g in groups)
    output = {
        "goods_blocks": groups,
        "total_blocks": len(groups),
        "total_items": total_items,
        "global_total_quantity": global_qty,
        "global_total_usd": global_usd,
        "errors": all_errors,
        "file": args.pdf
    }

    if args.out:
        write_auto(output, args.out)
        print(f"Extracted {len(groups)} block(s), {total_items} item(s) -> {args.out}")
    else:
        print_auto(output, mode="json")


def main():
    """CLI 主入口"""
    logging.basicConfig(level=logging.INFO, format=DEFAULT_LOG_FORMAT)

    parser = setup_parser()
    args = parser.parse_args()

    # 子命令模式
    if args.command == "extract":
        run_extract(args)
    elif args.command == "auto":
        run_auto(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
