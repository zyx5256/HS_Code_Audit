"""
HS Code 审计主程序
整合 PDF 提取、Excel 提取和对比功能
"""
import os
import sys
import json
import csv
import logging
import argparse
import tempfile
from pathlib import Path
from datetime import datetime

# 导入各模块的主函数
from excel_extractor import extract_item_hscode_mapping
from comparator import compare_hscode, HSCodeError

logger = logging.getLogger(__name__)


def extract_pdf_data(
    pdf_path: str,
    output_dir: str,
    truncate_marker: str = "SAY U.S.DOLLARS",
    ocr_lang: str = None,
    debug_level: int = None
) -> dict:
    """
    从 PDF 提取发票数据（调用 pdf_extract）

    参数:
        pdf_path: PDF 文件路径
        output_dir: 输出目录
        truncate_marker: 截断标记（默认 "SAY U.S.DOLLARS"）
        ocr_lang: OCR 语言（如 "chi_sim+eng"）
        debug_level: Debug 级别（None=保存JSON, 0-3=在该阶段停止并保存CSV）

    返回:
        提取的发票数据（字典格式）
    """
    logger.info(f"Extracting data from PDF: {pdf_path}")

    # 输出路径
    output_path = os.path.join(output_dir, "pdf_data.json")

    # 调用 PDF 提取模块
    from pdf_extract import run_auto

    # 构造参数对象
    class Args:
        pdf = pdf_path
        out = output_path
        truncate = truncate_marker
        debug = debug_level  # 传入 debug level（None 或 0-3）
        ocr = ocr_lang

    args = Args()

    # 调用提取函数
    run_auto(args)

    # 读取提取结果（如果 debug_level 0-3 会提前返回，不会生成 JSON）
    if debug_level is None:
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"PDF data saved to: {output_path}")
        return data
    else:
        # debug level 0-3：已在 pdf_extract 中提前返回并保存了 CSV
        logger.info(f"Debug level {debug_level}: PDF processing stopped at intermediate stage")
        sys.exit(0)


def save_errors_to_csv(errors: list, output_path: str):
    """
    将错误列表保存为 CSV 文件

    参数:
        errors: HSCodeError 对象列表（包含 mismatch 和 not_found）
        output_path: 输出 CSV 文件路径
    """
    if not errors:
        logger.info("No errors to save")
        return

    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'U11 Code',
            'Block Index',
            'Item Index',
            'PDF HScode',
            'Excel HScode',
            'Excel Row',
            'Error Type'
        ])
        writer.writeheader()

        for error in errors:
            writer.writerow({
                'U11 Code': error.u11_code,
                'Block Index': error.block_index,
                'Item Index': error.item_index,
                'PDF HScode': error.pdf_hscode,
                'Excel HScode': error.excel_hscode or '',
                'Excel Row': error.excel_row or '',
                'Error Type': error.error_type
            })

    logger.info(f"Error report saved to: {output_path}")


def print_errors(mismatch_errors: list, not_found_errors: list):
    """
    打印错误到控制台

    参数:
        mismatch_errors: HScode 不匹配错误列表
        not_found_errors: 未找到错误列表
    """
    if mismatch_errors:
        print(f"\n{'='*70}")
        print(f"HScode Mismatch Errors ({len(mismatch_errors)}):")
        print(f"{'='*70}")

        for error in mismatch_errors:
            print(f"\n{error}")

    if not_found_errors:
        print(f"\n{'='*70}")
        print(f"U11 Codes Not Found in Excel ({len(not_found_errors)}):")
        print(f"{'='*70}")
        for error in not_found_errors:
            print(f"\n{error}")


def main():
    # 命令行参数
    parser = argparse.ArgumentParser(
        description='HS Code Audit Tool - Compare PDF invoice with Excel HScode mapping'
    )
    parser.add_argument('pdf', help='PDF invoice file path')
    parser.add_argument('excel', help='Excel HScode mapping file path')
    parser.add_argument(
        '--item-col',
        default='Item',
        help='Item column name in Excel (default: Item)'
    )
    parser.add_argument(
        '--hscode-col',
        default='HScode USA ',
        help='HScode column name in Excel (default: "HScode USA ")'
    )
    parser.add_argument(
        '--debug',
        type=int,
        nargs='?',
        const=-1,
        metavar='LEVEL',
        help='Debug mode: save intermediate files. Optional LEVEL: 0=raw, 1=truncated, 2=split, 3=merged (stops at that stage)'
    )
    parser.add_argument(
        '--truncate',
        default='SAY U.S.DOLLARS',
        help='Truncate marker for PDF extraction (default: "SAY U.S.DOLLARS")'
    )
    parser.add_argument(
        '--ocr',
        help='OCR language for scanned PDFs (e.g., "chi_sim+eng")'
    )

    args = parser.parse_args()

    # 创建输出目录：output/pdf文件名_时间戳/
    pdf_name = Path(args.pdf).stem  # 获取文件名（不含扩展名）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join("output", f"{timestamp}_{pdf_name}")
    os.makedirs(output_dir, exist_ok=True)

    # 配置日志（使用 UTF-8 编码避免 Windows 终端编码问题）
    log_level = logging.DEBUG if args.debug is not None else logging.INFO

    # 移除默认的 handler
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    # 创建日志格式
    log_format = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')

    # 添加控制台 handler（支持 UTF-8）
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(log_format)
    try:
        console_handler.stream.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    logging.root.addHandler(console_handler)

    # 添加文件 handler（保存到 output 目录）
    log_file = os.path.join(output_dir, "audit.log")
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(log_level)
    file_handler.setFormatter(log_format)
    logging.root.addHandler(file_handler)

    logging.root.setLevel(log_level)

    logger.info(f"Output directory: {output_dir}")

    # debug_level: None 表示只保存 JSON，不提前返回；0-3 表示在该阶段提前返回
    debug_level = None
    if args.debug is not None:
        debug_level = args.debug if args.debug >= 0 else None
        if debug_level is not None:
            logger.info(f"Debug mode enabled (level {debug_level})")
        else:
            logger.info(f"Debug mode enabled")

    try:
        # 1. 从 PDF 提取数据
        pdf_data = extract_pdf_data(
            args.pdf,
            output_dir=output_dir,
            truncate_marker=args.truncate,
            ocr_lang=args.ocr,
            debug_level=debug_level
        )

        # 2. 从 Excel 提取映射
        logger.info(f"Extracting mapping from Excel: {args.excel}")
        excel_mapping = extract_item_hscode_mapping(
            args.excel,
            item_col=args.item_col,
            hscode_col=args.hscode_col
        )

        # 保存 Excel 映射（debug 模式）
        if args.debug is not None:
            excel_json_path = os.path.join(output_dir, "excel_mapping.json")
            with open(excel_json_path, 'w', encoding='utf-8') as f:
                json.dump(excel_mapping, f, ensure_ascii=False, indent=2)
            logger.info(f"Excel mapping saved to: {excel_json_path}")

        # 3. 对比
        logger.info("Comparing PDF data with Excel mapping...")
        mismatch_errors, not_found_errors = compare_hscode(pdf_data, excel_mapping)

        # 4. 输出结果
        total_items = sum(len(block.get('items', [])) for block in pdf_data.get('goods_blocks', []))
        all_errors = mismatch_errors + not_found_errors

        print(f"\n{'='*70}")
        print(f"Audit Summary:")
        print(f"  Total items: {total_items}")
        print(f"  HScode mismatches: {len(mismatch_errors)}")
        print(f"  Not found in Excel: {len(not_found_errors)}")
        print(f"  Total errors: {len(all_errors)}")
        print(f"{'='*70}")

        if all_errors:
            # 打印错误
            print_errors(mismatch_errors, not_found_errors)

            # 保存 CSV 到 output 目录（合并所有错误）
            csv_path = os.path.join(output_dir, "errors.csv")
            save_errors_to_csv(all_errors, csv_path)
            print(f"\nError report saved to: {csv_path}")

            sys.exit(1)  # 有错误时返回非零状态码
        else:
            print("\n✓ Verification successful! All HScodes match.")

            # 保存成功结果
            result_path = os.path.join(output_dir, "result.json")
            with open(result_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "status": "success",
                    "total_items": total_items,
                    "pdf_file": args.pdf,
                    "excel_file": args.excel,
                    "timestamp": timestamp
                }, f, ensure_ascii=False, indent=2)
            logger.info(f"Result saved to: {result_path}")

            sys.exit(0)

    except Exception as e:
        logger.error(f"Audit failed: {e}", exc_info=args.debug)
        sys.exit(1)


if __name__ == "__main__":
    main()
