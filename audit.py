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
    debug_level: int = None,
    column_config: str = "default"
) -> dict:
    """
    从 PDF 提取发票数据（调用 pdf_extract）

    参数:
        pdf_path: PDF 文件路径
        output_dir: 输出目录
        truncate_marker: 截断标记（默认 "SAY U.S.DOLLARS"）
        ocr_lang: OCR 语言（如 "chi_sim+eng"）
        debug_level: Debug 级别（None=保存JSON, 0-3=在该阶段停止并保存CSV）
        column_config: 列配置键名（默认 "default"）

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
        pass

    args = Args()
    args.pdf = pdf_path
    args.out = output_path
    args.truncate = truncate_marker
    args.debug = debug_level  # 传入 debug level（None 或 0-3）
    args.ocr = ocr_lang
    args.column_config = column_config  # 传入列配置键名

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
        errors: HSCodeError 对象列表（包含 mismatch、not_found 和 validation_*）
        output_path: 输出 CSV 文件路径
    """
    if not errors:
        logger.info("No errors to save")
        return

    # 排序：先按block_index，再按item_index（validation错误的index可能为0，排在后面）
    sorted_errors = sorted(errors, key=lambda e: (
        e.block_index if e.block_index > 0 else 9999,
        e.item_index if e.item_index > 0 else 9999
    ))

    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'Error Type',
            'Block Index',
            'Item Index',
            'Final Customers',
            'U11 Code',
            'PDF HScode',
            'Excel HScode',
            'Excel Row'
        ])
        writer.writeheader()

        for error in sorted_errors:
            is_validation = error.error_type.startswith('validation_') or error.error_type == 'missing_hscode'
            is_extraction_failed = error.error_type == 'extraction_failed'

            row = {
                'Error Type': error.error_type,
                'Final Customers': getattr(error, 'final_customers', ''),
                'U11 Code': '' if (is_validation and error.u11_code == 'N/A') or is_extraction_failed else error.u11_code,
                'Block Index': error.block_index if error.block_index > 0 else '',
                'Item Index': error.item_index if error.item_index > 0 else '',
                'PDF HScode': '' if is_validation or is_extraction_failed else error.pdf_hscode,
                'Excel HScode': '' if (is_validation or error.error_type == 'not_found' or is_extraction_failed) else error.excel_hscode,
                'Excel Row': error.excel_row or ''
            }
            writer.writerow(row)

    logger.info(f"Report saved to: {output_path}")


def parse_validation_errors(validation_errors: list) -> list:
    """
    解析 PDF 校验错误字符串，转换为 HSCodeError 对象

    参数:
        validation_errors: 校验错误字符串列表（来自 validator.py）

    返回:
        HSCodeError 对象列表
    """
    import re
    errors = []

    for i, msg in enumerate(validation_errors):
        # 尝试从消息中提取 Block 和 Item 信息
        # 格式示例：
        # "[WARNING] Block 1 (HS Code '8481.80.9090'), Item 1 (U11: YCV5-43GTLA-1-U3): amount mismatch! ..."
        # "[WARNING] Block 1 (HS Code '8481.80.9090'): subtotal mismatch! ..."
        # "[WARNING] Global total_quantity mismatch! ..."
        # "[WARNING] Goods '...' at block 7 does not have H.S Code!"

        block_match = re.search(r'[Bb]lock (\d+)', msg)  # 支持 Block 和 block
        item_match = re.search(r'Item (\d+)', msg)
        u11_match = re.search(r'U11:\s*([^\)]+)', msg)
        hscode_match = re.search(r"HS Code '([^']+)'", msg)

        block_index = int(block_match.group(1)) if block_match else 0
        item_index = int(item_match.group(1)) if item_match else 0
        u11_code = u11_match.group(1).strip() if u11_match else "N/A"
        pdf_hscode = hscode_match.group(1) if hscode_match else ""

        # 判断校验错误类型
        if 'does not have H.S Code' in msg:
            error_type = "missing_hscode"
        elif 'Global' in msg:
            error_type = "validation_global"
        elif item_match or u11_match:
            error_type = "validation_item"
        elif block_match:
            error_type = "validation_block"
        else:
            error_type = "validation_block"  # 默认为block级

        # 创建 HSCodeError 对象
        error = HSCodeError(
            u11_code=u11_code,
            block_index=block_index,
            item_index=item_index,
            pdf_hscode=pdf_hscode,
            excel_hscode=msg,  # 将完整错误消息存储在 excel_hscode 字段（仅用于打印）
            excel_row=None,
            error_type=error_type
        )
        errors.append(error)

    return errors


def print_errors(mismatch_errors: list, not_found_errors: list, validation_errors: list = None):
    """
    打印错误到控制台

    参数:
        mismatch_errors: HScode 不匹配错误列表
        not_found_errors: 未找到错误列表
        validation_errors: PDF 校验错误列表
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

    if validation_errors:
        print(f"\n{'='*70}")
        print(f"PDF Validation Errors ({len(validation_errors)}):")
        print(f"{'='*70}")
        for error in validation_errors:
            try:
                print(f"\n{error}")
            except UnicodeEncodeError:
                # Windows终端无法打印中文，使用ASCII安全版本
                error_str = str(error).encode('ascii', 'replace').decode('ascii')
                print(f"\n{error_str}")


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
        default='HScode USA',
        help='HScode column name in Excel (default: "HScode USA")'
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
    parser.add_argument(
        '--column-config',
        default='default',
        help='Column configuration key name in column_config.json (default: "default")'
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
            debug_level=debug_level,
            column_config=args.column_config
        )

        # 2. 检查提取结果
        total_items = sum(len(block.get('items', [])) for block in pdf_data.get('goods_blocks', []))

        # 如果没有提取到任何item，认为提取失败
        if total_items == 0:
            logger.error("PDF extraction failed: No items extracted")
            extraction_error = HSCodeError(
                u11_code="",
                block_index=0,
                item_index=0,
                pdf_hscode="",
                excel_hscode="PDF extraction failed: No items found in the invoice",
                excel_row=None,
                error_type="extraction_failed"
            )

            # 直接输出错误并退出
            csv_path = os.path.join(output_dir, "result.csv")
            save_errors_to_csv([extraction_error], csv_path)

            print(f"\n{'='*70}")
            print(f"Audit Summary:")
            print(f"  Total items: 0")
            print(f"  Extraction failed: Unable to extract any items from PDF")
            print(f"{'='*70}")
            print(f"\nError report saved to: {csv_path}")

            sys.exit(1)

        # 3. 从 Excel 提取映射
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

        # 4. 提取 PDF 校验错误
        pdf_validation_errors_raw = pdf_data.get('errors', [])
        pdf_validation_errors = parse_validation_errors(pdf_validation_errors_raw) if pdf_validation_errors_raw else []

        if pdf_validation_errors:
            logger.warning(f"PDF validation found {len(pdf_validation_errors)} error(s)")

        # 5. 对比（不跳过任何item）
        logger.info("Comparing PDF data with Excel mapping...")
        mismatch_errors, not_found_errors, ok_results = compare_hscode(
            pdf_data,
            excel_mapping
        )

        # 6. 输出结果
        # all_errors只包含item级别的错误（mismatch和not_found）
        # validation errors已经在pdf_data中，不需要重复输出到result.csv
        all_errors = mismatch_errors + not_found_errors
        all_results = all_errors + ok_results  # 所有item结果（错误+OK）

        print(f"\n{'='*70}")
        print(f"Audit Summary:")
        print(f"  Total items: {total_items}")
        print(f"  HScode mismatches: {len(mismatch_errors)}")
        print(f"  Not found in Excel: {len(not_found_errors)}")
        print(f"  Total errors: {len(all_errors)}")
        if pdf_validation_errors:
            print(f"  PDF validation errors: {len(pdf_validation_errors)} (see PDF output for details)")
        print(f"{'='*70}")

        # 保存 CSV 到 output 目录（所有结果，包括OK的）
        csv_path = os.path.join(output_dir, "result.csv")
        save_errors_to_csv(all_results, csv_path)

        if all_errors:
            # 打印错误（只打印item级别的错误）
            print_errors(mismatch_errors, not_found_errors, [])
            print(f"\nResult saved to: {csv_path}")
            sys.exit(1)  # 有错误时返回非零状态码
        else:
            print("\n✓ Verification successful! All HScodes match.")
            print(f"\nResult saved to: {csv_path}")
            sys.exit(0)

    except Exception as e:
        logger.error(f"Audit failed: {e}", exc_info=args.debug)
        sys.exit(1)


if __name__ == "__main__":
    main()
