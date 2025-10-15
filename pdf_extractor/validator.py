"""
数据校验模块

包含三层校验逻辑：货物级、块级、全局级。
"""

import re
from typing import List, Dict


def parse_number(s: str) -> float:
    """
    从字符串中提取并累加所有数字（支持多单位合计格式）。

    Args:
        s: 包含数字的字符串（可能包含 $, 逗号等）

    Returns:
        浮点数值（多个数字则累加）

    Example:
        "$1,234.56" → 1234.56
        "100" → 100.0
        "7344PCS+5768SETS+512SMETAS" → 13624.0
        "100PCS" → 100.0
    """
    # 提取所有数字（包含小数点）
    # 匹配模式：可选的逗号分隔的整数部分 + 可选的小数部分
    numbers = re.findall(r'[\d,]+\.?\d*', s)

    total = 0.0
    for num_str in numbers:
        # 移除逗号
        cleaned = num_str.replace(',', '')
        try:
            if cleaned:
                total += float(cleaned)
        except ValueError:
            continue

    return total


def validate_invoice_data(
    groups: List[Dict],
    global_total_quantity: str,
    global_total_usd: str
) -> List[str]:
    """
    三层校验发票数据。

    校验层级：
        0. 必填字段校验：quantity不能为空
        1. 货物级：quantity × unit_price == amount
        2. 块级：subtotal == Σ(quantity), total_usd == Σ(amount)
        3. 全局：global_total_quantity == Σ(subtotal), global_total_usd == Σ(total_usd)

    Args:
        groups: 货物块列表
        global_total_quantity: 全局总数量
        global_total_usd: 全局总金额

    Returns:
        警告信息列表
    """
    warnings = []

    for block_idx, group in enumerate(groups, start=1):
        # 层级 0：必填字段校验
        for item_idx, item in enumerate(group["items"], start=1):
            # 检查必填字段
            if not item.get("quantity") or item.get("quantity").strip() == "":
                warnings.append(
                    f"[ERROR] Block {block_idx} (HS Code '{group['hs_code']}'), Item {item_idx} (U11: {item.get('u11_code', 'N/A')}): "
                    f"quantity is REQUIRED but MISSING or EMPTY!"
                )

        # 层级 1：货物级校验
        for item_idx, item in enumerate(group["items"], start=1):
            unit_price = parse_number(item.get("unit_price", ""))
            quantity = parse_number(item.get("quantity", ""))
            amount = parse_number(item.get("amount", ""))
            calculated_amount = unit_price * quantity

            # 修复：不要用 > 0 跳过校验，即使quantity为空（0）也要报错
            if abs(calculated_amount - amount) > 0.01:
                warnings.append(
                    f"[WARNING] Block {block_idx} (HS Code '{group['hs_code']}'), Item {item_idx} (U11: {item.get('u11_code', 'N/A')}): "
                    f"amount mismatch! Expected: {amount:.2f}, Calculated: {calculated_amount:.2f} "
                    f"(quantity={quantity}, unit_price={unit_price})"
                )

        # 层级 2：块级校验
        subtotal_calc = sum(parse_number(item.get("quantity", "")) for item in group["items"])
        total_usd_calc = sum(parse_number(item.get("amount", "")) for item in group["items"])

        subtotal_expected = parse_number(group["subtotal"])
        total_usd_expected = parse_number(group["total_usd"])

        # 修复：不要用 > 0 跳过校验
        if abs(subtotal_calc - subtotal_expected) > 0.01:
            warnings.append(
                f"[WARNING] Block {block_idx} (HS Code '{group['hs_code']}'): subtotal mismatch! "
                f"Expected: {subtotal_expected:.2f}, Calculated: {subtotal_calc:.2f}"
            )

        if abs(total_usd_calc - total_usd_expected) > 0.01:
            warnings.append(
                f"[WARNING] Block {block_idx} (HS Code '{group['hs_code']}'): total_usd mismatch! "
                f"Expected: {total_usd_expected:.2f}, Calculated: {total_usd_calc:.2f}"
            )

    # 层级 3：全局校验
    global_subtotal_calc = sum(parse_number(g["subtotal"]) for g in groups)
    global_total_usd_calc = sum(parse_number(g["total_usd"]) for g in groups)

    global_subtotal_expected = parse_number(global_total_quantity)
    global_total_usd_expected = parse_number(global_total_usd)

    # 修复：不要用 > 0 跳过校验
    if abs(global_subtotal_calc - global_subtotal_expected) > 0.01:
        warnings.append(
            f"[WARNING] Global total_quantity mismatch! "
            f"Expected: {global_subtotal_expected:.2f}, Calculated: {global_subtotal_calc:.2f}"
        )

    if abs(global_total_usd_calc - global_total_usd_expected) > 0.01:
        warnings.append(
            f"[WARNING] Global total_usd mismatch! "
            f"Expected: {global_total_usd_expected:.2f}, Calculated: {global_total_usd_calc:.2f}"
        )

    return warnings
