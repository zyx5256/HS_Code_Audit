"""
内容抽取算法模块

职责：
- 截断处理（过滤底部无关内容）
- 基于规则的字段提取（页码+行号）
- 发票货物信息自动提取
- 只做提取，不做校验（校验由 validator.py 负责）
"""

import logging
import json
import os
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import fitz  # PyMuPDF - 用于表格提取

logger = logging.getLogger("pdf_text")


def load_column_config(config_path: str = None, config_key: str = "default") -> List[str]:
    """
    加载列配置文件

    Args:
        config_path: 配置文件路径，默认为 column_config.json
        config_key: 配置键名，默认为 "default"

    Returns:
        列字段名列表，如 ["customer", "order_no", ...]
    """
    if config_path is None:
        # 默认配置文件路径：与 extractor.py 同目录下的 ../column_config.json
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(current_dir, "..", "column_config.json")

    if not os.path.exists(config_path):
        logger.error(f"Column config file not found: {config_path}")
        return []

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        if config_key not in config:
            logger.error(f"Config key '{config_key}' not found in {config_path}")
            return []

        column_fields = config[config_key]
        logger.info(f"Loaded column config '{config_key}' from {config_path}: {column_fields}")
        return column_fields

    except Exception as e:
        logger.error(f"Failed to load column config from {config_path}: {e}")
        return []


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
    # 预处理marker：去掉空格和点号
    normalized_marker = marker.upper().replace(" ", "").replace(".", "")

    for i, row in enumerate(rows):
        # 预处理row文本：去掉空格和点号
        normalized_text = row["text"].upper().replace(" ", "").replace(".", "")

        if normalized_marker in normalized_text:
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


#
# ========== 表格提取辅助函数（基于矩形边界）==========
#

def extract_table_rectangles(page) -> List[Dict]:
    """
    从 PDF 页面提取矩形单元格

    Args:
        page: PyMuPDF page 对象

    Returns:
        [{'x0': float, 'y0': float, 'x1': float, 'y1': float}, ...]
    """
    drawings = page.get_drawings()
    rectangles = []
    for drawing in drawings:
        items = drawing.get('items', [])
        for item in items:
            if item[0] == 're':  # rectangle
                rect = item[1]
                rectangles.append({
                    'x0': rect.x0,
                    'y0': rect.y0,
                    'x1': rect.x1,
                    'y1': rect.y1,
                })
    return rectangles


def find_header_region_bounds(page) -> Optional[Tuple[float, float]]:
    """
    找到表头区域的上下边界（使用业务逻辑标记）

    表头区域定义：
    - 上边界：第一次出现 "SHIPPED TO" 或 "Shipped by" 的 y 坐标
    - 下边界：第一次出现 "DESCRIPTION OF GOODS" 的 y 坐标

    Args:
        page: PyMuPDF page 对象

    Returns:
        (upper_bound_y, lower_bound_y) 元组，未找到返回 None
    """
    words = page.get_text("words")

    # 找上边界：SHIPPED TO 或 Shipped by
    upper_y = None
    for w in words:
        text_upper = w[4].upper()
        if 'SHIPPED' in text_upper or 'SHIP' in text_upper:
            # 检查附近词语是否构成完整短语
            nearby = [w2[4] for w2 in words if abs(w2[1] - w[1]) < 3]
            nearby_text = ' '.join(nearby).upper()
            if 'SHIPPED' in nearby_text and ('TO' in nearby_text or 'BY' in nearby_text):
                upper_y = w[1]
                logger.info(f"[TABLE-REGION] Found upper bound at y={upper_y:.2f}, text: '{' '.join(nearby)}'")
                break

    # 找下边界：DESCRIPTION OF GOODS
    lower_y = None
    for w in words:
        text_upper = w[4].upper()
        if 'DESCRIPTION' in text_upper or 'GOODS' in text_upper:
            # 检查附近词语
            nearby = [w2[4] for w2 in words if abs(w2[1] - w[1]) < 3]
            nearby_text = ' '.join(nearby).upper()
            if 'DESCRIPTION' in nearby_text and 'GOODS' in nearby_text:
                lower_y = w[1]
                logger.info(f"[TABLE-REGION] Found lower bound at y={lower_y:.2f}, text: '{' '.join(nearby)}'")
                break

    if upper_y is not None and lower_y is not None:
        logger.info(f"[TABLE-REGION] Header region: y=[{upper_y:.2f}, {lower_y:.2f}], height={lower_y - upper_y:.2f}")
        return (upper_y, lower_y)
    else:
        logger.warning(f"[TABLE-REGION] Cannot find header region bounds (upper={upper_y}, lower={lower_y})")
        return None


def find_header_row_y(page) -> Optional[float]:
    """
    找到表头行的 y 坐标（搜索 "U11 CODE"）

    注意：此函数保留用于向后兼容，新代码应使用 find_header_region_bounds

    Args:
        page: PyMuPDF page 对象

    Returns:
        表头行的 y 坐标，未找到返回 None
    """
    words = page.get_text("words")
    for w in words:
        if 'U11' in w[4] or 'CODE' in w[4]:
            # 检查附近是否有 "U11 CODE"
            nearby = [w2[4] for w2 in words if abs(w2[1] - w[1]) < 3]
            nearby_text = ' '.join(nearby)
            if 'U11' in nearby_text and 'CODE' in nearby_text:
                header_y = w[1]
                logger.info(f"[TABLE-HEADER] Found header row at y={header_y:.2f}, keyword: '{w[4]}' at ({w[0]:.2f}, {w[1]:.2f})")
                return header_y
    return None


def identify_columns_from_config(page, column_fields: List[str], header_region: Optional[Tuple[float, float]] = None) -> Dict[str, Dict]:
    """
    从配置文件识别列定义（基于竖线分隔 + 配置的列顺序）

    Args:
        page: PyMuPDF page 对象
        column_fields: 列字段名列表（按顺序），如 ["customer", "u11_code", ...]
        header_region: 表头区域的上下边界 (upper_y, lower_y)，如果为 None 则自动查找

    Returns:
        {field_name: {'x0': float, 'x1': float}, ...}
    """
    rectangles = extract_table_rectangles(page)

    # 确定表头区域边界
    if header_region is None:
        header_region = find_header_region_bounds(page)
        if header_region is None:
            logger.error("Cannot find header region, unable to identify columns")
            return {}

    upper_y, lower_y = header_region
    logger.info(f"[COLUMN-DETECTION] Using header region: y=[{upper_y:.2f}, {lower_y:.2f}]")

    # 提取竖线（width < 2）在表头区域内
    vertical_lines = [r for r in rectangles
                      if (r['x1'] - r['x0']) < 2 and upper_y <= r['y0'] <= lower_y]

    logger.info(f"[COLUMN-DETECTION] Found {len(vertical_lines)} vertical lines in header region")

    if not vertical_lines:
        # 回退到旧方法：使用单元格矩形
        logger.warning("No vertical lines found in header region, falling back to cell rectangles")
        header_rects = [r for r in rectangles if upper_y <= r['y0'] <= lower_y]
        header_rects = [r for r in header_rects if 5 < (r['x1'] - r['x0']) < 150]
        header_rects.sort(key=lambda r: r['x0'])

        logger.info(f"[COLUMN-DETECTION] Found {len(header_rects)} cell rectangles in header region")
    else:
        # 使用竖线定义列边界
        vertical_lines.sort(key=lambda r: r['x0'])
        # 去重（x坐标接近的竖线合并）
        unique_x = []
        for line in vertical_lines:
            if not unique_x or abs(line['x0'] - unique_x[-1]) > 2:
                unique_x.append(line['x0'])

        logger.info(f"[COLUMN-DETECTION] Found {len(unique_x)} unique vertical lines (after dedup)")

        # 相邻竖线之间定义一列
        header_rects = []
        for i in range(len(unique_x) - 1):
            header_rects.append({
                'x0': unique_x[i],
                'x1': unique_x[i + 1],
                'y0': upper_y,
                'y1': lower_y
            })

    # 直接用配置顺序映射列（不再识别文本）
    columns = {}
    logger.info(f"[COLUMN-DETECTION] Identifying {len(header_rects)} columns in header region")
    for col_idx, rect in enumerate(header_rects):
        # 如果配置里定义了这一列的字段名，用配置的名称
        if col_idx < len(column_fields):
            field_name = column_fields[col_idx]
        else:
            # 超出配置的列用 unknown_1, unknown_2...
            field_name = f"unknown_{col_idx - len(column_fields) + 1}"

        columns[field_name] = {
            'x0': rect['x0'],
            'x1': rect['x1']
        }

        # 输出每列的详细信息
        logger.info(f"[COLUMN-DETECTION]   Column {col_idx}: '{field_name}' -> x=[{rect['x0']:.2f}, {rect['x1']:.2f}] width={rect['x1'] - rect['x0']:.2f}")

    logger.info(f"[COLUMN-DETECTION] Total {len(columns)} columns identified: {list(columns.keys())}")
    return columns


def extract_horizontal_lines(rectangles: List[Dict], start_y: float, end_y: float) -> List[float]:
    """
    提取横线的 y 坐标（用于精确定位数据行）

    Args:
        rectangles: 矩形列表
        start_y: 起始 y 坐标
        end_y: 结束 y 坐标

    Returns:
        排序后的横线 y 坐标列表
    """
    # 横线特征：高度很小（height < 2），宽度较大（width > 50）
    horizontal_lines = [r for r in rectangles
                        if start_y <= r['y0'] <= end_y and
                        (r['y1'] - r['y0']) < 2 and
                        (r['x1'] - r['x0']) > 50]

    # 提取 y 坐标并去重（合并相近的横线）
    y_coords = []
    for line in sorted(horizontal_lines, key=lambda r: r['y0']):
        if not y_coords or abs(line['y0'] - y_coords[-1]) > 2:
            y_coords.append(line['y0'])

    return y_coords


def cluster_rows_by_horizontal_lines(rectangles: List[Dict], horizontal_lines: List[float], columns: Optional[Dict[str, Dict]] = None) -> List[Tuple[float, List[Dict]]]:
    """
    使用横线分隔行（更精确的方法）

    相邻两条横线之间的区域 = 一行数据

    Args:
        rectangles: 矩形列表
        horizontal_lines: 横线 y 坐标列表（已排序）
        columns: 列定义字典（可选，用于纯网格线表格的回退）

    Returns:
        [(row_y, [rect, ...]), ...]
    """
    rows = []

    # 跳过第一条横线（block 顶部边界），从第二条开始
    # 每两条横线之间定义一行
    for i in range(len(horizontal_lines) - 1):
        upper_line = horizontal_lines[i]
        lower_line = horizontal_lines[i + 1]

        # 行的 y 坐标取中间值
        row_y = (upper_line + lower_line) / 2

        # 提取这一行的所有单元格（在两条横线之间）
        row_cells = [r for r in rectangles
                     if upper_line <= r['y0'] <= lower_line and
                     5 < (r['x1'] - r['x0']) < 150]

        # 回退：如果单元格矩形太少（< 5个），用竖线构造虚拟单元格（纯网格线表格）
        # 这样可以处理只有网格线没有单元格矩形的PDF
        if len(row_cells) < 5 and columns:
            logger.debug(f"[ROW-EXTRACT] Only {len(row_cells)} cell rectangles found between y={upper_line:.2f} and y={lower_line:.2f}, using columns to construct virtual cells")
            row_cells = []
            for field_name, col_info in columns.items():
                row_cells.append({
                    'x0': col_info['x0'],
                    'y0': upper_line,
                    'x1': col_info['x1'],
                    'y1': lower_line
                })

        if row_cells:
            rows.append((row_y, row_cells))

    return rows


def cluster_rows_by_y(rectangles: List[Dict], start_y: float, end_y: float, tolerance: float = 2) -> List[Tuple[float, List[Dict]]]:
    """
    按 y 坐标聚类矩形成行（旧方法，作为回退）

    Args:
        rectangles: 矩形列表
        start_y: 起始 y 坐标
        end_y: 结束 y 坐标
        tolerance: y 坐标容忍度

    Returns:
        [(row_y, [rect, ...]), ...]
    """
    # 过滤：只保留合理宽度的矩形（排除整行大矩形和竖线）
    table_rects = [r for r in rectangles
                   if start_y <= r['y0'] <= end_y and
                   5 < (r['x1'] - r['x0']) < 150]
    table_rects.sort(key=lambda r: r['y0'])

    rows = []
    if table_rects:
        current_row = [table_rects[0]]
        current_y = table_rects[0]['y0']

        for rect in table_rects[1:]:
            if abs(rect['y0'] - current_y) < tolerance:
                current_row.append(rect)
            else:
                rows.append((current_y, current_row))
                current_row = [rect]
                current_y = rect['y0']
        rows.append((current_y, current_row))

    return rows


def extract_cell_text(words: List[Tuple], cell_rect: Dict, tolerance: float = 2, debug_log: bool = False) -> str:
    """
    从 words 中提取矩形内的文字

    Args:
        words: page.get_text("words") 返回的词列表
        cell_rect: {'x0': float, 'y0': float, 'x1': float, 'y1': float}
        tolerance: 边界容忍度
        debug_log: 是否输出详细日志

    Returns:
        单元格内的文字
    """
    cell_words = []
    for w in words:
        # w = (x0, y0, x1, y1, text, ...)
        if (cell_rect['x0'] - tolerance <= w[0] and
            w[2] <= cell_rect['x1'] + tolerance and
            cell_rect['y0'] - tolerance <= w[1] and
            w[3] <= cell_rect['y1'] + tolerance):
            cell_words.append((w[1], w[4]))  # (y, text)
            if debug_log:
                logger.debug(f"[CELL-EXTRACT]       Word in cell: '{w[4]}' at ({w[0]:.2f}, {w[1]:.2f}, {w[2]:.2f}, {w[3]:.2f})")

    cell_words.sort()
    result = ' '.join(text for _, text in cell_words).strip()

    if debug_log and cell_words:
        logger.debug(f"[CELL-EXTRACT]     Cell [{cell_rect['x0']:.2f}, {cell_rect['y0']:.2f}, {cell_rect['x1']:.2f}, {cell_rect['y1']:.2f}] -> '{result}' ({len(cell_words)} words)")

    # 去除换行导致的多余空格：如果文本中包含空格，且空格前后都是字母/数字（不含标点），则去除空格
    # 示例："ACCUMULA TOR" -> "ACCUMULATOR", "100 200" -> "100200", "RFGD00099 03" -> "RFGD0009903"
    # 保留正常的多词文本，如 "FOR AIR" 不变（因为超过2个部分）
    import re
    # 检测模式：字母/数字 + 空格 + 字母/数字，且整体只包含字母数字和空格
    if ' ' in result and re.match(r'^[A-Za-z0-9 ]+$', result):
        # 进一步检测：如果只有一个空格（即2个部分）
        parts = result.split()
        if len(parts) == 2:
            # 两部分都是字母数字字符（不含其他符号），则去除空格
            part1_alnum = parts[0].isalnum()
            part2_alnum = parts[1].isalnum()

            if part1_alnum and part2_alnum:
                result = ''.join(parts)

    return result


def assign_cell_to_column(cell_x0: float, columns: Dict[str, Dict], tolerance: float = 10) -> Optional[str]:
    """
    根据单元格 x0 判断属于哪一列

    策略：找到包含 cell_x0 的列（在 x0 到 x1 范围内），选择距离最近的

    Args:
        cell_x0: 单元格的 x0 坐标
        columns: 列定义字典
        tolerance: x 坐标容忍度

    Returns:
        字段名，未匹配返回 None
    """
    candidates = []
    for field_name, col_info in columns.items():
        if col_info['x0'] - tolerance <= cell_x0 < col_info['x1']:
            distance = abs(cell_x0 - col_info['x0'])
            candidates.append((distance, field_name))

    if not candidates:
        return None

    candidates.sort()
    return candidates[0][1]


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

    from .preprocessor import clean_text

    for i, line in enumerate(lines):
        # 先清理文本（替换全角冒号等）
        line = clean_text(line)
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
                        # 取第一个空格之前的内容
                        code_part = name_and_code[1].strip()
                        if code_part:
                            # 找第一个空格的位置
                            space_idx = code_part.find(' ')
                            if space_idx > 0:
                                hs_code = code_part[:space_idx]
                            else:
                                # 没有空格，全部都是HS Code
                                hs_code = code_part
                        else:
                            hs_code = ""
                else:
                    desc_of_goods = rest.strip()

            goods_positions.append((i, hs_code, desc_of_goods))

        elif "SUB TOTAL" in line_upper:
            subtotal_positions.append(i)

    return goods_positions, subtotal_positions


def extract_invoice_goods_items(
    lines: List[str],
    goods_positions: List[Tuple[int, str, str]],
    subtotal_positions: List[int],
    pdf_path: Optional[str] = None,
    rows: Optional[List[Dict]] = None,
    column_config: str = "default"
) -> Tuple[List[Dict], List[str]]:
    """
    提取发票货物信息。

    提取逻辑：
        - 使用矩形边界识别表格列（如果提供 pdf_path）
        - 回退到固定 7 行算法（如果未提供 pdf_path）

    Args:
        lines: 纯文本行列表
        goods_positions: [(index, hs_code, desc_of_goods), ...]
        subtotal_positions: [index, ...]
        pdf_path: PDF 文件路径（可选，用于表格提取）
        rows: 预处理后的行列表（包含 page 信息，用于多页处理）
        column_config: 列配置键名（默认 "default"）

    Returns:
        (all_items, warnings)
        - all_items: 所有提取的货物项列表
        - warnings: 提取过程中的警告信息
    """
    all_items = []
    warnings = []

    # 如果提供了 PDF 路径，使用矩形边界提取
    if pdf_path:
        try:
            doc = fitz.open(pdf_path)

            # 找到截断后涉及的所有页面
            pages_to_process = []
            if rows:
                pages_to_process = sorted(set(row['page'] for row in rows))
                logger.info(f"Processing {len(pages_to_process)} pages after truncation: {pages_to_process}")
            else:
                # 回退：只处理第 1 页
                pages_to_process = [1]

            # 第 1 页：识别表头和列定义
            page = doc.load_page(pages_to_process[0] - 1)  # PyMuPDF 使用 0-based 索引

            # 查找表头区域边界（新方法）
            header_region = find_header_region_bounds(page)
            if not header_region:
                logger.warning("Cannot find header region, falling back to 7-line algorithm")
                doc.close()
                pdf_path = None  # 回退到旧算法
            else:
                # 加载列配置
                column_fields = load_column_config(config_key=column_config)
                if not column_fields:
                    logger.warning("Cannot load column config, falling back to 7-line algorithm")
                    doc.close()
                    pdf_path = None  # 回退到旧算法
                else:
                    # 识别列（使用新方法）
                    columns = identify_columns_from_config(page, column_fields, header_region)
                    if not columns:
                        logger.warning("Cannot identify columns, falling back to 7-line algorithm")
                        doc.close()
                        pdf_path = None  # 回退到旧算法
                    else:
                        logger.info(f"Using table extraction: found {len(columns)} columns")
                        from .preprocessor import clean_text

                        # 配对 DESCRIPTION 和 SUB TOTAL（基于行索引，自然支持跨页）
                    all_regions = []  # [(desc_page, desc_y, subtotal_page, subtotal_y), ...]

                    for goods_idx, hs_code, desc_of_goods in goods_positions:
                        # 找到后面最近的 SUB TOTAL
                        subtotal_idx = None
                        for st_idx in subtotal_positions:
                            if st_idx > goods_idx:
                                subtotal_idx = st_idx
                                break

                        # 通过 rows 查找页码和 y 坐标
                        if rows and goods_idx < len(rows):
                            desc_page = rows[goods_idx]['page']
                            desc_y = rows[goods_idx]['y0']
                        else:
                            # 回退：在第一页查找，使用表头区域下边界
                            desc_page = pages_to_process[0]
                            desc_y = header_region[1]  # 使用lower_y（下边界）

                        if subtotal_idx and rows and subtotal_idx < len(rows):
                            subtotal_page = rows[subtotal_idx]['page']
                            subtotal_y = rows[subtotal_idx]['y0']
                        else:
                            # 回退：假设在同一页
                            subtotal_page = desc_page
                            subtotal_y = 800  # 页面底部

                        all_regions.append((desc_page, desc_y, subtotal_page, subtotal_y))
                        logger.debug(f"Block {len(all_regions)}: DESCRIPTION at page {desc_page} y={desc_y:.1f}, SUB TOTAL at page {subtotal_page} y={subtotal_y:.1f}")

                    logger.info(f"Found {len(all_regions)} table regions (may cross pages)")

                    # 按块提取
                    for block_idx, (desc_page, desc_y, subtotal_page, subtotal_y) in enumerate(all_regions, start=1):
                        # 简化策略：按顺序匹配（block_idx-1 对应 goods_positions 的索引）
                        hs_code = ""
                        desc_of_goods = ""
                        subtotal_idx = None

                        if block_idx - 1 < len(goods_positions):
                            goods_idx, hs_code, desc_of_goods = goods_positions[block_idx - 1]

                            # 找到对应的 subtotal_idx
                            for st_idx in subtotal_positions:
                                if st_idx > goods_idx:
                                    subtotal_idx = st_idx
                                    break

                        if not hs_code:
                            warnings.append(f"[WARNING] Goods '{desc_of_goods}' at block {block_idx} does not have H.S Code!")

                        # 确定 block 的实际结束位置：下一个 DESCRIPTION（如果存在）
                        block_end_y = subtotal_y
                        block_end_page = subtotal_page

                        if block_idx < len(all_regions):
                            # 有下一个 block，用下一个 DESCRIPTION 作为当前 block 的结束
                            next_desc_page, next_desc_y, _, _ = all_regions[block_idx]
                            block_end_y = next_desc_y
                            block_end_page = next_desc_page
                            logger.debug(f"[BLOCK-BOUNDARY] Block {block_idx}: desc_y={desc_y:.2f}, next_desc_y={next_desc_y:.2f} (use next DESCRIPTION as boundary)")
                        else:
                            logger.debug(f"[BLOCK-BOUNDARY] Block {block_idx}: desc_y={desc_y:.2f}, subtotal_y={subtotal_y:.2f} (last block, use SUB TOTAL)")

                        # 提取矩形和文字（处理跨页情况）
                        if desc_page == block_end_page:
                            # 同页：直接提取
                            page_obj = doc.load_page(desc_page - 1)
                            rectangles = extract_table_rectangles(page_obj)
                            words = page_obj.get_text("words")

                            # 提取横线（DESCRIPTION 到 block_end 之间）
                            horizontal_lines = extract_horizontal_lines(rectangles, desc_y, block_end_y)
                            logger.info(f"[ROW-EXTRACT] Block {block_idx}: found {len(horizontal_lines)} horizontal lines (desc_y={desc_y:.2f}, block_end_y={block_end_y:.2f})")

                            # 使用横线分隔行
                            # 横线说明：第一条横线 = DESCRIPTION 行的下边界（也是第一行数据的上边界）
                            # 相邻两条横线之间 = 一行数据
                            if len(horizontal_lines) >= 2:
                                data_rows = cluster_rows_by_horizontal_lines(rectangles, horizontal_lines, columns)
                                logger.info(f"[ROW-EXTRACT] Block {block_idx}: extracted {len(data_rows)} data rows using horizontal lines")
                            else:
                                # 回退到旧方法
                                logger.warning(f"[ROW-EXTRACT] Block {block_idx}: insufficient horizontal lines ({len(horizontal_lines)}), falling back to y-clustering")
                                data_start_y = desc_y + 5
                                data_end_y = block_end_y - 5
                                data_rows = cluster_rows_by_y(rectangles, data_start_y, data_end_y)

                            # 解析每行（同页情况）
                            for row_idx, (row_y, cells) in enumerate(data_rows, start=1):
                                cells.sort(key=lambda c: c['x0'])
                                logger.debug(f"[ROW-EXTRACT] Block {block_idx}, Row {row_idx} at y={row_y:.2f}, {len(cells)} cells")

                                # 提取各字段
                                item_data = {
                                    'customer': '',
                                    'order_no': '',
                                    'u11_code': '',
                                    'customer_no': '',
                                    'sanhua_no': '',
                                    'quantity': '',
                                    'unit_price': '',
                                    'amount': '',
                                }

                                for cell_idx, cell in enumerate(cells):
                                    logger.debug(f"[CELL-EXTRACT]   Processing cell {cell_idx}: [{cell['x0']:.2f}, {cell['y0']:.2f}, {cell['x1']:.2f}, {cell['y1']:.2f}]")
                                    content = extract_cell_text(words, cell, debug_log=True)
                                    if not content:
                                        continue

                                    field_name = assign_cell_to_column(cell['x0'], columns)
                                    if field_name and field_name in item_data:
                                        if item_data[field_name]:
                                            item_data[field_name] += ' ' + content
                                        else:
                                            item_data[field_name] = content
                                        logger.debug(f"[CELL-EXTRACT]     Assigned to column '{field_name}': '{content}'")
                                    else:
                                        logger.debug(f"[CELL-EXTRACT]     Cell at x={cell['x0']:.2f} not assigned to any column (field_name={field_name})")

                                # 清理客户名
                                item_data['customer'] = clean_text(item_data['customer'])

                                # 验证：至少有 u11_code 或 sanhua_no
                                if item_data['u11_code']:
                                    logger.debug(f"[ROW-EXTRACT]   Extracted item: u11={item_data['u11_code']}, customer={item_data['customer']}, sanhua_no={item_data['sanhua_no']}")
                                    all_items.append({
                                        "block_idx": block_idx,
                                        "hs_code": hs_code if hs_code else "",
                                        "desc_of_goods": desc_of_goods,
                                        "subtotal_idx": subtotal_idx,
                                        "final_customers": item_data['customer'],
                                        "u11_code": item_data['u11_code'],
                                        "customers_no": item_data['customer_no'],
                                        "sanhua_no": item_data['sanhua_no'],
                                        "quantity": item_data['quantity'],
                                        "unit_price": item_data['unit_price'],
                                        "amount": item_data['amount']
                                    })
                                else:
                                    logger.warning(f"[ROW-EXTRACT] Block {block_idx}, Row {row_idx}: Skipped (no u11_code). customer={item_data['customer']}, sanhua_no={item_data['sanhua_no']}")

                        else:
                            # 跨页：分别提取第一页和第二页的数据行
                            # 第一页：从 desc_y 到页底
                            page_obj1 = doc.load_page(desc_page - 1)
                            rects1 = extract_table_rectangles(page_obj1)
                            words1 = page_obj1.get_text("words")
                            page_height1 = page_obj1.rect.height

                            # 提取第一页的横线
                            h_lines1 = extract_horizontal_lines(rects1, desc_y, page_height1)
                            if len(h_lines1) >= 2:
                                rows1 = cluster_rows_by_horizontal_lines(rects1, h_lines1, columns)
                                logger.info(f"[ROW-EXTRACT] Block {block_idx}, Page {desc_page}: found {len(h_lines1)} horizontal lines, extracted {len(rows1)} rows")
                            else:
                                logger.warning(f"[ROW-EXTRACT] Block {block_idx}, Page {desc_page}: insufficient horizontal lines ({len(h_lines1)}), falling back")
                                data_start_y1 = desc_y + 5
                                data_end_y1 = page_height1
                                rows1 = cluster_rows_by_y(rects1, data_start_y1, data_end_y1)

                            # 第二页：从页顶到 block_end_y
                            page_obj2 = doc.load_page(block_end_page - 1)
                            rects2 = extract_table_rectangles(page_obj2)
                            words2 = page_obj2.get_text("words")

                            # 提取第二页的横线
                            h_lines2 = extract_horizontal_lines(rects2, 0, block_end_y)
                            if len(h_lines2) >= 1:
                                # 第二页没有 DESCRIPTION 行，直接使用所有横线
                                rows2 = cluster_rows_by_horizontal_lines(rects2, h_lines2, columns)
                                logger.info(f"[ROW-EXTRACT] Block {block_idx}, Page {block_end_page}: found {len(h_lines2)} horizontal lines, extracted {len(rows2)} rows")
                            else:
                                logger.warning(f"[ROW-EXTRACT] Block {block_idx}, Page {block_end_page}: insufficient horizontal lines ({len(h_lines2)}), falling back")
                                data_start_y2 = 0
                                data_end_y2 = block_end_y - 5
                                rows2 = cluster_rows_by_y(rects2, data_start_y2, data_end_y2)

                            logger.info(f"Block {block_idx} crosses pages ({desc_page}→{block_end_page}): extracted {len(rows1)} rows from page {desc_page}, {len(rows2)} rows from page {block_end_page}")

                            # 处理第一页的行
                            for row_idx, (row_y, cells) in enumerate(rows1, start=1):
                                cells.sort(key=lambda c: c['x0'])
                                logger.debug(f"[ROW-EXTRACT] Block {block_idx}, Page {desc_page} Row {row_idx} at y={row_y:.2f}, {len(cells)} cells")

                                item_data = {
                                    'customer': '',
                                    'order_no': '',
                                    'u11_code': '',
                                    'customer_no': '',
                                    'sanhua_no': '',
                                    'quantity': '',
                                    'unit_price': '',
                                    'amount': '',
                                }

                                for cell_idx, cell in enumerate(cells):
                                    logger.debug(f"[CELL-EXTRACT]   Processing cell {cell_idx}: [{cell['x0']:.2f}, {cell['y0']:.2f}, {cell['x1']:.2f}, {cell['y1']:.2f}]")
                                    content = extract_cell_text(words1, cell, debug_log=True)  # 使用 words1
                                    if not content:
                                        continue

                                    field_name = assign_cell_to_column(cell['x0'], columns)
                                    if field_name and field_name in item_data:
                                        if item_data[field_name]:
                                            item_data[field_name] += ' ' + content
                                        else:
                                            item_data[field_name] = content
                                        logger.debug(f"[CELL-EXTRACT]     Assigned to column '{field_name}': '{content}'")
                                    else:
                                        logger.debug(f"[CELL-EXTRACT]     Cell at x={cell['x0']:.2f} not assigned to any column (field_name={field_name})")

                                item_data['customer'] = clean_text(item_data['customer'])

                                if item_data['u11_code'] or item_data['sanhua_no']:
                                    logger.debug(f"[ROW-EXTRACT]   Extracted item: u11={item_data['u11_code']}, customer={item_data['customer']}, sanhua_no={item_data['sanhua_no']}")
                                    all_items.append({
                                        "block_idx": block_idx,
                                        "hs_code": hs_code if hs_code else "",
                                        "desc_of_goods": desc_of_goods,
                                        "subtotal_idx": subtotal_idx,
                                        "final_customers": item_data['customer'],
                                        "u11_code": item_data['u11_code'],
                                        "customers_no": item_data['customer_no'],
                                        "sanhua_no": item_data['sanhua_no'],
                                        "quantity": item_data['quantity'],
                                        "unit_price": item_data['unit_price'],
                                        "amount": item_data['amount']
                                    })

                            # 处理第二页的行
                            for row_idx, (row_y, cells) in enumerate(rows2, start=1):
                                cells.sort(key=lambda c: c['x0'])
                                logger.debug(f"[ROW-EXTRACT] Block {block_idx}, Page {subtotal_page} Row {row_idx} at y={row_y:.2f}, {len(cells)} cells")

                                item_data = {
                                    'customer': '',
                                    'order_no': '',
                                    'u11_code': '',
                                    'customer_no': '',
                                    'sanhua_no': '',
                                    'quantity': '',
                                    'unit_price': '',
                                    'amount': '',
                                }

                                for cell_idx, cell in enumerate(cells):
                                    logger.debug(f"[CELL-EXTRACT]   Processing cell {cell_idx}: [{cell['x0']:.2f}, {cell['y0']:.2f}, {cell['x1']:.2f}, {cell['y1']:.2f}]")
                                    content = extract_cell_text(words2, cell, debug_log=True)  # 使用 words2
                                    if not content:
                                        continue

                                    field_name = assign_cell_to_column(cell['x0'], columns)
                                    if field_name and field_name in item_data:
                                        if item_data[field_name]:
                                            item_data[field_name] += ' ' + content
                                        else:
                                            item_data[field_name] = content
                                        logger.debug(f"[CELL-EXTRACT]     Assigned to column '{field_name}': '{content}'")
                                    else:
                                        logger.debug(f"[CELL-EXTRACT]     Cell at x={cell['x0']:.2f} not assigned to any column (field_name={field_name})")

                                item_data['customer'] = clean_text(item_data['customer'])

                                if item_data['u11_code'] or item_data['sanhua_no']:
                                    logger.debug(f"[ROW-EXTRACT]   Extracted item: u11={item_data['u11_code']}, customer={item_data['customer']}, sanhua_no={item_data['sanhua_no']}")
                                    all_items.append({
                                        "block_idx": block_idx,
                                        "hs_code": hs_code if hs_code else "",
                                        "desc_of_goods": desc_of_goods,
                                        "subtotal_idx": subtotal_idx,
                                        "final_customers": item_data['customer'],
                                        "u11_code": item_data['u11_code'],
                                        "customers_no": item_data['customer_no'],
                                        "sanhua_no": item_data['sanhua_no'],
                                        "quantity": item_data['quantity'],
                                        "unit_price": item_data['unit_price'],
                                        "amount": item_data['amount']
                                    })

                    doc.close()
        except Exception as e:
            logger.error(f"Table extraction failed: {e}")
            raise RuntimeError(f"Failed to extract invoice data: {e}")

    else:
        # PDF路径未提供，无法使用表格提取
        logger.error("PDF path is required for table extraction")
        raise ValueError("PDF path must be provided for invoice extraction")

    # 旧的7行算法已移除，不再支持回退
    if False:  # 保留代码结构，但永不执行
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


def extract_invoice_items(lines: List[str], debug: bool = False, pdf_path: Optional[str] = None, rows: Optional[List[Dict]] = None, column_config: str = "default") -> Tuple[List[Dict], str, str, List[str]]:
    """
    自动提取发票货物信息（不包含校验）。

    提取逻辑：
        1. 识别 "DESCRIPTION OF GOODS" 块，提取 HS Code 和货物描述
        2. 使用矩形边界识别表格列（如果提供 pdf_path）
        3. 回退到固定 7 行算法（如果未提供 pdf_path 或表格提取失败）
        4. 遇到 "SUB TOTAL" 标记当前块结束
        5. 按 PDF 中出现的块顺序分组

    Args:
        lines: 纯文本行列表（已预处理）
        debug: 是否打印调试信息
        pdf_path: PDF 文件路径（可选，用于表格提取）
        rows: 预处理后的行列表（包含 page 信息，用于多页处理）
        column_config: 列配置键名（默认 "default"）

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
    all_items, extraction_errors = extract_invoice_goods_items(lines, goods_positions, subtotal_positions, pdf_path, rows, column_config)

    # 按块分组
    groups = group_invoice_items_by_block(all_items)

    # 提取每个块的 subtotal 信息
    groups = extract_block_totals(groups, lines)

    return groups, global_total_quantity, global_total_usd, extraction_errors
