"""
Excel 提取模块
从 Excel 文件中提取 Item 列和 HScode USA 列，生成字典
"""
import logging
from typing import Dict, Optional
import pandas as pd

logger = logging.getLogger(__name__)


def extract_item_hscode_mapping(
    excel_path: str,
    item_col: str = "Item",
    hscode_col: str = "HScode USA ",  # 注意尾部有空格
) -> Dict[str, Dict[str, any]]:
    """
    从 Excel 文件中提取 Item 和 HScode 的映射关系

    参数:
        excel_path: Excel 文件路径
        item_col: Item 列名（默认 "Item"）
        hscode_col: HScode 列名（默认 "HScode USA "，注意尾部空格）

    返回:
        字典格式：
        {
            "Item值1": {"hs_code": "HScode值1", "row": 行号1},
            "Item值2": {"hs_code": "HScode值2", "row": 行号2},
            ...
        }

        注意：
        - 行号从 2 开始（Excel 中第 1 行是表头）
        - 如果 Item 值重复，后面的会覆盖前面的
        - 跳过 Item 或 HScode 为空的行
    """
    try:
        # 读取 Excel 文件
        logger.info(f"正在读取 Excel 文件: {excel_path}")
        df = pd.read_excel(excel_path)

        # 检查列是否存在
        if item_col not in df.columns:
            raise ValueError(f"列 '{item_col}' 不存在。可用列: {df.columns.tolist()}")
        if hscode_col not in df.columns:
            raise ValueError(f"列 '{hscode_col}' 不存在。可用列: {df.columns.tolist()}")

        # 构建映射字典
        result = {}
        skipped_count = 0
        duplicate_count = 0

        for idx, row in df.iterrows():
            item = row[item_col]
            hs_code = row[hscode_col]

            # 跳过空值
            if pd.isna(item) or pd.isna(hs_code):
                skipped_count += 1
                continue

            # 转换为字符串并去除首尾空格
            item = str(item).strip()
            hs_code = str(hs_code).strip()

            # 跳过空字符串
            if not item or not hs_code:
                skipped_count += 1
                continue

            # Excel 行号 = DataFrame 索引 + 2（表头占第 1 行）
            excel_row = idx + 2

            # 检查是否重复
            if item in result:
                logger.warning(f"Item '{item}' 重复出现在第 {excel_row} 行，将覆盖第 {result[item]['row']} 行的值")
                duplicate_count += 1

            result[item] = {
                "hs_code": hs_code,
                "row": excel_row
            }

        logger.info(f"提取完成: 共 {len(result)} 条有效记录，跳过 {skipped_count} 条空记录，{duplicate_count} 条重复记录")
        return result

    except Exception as e:
        logger.error(f"提取 Excel 数据失败: {e}")
        raise


def save_mapping_to_json(mapping: Dict, output_path: str):
    """
    将映射字典保存为 JSON 文件

    参数:
        mapping: 映射字典
        output_path: 输出文件路径
    """
    import json
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    logger.info(f"映射字典已保存到: {output_path}")


if __name__ == "__main__":
    import argparse

    # 配置日志
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    # 命令行参数
    parser = argparse.ArgumentParser(description='从 Excel 文件提取 Item 和 HScode 的映射关系')
    parser.add_argument('excel_file', help='Excel 文件路径')
    parser.add_argument('--item-col', default='Item', help='Item 列名（默认: Item）')
    parser.add_argument('--hscode-col', default='HScode USA ', help='HScode 列名（默认: "HScode USA "，注意尾部空格）')
    parser.add_argument('--out', '-o', help='输出 JSON 文件路径（可选）')
    args = parser.parse_args()

    # 提取数据
    mapping = extract_item_hscode_mapping(
        args.excel_file,
        item_col=args.item_col,
        hscode_col=args.hscode_col
    )

    # 打印前 5 条记录
    print("\nFirst 5 records:")
    for i, (item, data) in enumerate(mapping.items()):
        if i >= 5:
            break
        print(f"  {item}: hs_code={data['hs_code']}, row={data['row']}")

    print(f"\nTotal: {len(mapping)} records")

    # 保存到 JSON（如果指定了输出路径）
    if args.out:
        save_mapping_to_json(mapping, args.out)