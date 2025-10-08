"""
对比模块
对比 PDF 提取的发票数据和 Excel 提取的 HScode 映射，验证 HScode 是否一致
"""
import json
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class HSCodeError:
    """HSCode 不匹配或未找到错误"""
    def __init__(
        self,
        u11_code: str,
        block_index: int,
        item_index: int,
        pdf_hscode: str,
        excel_hscode: str = None,
        excel_row: int = None,
        error_type: str = "mismatch"  # "mismatch" 或 "not_found"
    ):
        self.u11_code = u11_code
        self.block_index = block_index
        self.item_index = item_index
        self.pdf_hscode = pdf_hscode
        self.excel_hscode = excel_hscode
        self.excel_row = excel_row
        self.error_type = error_type

    def __str__(self):
        if self.error_type == "not_found":
            return (
                f"[NOT FOUND] U11 Code: {self.u11_code}\n"
                f"  PDF Location: Block {self.block_index}, Item {self.item_index}\n"
                f"  PDF HScode: {self.pdf_hscode}\n"
                f"  Status: Not found in Excel"
            )
        else:
            return (
                f"[MISMATCH] U11 Code: {self.u11_code}\n"
                f"  PDF Location: Block {self.block_index}, Item {self.item_index}\n"
                f"  PDF HScode: {self.pdf_hscode}\n"
                f"  Excel Location: Row {self.excel_row}\n"
                f"  Excel HScode: {self.excel_hscode}"
            )

    def to_dict(self):
        return {
            "u11_code": self.u11_code,
            "block_index": self.block_index,
            "item_index": self.item_index,
            "pdf_hscode": self.pdf_hscode,
            "excel_hscode": self.excel_hscode or "",
            "excel_row": self.excel_row or "",
            "error_type": self.error_type
        }


def compare_hscode(
    pdf_data: Dict,
    excel_mapping: Dict,
    normalize_hscode: bool = True
) -> Tuple[List[HSCodeError], List[HSCodeError]]:
    """
    对比 PDF 发票数据和 Excel HScode 映射

    参数:
        pdf_data: PDF 提取的发票数据（包含 goods_blocks）
        excel_mapping: Excel 提取的映射字典（u11_code -> {hs_code, row}）
        normalize_hscode: 是否规范化 HScode 格式（去除点号后比较）

    返回:
        (不匹配错误列表, 未找到错误列表)
    """
    mismatch_errors = []
    not_found_errors = []

    goods_blocks = pdf_data.get('goods_blocks', [])

    for block_idx, block in enumerate(goods_blocks):
        # block_index 从 1 开始
        block_index = block_idx + 1
        pdf_hscode = block.get('hs_code', '')
        items = block.get('items', [])

        for item_idx, item in enumerate(items):
            # item_index 从 1 开始
            item_index = item_idx + 1
            u11_code = item.get('u11_code', '').strip()

            if not u11_code:
                logger.warning(f"Block {block_index} Item {item_index} 缺少 u11_code")
                continue

            # 在 Excel 映射中查找
            if u11_code not in excel_mapping:
                logger.warning(f"U11 Code '{u11_code}' 未在 Excel 中找到 (Block {block_index} Item {item_index})")
                error = HSCodeError(
                    u11_code=u11_code,
                    block_index=block_index,
                    item_index=item_index,
                    pdf_hscode=pdf_hscode,
                    error_type="not_found"
                )
                not_found_errors.append(error)
                continue

            excel_info = excel_mapping[u11_code]
            excel_hscode = excel_info['hs_code']
            excel_row = excel_info['row']

            # 比较 HScode
            pdf_hs = pdf_hscode.strip()
            excel_hs = excel_hscode.strip()

            # 可选：规范化格式（去除点号）
            if normalize_hscode:
                pdf_hs_normalized = pdf_hs.replace('.', '')
                excel_hs_normalized = excel_hs.replace('.', '')
            else:
                pdf_hs_normalized = pdf_hs
                excel_hs_normalized = excel_hs

            if pdf_hs_normalized != excel_hs_normalized:
                error = HSCodeError(
                    u11_code=u11_code,
                    block_index=block_index,
                    item_index=item_index,
                    pdf_hscode=pdf_hscode,
                    excel_hscode=excel_hscode,
                    excel_row=excel_row,
                    error_type="mismatch"
                )
                mismatch_errors.append(error)
                logger.error(str(error))

    return mismatch_errors, not_found_errors


def load_json(file_path: str) -> Dict:
    """加载 JSON 文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_errors_to_json(errors: List[HSCodeError], output_path: str):
    """保存错误列表到 JSON 文件"""
    error_dicts = [e.to_dict() for e in errors]
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(error_dicts, f, ensure_ascii=False, indent=2)
    logger.info(f"错误报告已保存到: {output_path}")


if __name__ == "__main__":
    import argparse

    # 配置日志
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    # 命令行参数
    parser = argparse.ArgumentParser(description='对比 PDF 发票和 Excel HScode 映射')
    parser.add_argument('pdf_json', help='PDF 提取的 JSON 文件路径')
    parser.add_argument('excel_json', help='Excel 提取的映射 JSON 文件路径')
    parser.add_argument('--out', '-o', help='错误报告输出路径（JSON 格式）')
    parser.add_argument('--no-normalize', action='store_true', help='不规范化 HScode 格式（默认会去除点号比较）')
    args = parser.parse_args()

    # 加载数据
    logger.info(f"加载 PDF 数据: {args.pdf_json}")
    pdf_data = load_json(args.pdf_json)

    logger.info(f"加载 Excel 映射: {args.excel_json}")
    excel_mapping = load_json(args.excel_json)

    # 对比
    logger.info("开始对比...")
    errors, not_found = compare_hscode(
        pdf_data,
        excel_mapping,
        normalize_hscode=not args.no_normalize
    )

    # 输出结果
    print(f"\n{'='*60}")
    print(f"Comparison completed:")
    print(f"  Total items: {sum(len(block.get('items', [])) for block in pdf_data.get('goods_blocks', []))}")
    print(f"  HScode mismatches: {len(errors)}")
    print(f"  Not found in Excel: {len(not_found)}")
    print(f"{'='*60}\n")

    if errors:
        print(f"HScode mismatch errors ({len(errors)}):")
        for error in errors:
            print(f"\n{error}")

    if not_found:
        print(f"\nU11 Codes not found in Excel ({len(not_found)}):")
        for code in not_found:
            print(f"  - {code}")

    # 保存错误报告
    if args.out and errors:
        save_errors_to_json(errors, args.out)
