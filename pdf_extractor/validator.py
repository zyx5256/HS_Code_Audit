"""
数据校验模块

包含三层校验逻辑：货物级、块级、全局级。
"""

import re
from typing import List, Dict


def parse_number(s: str) -> float:
    """
    从字符串中提取数字。

    Args:
        s: 包含数字的字符串（可能包含 $, 逗号等）

    Returns:
        浮点数值

    Example:
        "$1,234.56" → 1234.56
        "100" → 100.0
    """
    cleaned = re.sub(r'[^\d.]', '', s)
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def validate_invoice_data(
    groups: List[Dict],
    global_total_quantity: str,
    global_total_usd: str
) -> List[str]:
    """
    三层校验发票数据。

    校验层级：
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
        # 层级 1：货物级校验
        for item_idx, item in enumerate(group["items"], start=1):
            unit_price = parse_number(item.get("unit_price", ""))
            quantity = parse_number(item.get("quantity", ""))
            amount = parse_number(item.get("amount", ""))
            calculated_amount = unit_price * quantity

            if calculated_amount > 0 and abs(calculated_amount - amount) > 0.01:
                warnings.append(
                    f"[WARNING] Block {block_idx} (HS Code '{group['hs_code']}'), Item {item_idx} (U11: {item.get('u11_code', 'N/A')}): "
                    f"amount mismatch! Expected: {amount:.2f}, Calculated: {calculated_amount:.2f}"
                )

        # 层级 2：块级校验
        subtotal_calc = sum(parse_number(item.get("quantity", "")) for item in group["items"])
        total_usd_calc = sum(parse_number(item.get("amount", "")) for item in group["items"])

        subtotal_expected = parse_number(group["subtotal"])
        total_usd_expected = parse_number(group["total_usd"])

        if subtotal_calc > 0 and abs(subtotal_calc - subtotal_expected) > 0.01:
            warnings.append(
                f"[WARNING] Block {block_idx} (HS Code '{group['hs_code']}'): subtotal mismatch! "
                f"Expected: {subtotal_expected:.2f}, Calculated: {subtotal_calc:.2f}"
            )

        if total_usd_calc > 0 and abs(total_usd_calc - total_usd_expected) > 0.01:
            warnings.append(
                f"[WARNING] Block {block_idx} (HS Code '{group['hs_code']}'): total_usd mismatch! "
                f"Expected: {total_usd_expected:.2f}, Calculated: {total_usd_calc:.2f}"
            )

    # 层级 3：全局校验
    global_subtotal_calc = sum(parse_number(g["subtotal"]) for g in groups)
    global_total_usd_calc = sum(parse_number(g["total_usd"]) for g in groups)

    global_subtotal_expected = parse_number(global_total_quantity)
    global_total_usd_expected = parse_number(global_total_usd)

    if global_subtotal_calc > 0 and abs(global_subtotal_calc - global_subtotal_expected) > 0.01:
        warnings.append(
            f"[WARNING] Global total_quantity mismatch! "
            f"Expected: {global_subtotal_expected:.2f}, Calculated: {global_subtotal_calc:.2f}"
        )

    if global_total_usd_calc > 0 and abs(global_total_usd_calc - global_total_usd_expected) > 0.01:
        warnings.append(
            f"[WARNING] Global total_usd mismatch! "
            f"Expected: {global_total_usd_expected:.2f}, Calculated: {global_total_usd_calc:.2f}"
        )

    return warnings
