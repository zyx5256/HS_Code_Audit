"""
内容抽取算法模块

职责：
- 截断处理（过滤底部无关内容）
- 基于规则的字段提取（页码+行号）
- 发票货物信息自动提取
- 只做提取，不做校验（校验由 validator.py 负责）
"""

import logging
from typing import List, Dict, Tuple, Optional
from collections import defaultdict

logger = logging.getLogger("pdf_text")


def truncate_at_marker(rows: List[Dict], marker: str) -> List[Dict]:
    """
    截断文本：遇到标记行后舍弃该行及后续内容。

    用途：过滤发票底部的银行信息、备注等无关内容。

    Args:
        rows: 文本行列表
              格式: [{"page": int, "index": int, "text": str, ...}, ...]
        marker: 截断标记（不区分大小写）

    Returns:
        截断后的行列表（不包含标记行）

    Example:
        marker="SAY U.S.DOLLARS"
        遇到此行后，后续的银行信息等都会被过滤掉
    """
    for i, row in enumerate(rows):
        if marker.upper() in row["text"].upper():
            logger.info(f"Truncated at row {i+1} (page {row['page']}, index {row['index']}): '{row['text'][:50]}...'")
            return rows[:i]
    return rows


def extract_by_line_numbers(rows: List[Dict], page: int, line: int) -> Optional[str]:
    """
    按页码+行号提取单行文本。

    Args:
        rows: 文本行列表
        page: 页码（1-based）
        line: 行号（1-based）

    Returns:
        提取的文本，未找到返回 None
    """
    for row in rows:
        if row["page"] == page and row["index"] == line:
            return row["text"]
    return None


def extract_by_line_range(rows: List[Dict], page: int, start: int, end: int, joiner: str = " ") -> Optional[str]:
    """
    按页码+行号范围提取多行文本。

    Args:
        rows: 文本行列表
        page: 页码（1-based）
        start: 起始行号（1-based，包含）
        end: 结束行号（1-based，包含）
        joiner: 连接符

    Returns:
        提取的文本，未找到返回 None
    """
    matched_lines = []
    for row in rows:
        if row["page"] == page and start <= row["index"] <= end:
            matched_lines.append(row["text"])

    if matched_lines:
        return joiner.join(matched_lines)
    return None


def extract_by_rules(rows: List[Dict], rules: Dict) -> Dict:
    """
    基于规则文件提取字段。

    规则格式：
    {
      "fields": [
        {"name": "invoice_number", "selector": {"page": 1, "line": 5}},
        {"name": "ship_to", "selector": {"page": 1, "lines": [10, 15], "join": "\\n"}}
      ]
    }

    Args:
        rows: 文本行列表
        rules: 规则字典

    Returns:
        提取结果：{field_name: value, ...}
    """
    results = {}

    for field in rules.get("fields", []):
        name = field.get("name")
        sel = field.get("selector", {})
        page_no = int(sel.get("page", 1))
        joiner = sel.get("join", " ")

        value = None
        if "line" in sel:
            # 提取单行
            line_no = int(sel["line"])
            value = extract_by_line_numbers(rows, page_no, line_no)
        elif "lines" in sel:
            # 提取行段
            start, end = sel["lines"]
            value = extract_by_line_range(rows, page_no, int(start), int(end), joiner)

        results[name] = value

    return results


def parse_invoice_structure(lines: List[str]) -> Tuple[List[Tuple[int, str, str]], List[int]]:
    """
    解析发票结构，找到所有 DESCRIPTION OF GOODS 和 SUB TOTAL 位置。

    Args:
        lines: 纯文本行列表

    Returns:
        (goods_positions, subtotal_positions)
        - goods_positions: [(index, hs_code, desc_of_goods), ...]
        - subtotal_positions: [index, ...]
    """
    goods_positions = []
    subtotal_positions = []

    for i, line in enumerate(lines):
        line_upper = line.upper()

        if "DESCRIPTION OF GOODS" in line_upper:
            desc_of_goods = ""
            hs_code = ""

            if ":" in line:
                parts = line.split(":", 1)
                rest = parts[1].strip() if len(parts) > 1 else ""

                # 提取 HS Code
                if "H.S CODE:" in rest.upper():
                    name_and_code = rest.upper().split("H.S CODE:")
                    desc_of_goods = name_and_code[0].strip()
                    if len(name_and_code) > 1:
                        hs_code = name_and_code[1].strip().split()[0] if name_and_code[1].strip() else ""
                else:
                    desc_of_goods = rest.strip()

            # 清理货物描述（调用 preprocessor 的功能）
            from .preprocessor import clean_text
            desc_of_goods = clean_text(desc_of_goods)

            goods_positions.append((i, hs_code, desc_of_goods))

        elif "SUB TOTAL" in line_upper:
            subtotal_positions.append(i)

    return goods_positions, subtotal_positions


def extract_invoice_goods_items(
    lines: List[str],
    goods_positions: List[Tuple[int, str, str]],
    subtotal_positions: List[int]
) -> Tuple[List[Dict], List[str]]:
    """
    提取发票货物信息。

    提取逻辑：
        - 每 7 行为一组货物信息
        - 验证 U11 CODE 必须包含字母数字

    Args:
        lines: 纯文本行列表
        goods_positions: [(index, hs_code, desc_of_goods), ...]
        subtotal_positions: [index, ...]

    Returns:
        (all_items, warnings)
        - all_items: 所有提取的货物项列表
        - warnings: 提取过程中的警告信息
    """
    all_items = []
    warnings = []

    for block_idx, (goods_idx, hs_code, desc_of_goods) in enumerate(goods_positions, start=1):
        # 检查是否缺少 HS Code
        if not hs_code:
            warnings.append(f"[WARNING] Goods '{desc_of_goods}' at block {block_idx} does not have H.S Code!")

        # 找到最近的 SUB TOTAL
        end_idx = len(lines)
        subtotal_idx = None
        for st_idx in subtotal_positions:
            if st_idx > goods_idx:
                end_idx = st_idx
                subtotal_idx = st_idx
                break

        # 提取 7 行一组的货物信息
        start_idx = goods_idx + 1
        i = start_idx

        while i + 6 < end_idx:
            # 读取原始行并检测是否需要拆分（处理表格两列合并的情况）
            line_text = lines[i].strip()

            # 检测并拆分宽行：如果包含空格且看起来像两列合并
            # 例如："AIFI(GOODMAN) 10205389943" 应该拆分成两行
            if " " in line_text:
                last_space_idx = line_text.rfind(" ")
                before_space = line_text[:last_space_idx].strip()
                after_space = line_text[last_space_idx + 1:].strip()

                # 判断是否是两列合并：
                # 1. 后半部分是纯数字（可能是编号）
                # 2. 前半部分包含字母（可能是客户名）
                if after_space.isdigit() and any(c.isalpha() for c in before_space):
                    # 拆分：将后半部分插入到下一行
                    lines.insert(i + 1, after_space)
                    lines[i] = before_space
                    end_idx += 1  # 更新结束索引
                    # 使用logger而不是print，避免Windows终端编码问题
                    logger.debug(f"[SPLIT-INVOICE] Line {i}: split by 2+ spaces")

            final_customers = lines[i].strip()
            u11_code = lines[i + 1].strip()
            customers_no = lines[i + 2].strip()
            sanhua_no = lines[i + 3].strip()
            quantity = lines[i + 4].strip()
            unit_price = lines[i + 5].strip()
            amount = lines[i + 6].strip()

            # 清理客户信息（替换中文括号、去掉括号前后空格）
            from .preprocessor import clean_text
            final_customers = clean_text(final_customers)

            # 验证：U11 CODE 必须包含字母数字
            if final_customers and u11_code and (
                any(c.isalnum() for c in u11_code) and len(u11_code) > 3
            ):
                all_items.append({
                    "block_idx": block_idx,
                    "hs_code": hs_code if hs_code else "",
                    "desc_of_goods": desc_of_goods,
                    "subtotal_idx": subtotal_idx,
                    "final_customers": final_customers,
                    "u11_code": u11_code,
                    "customers_no": customers_no,
                    "sanhua_no": sanhua_no,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "amount": amount
                })
                i += 7
            else:
                i += 1

    # 打印警告
    for warning in warnings:
        logger.warning(warning)

    return all_items, warnings


def group_invoice_items_by_block(all_items: List[Dict]) -> List[Dict]:
    """
    按 block 分组货物信息。

    Args:
        all_items: 所有货物项列表

    Returns:
        分组后的货物块列表
    """
    grouped = defaultdict(lambda: {"hs_code": "", "desc_of_goods": "", "items": [], "subtotal_idx": None})

    for item in all_items:
        key = item["block_idx"]
        if not grouped[key]["hs_code"]:
            grouped[key]["hs_code"] = item["hs_code"]
            grouped[key]["desc_of_goods"] = item["desc_of_goods"]
            grouped[key]["subtotal_idx"] = item["subtotal_idx"]

        # 移除分组字段
        item_data = {k: v for k, v in item.items() if k not in ["block_idx", "hs_code", "desc_of_goods", "subtotal_idx"]}
        grouped[key]["items"].append(item_data)

    return list(grouped.values())


def extract_block_totals(groups: List[Dict], lines: List[str]) -> List[Dict]:
    """
    提取每个块的 subtotal 和 total_usd。

    Args:
        groups: 货物块列表
        lines: 纯文本行列表

    Returns:
        更新后的 groups
    """
    for group in groups:
        st_idx = group["subtotal_idx"]
        if st_idx is not None and st_idx + 3 < len(lines):
            # 验证格式
            line1 = lines[st_idx].strip().upper()
            line3 = lines[st_idx + 2].strip().upper()

            if "SUB TOTAL" in line1 and "TOTAL" in line3 and "USD" in line3:
                group["subtotal"] = lines[st_idx + 1].strip()
                group["total_usd"] = lines[st_idx + 3].strip()
            else:
                logger.warning(f"Subtotal format mismatch for HS Code '{group['hs_code']}' at line {st_idx}")
                group["subtotal"] = ""
                group["total_usd"] = ""
        else:
            group["subtotal"] = ""
            group["total_usd"] = ""

        # 移除临时字段
        del group["subtotal_idx"]

    return groups


def extract_invoice_items(lines: List[str], debug: bool = False) -> Tuple[List[Dict], str, str, List[str]]:
    """
    自动提取发票货物信息（不包含校验）。

    提取逻辑：
        1. 识别 "DESCRIPTION OF GOODS" 块，提取 HS Code 和货物描述
        2. 每 7 行为一组货物信息
        3. 遇到 "SUB TOTAL" 标记当前块结束
        4. 按 PDF 中出现的块顺序分组

    Args:
        lines: 纯文本行列表（已预处理）
        debug: 是否打印调试信息

    Returns:
        (goods_blocks, global_total_quantity, global_total_usd, extraction_errors)
        - extraction_errors: 提取过程中的错误（如缺失 HS Code）
    """
    # 提取全局 total
    # - global_total_quantity: 严格匹配到 "TOTAL:" 的后一行
    # - global_total_usd: 最后一行
    global_total_quantity = ""
    global_total_usd = ""

    for i, line in enumerate(lines):
        if "TOTAL:" in line.upper():
            if i + 1 < len(lines):
                global_total_quantity = lines[i + 1].strip()
            break

    if lines:
        global_total_usd = lines[-1].strip()

    # 调试模式
    if debug:
        logger.info("=== All extracted lines ===")
        for i, line in enumerate(lines, start=1):
            logger.info(f"Line {i}: {line}")
        logger.info(f"=== Total lines: {len(lines)} ===")
        logger.info(f"=== Global totals ===")
        logger.info(f"global_total_quantity (line -3): {global_total_quantity}")
        logger.info(f"global_total_usd (line -1): {global_total_usd}")

    # 解析发票结构
    goods_positions, subtotal_positions = parse_invoice_structure(lines)

    # 提取货物信息
    all_items, extraction_errors = extract_invoice_goods_items(lines, goods_positions, subtotal_positions)

    # 按块分组
    groups = group_invoice_items_by_block(all_items)

    # 提取每个块的 subtotal 信息
    groups = extract_block_totals(groups, lines)

    return groups, global_total_quantity, global_total_usd, extraction_errors
