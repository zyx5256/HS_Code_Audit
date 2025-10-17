"""
文本预处理模块

职责：
- 智能合并相邻行（解决换行拆分问题）
- 文本清理（括号标准化等）
- 不包含业务逻辑，只做通用文本处理
"""

import logging
from typing import List, Dict

logger = logging.getLogger("pdf_text")


def split_wide_lines(rows: List[Dict]) -> List[Dict]:
    """
    检测并拆分异常宽度的行（表格两列被合并）。

    检测条件：
        - 行宽 > 100px（正常单列文本宽度 < 80px）
        - 文本包含空格

    拆分策略：
        - 按最后一个空格拆分（客户名可能包含空格，但后续字段是纯数字字母）
        - 按字符数比例估算 x 坐标

    Args:
        rows: 包含坐标和文本的行列表

    Returns:
        拆分后的行列表

    Example:
        输入:  [{text: "AIFI(GOODMAN) 10205389943", x0: 34.92, x1: 147.23}]
        输出:  [
                 {text: "AIFI(GOODMAN)", x0: 34.92, x1: 约100},
                 {text: "10205389943", x0: 约100, x1: 147.23}
               ]
    """
    if not rows:
        return rows

    result = []
    split_count = 0

    for row in rows:
        width = row["x1"] - row["x0"]

        # 跳过 DESCRIPTION OF GOODS 行（避免误拆分导致 HS CODE 丢失）
        if "DESCRIPTION OF GOODS" in row["text"].upper():
            result.append(row)
            continue

        # 检测异常宽度（> 100px，正常单列 < 80px）
        if 100 < width < 200 and " " in row["text"]:
            # 按最后一个空格拆分
            last_space_idx = row["text"].rfind(" ")
            if last_space_idx > 0:
                text1 = row["text"][:last_space_idx].strip()
                text2 = row["text"][last_space_idx + 1:].strip()

                if text1 and text2:
                    split_count += 1

                    # 按字符数比例估算 x 坐标
                    len1 = len(text1)
                    len2 = len(text2)
                    total_len = len1 + len2
                    ratio1 = len1 / total_len
                    mid_x = row["x0"] + width * ratio1

                    # 第一部分（左列）
                    row1 = row.copy()
                    row1["text"] = text1
                    row1["x1"] = mid_x

                    # 第二部分（右列）
                    row2 = row.copy()
                    row2["text"] = text2
                    row2["x0"] = mid_x

                    result.append(row1)
                    result.append(row2)

                    # 使用logger而不是print，避免Windows终端编码问题
                    logger.debug(
                        f"[SPLIT-WIDE] Page {row['page']}, Line {row['index']}: "
                        f"width={width:.2f}px -> split into 2 parts"
                    )
                else:
                    result.append(row)
            else:
                result.append(row)
        else:
            result.append(row)

    if split_count > 0:
        logger.info(f"Split {split_count} wide line(s)")

    # 重新编号
    page_counters = {}
    for r in result:
        page = r["page"]
        page_counters[page] = page_counters.get(page, 0) + 1
        r["index"] = page_counters[page]

    return result


def split_abnormal_height_lines(rows: List[Dict]) -> List[Dict]:
    """
    检测并拆分异常行高的行（PyMuPDF底部对齐导致的误合并）。

    检测条件：
        - 行高 > 15px（正常行高约12px）
        - 文本包含两个空格（可能是两个独立字段被合并）

    拆分策略：
        - 按两个连续空格拆分文本
        - 第一部分保持原坐标，第二部分估算新坐标

    Args:
        rows: 包含坐标和文本的行列表

    Returns:
        拆分后的行列表

    Example:
        输入:  [{text: "10270065043 D01ACMP0012759", y0: 321.65, y1: 339.4}]
        输出:  [
                 {text: "10270065043", y0: 321.65, y1: 333.525},
                 {text: "D01ACMP0012759", y0: 327.525, y1: 339.4}
               ]
    """
    if not rows:
        return rows

    result = []
    split_count = 0

    for row in rows:
        height = row["y1"] - row["y0"]

        # 检测异常行高（> 15px，正常约12px）
        if height > 15 and " " in row["text"]:
            # 按空格拆分（只拆分成2部分）
            parts = row["text"].split(" ", 1)
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                split_count += 1

                # 计算字符数比例
                text1 = parts[0].strip()
                text2 = parts[1].strip()
                len1 = len(text1)
                len2 = len(text2)
                total_len = len1 + len2

                # 按字符数比例估算 x 坐标
                width = row["x1"] - row["x0"]
                ratio1 = len1 / total_len
                mid_x = row["x0"] + width * ratio1

                # 第一部分（保持原 y 坐标）
                row1 = row.copy()
                row1["text"] = text1
                row1["x1"] = mid_x

                # 第二部分（保持原 y 坐标）
                row2 = row.copy()
                row2["text"] = text2
                row2["x0"] = mid_x

                result.append(row1)
                result.append(row2)

                # 使用logger而不是print，避免Windows终端编码问题
                logger.debug(
                    f"[SPLIT] Page {row['page']}, Line {row['index']}: "
                    f"height={height:.2f}px -> split into 2 lines"
                )
            else:
                result.append(row)
        else:
            result.append(row)

    if split_count > 0:
        logger.info(f"Split {split_count} abnormal height line(s)")

    # 重新编号
    page_counters = {}
    for r in result:
        page = r["page"]
        page_counters[page] = page_counters.get(page, 0) + 1
        r["index"] = page_counters[page]

    return result


def merge_adjacent_lines(rows: List[Dict]) -> List[Dict]:
    """
    智能合并相邻行，解决货物编码等字段因换行被拆分的问题。

    合并条件（同时满足）：
        1. 同一页
        2. 垂直紧邻 <= 1 像素
        3. 水平位置满足以下之一：
           a) 居中对齐：中心点差异 <= 10px（换行后居中的情况）
           b) 左对齐：左右边界差异都 < 20px（宽度相近的换行）

    Args:
        rows: 包含坐标和文本的行列表
              格式: [{"page": int, "index": int, "x0": float, "y0": float,
                      "x1": float, "y1": float, "text": str}, ...]

    Returns:
        合并后的行列表，index 会重新编号

    Example:
        输入:  [{"text": "YCV5-43GTLA-1-"}, {"text": "U3"}]
        输出:  [{"text": "YCV5-43GTLA-1-U3"}]
    """
    if not rows:
        return rows

    merged = []
    i = 0
    while i < len(rows):
        current = rows[i].copy()
        j = i + 1

        # 尝试向后合并相邻行
        while j < len(rows):
            next_row = rows[j]

            # 必须在同一页
            if current["page"] != next_row["page"]:
                break

            # 计算垂直间距
            vertical_overlap = next_row["y0"] >= current["y0"] and next_row["y0"] - current["y1"] <= 3

            # 计算水平位置关系
            c_left, c_right = current["x0"], current["x1"]
            n_left, n_right = next_row["x0"], next_row["x1"]

            # 计算中心点（居中对齐的换行情况）
            c_center = (c_left + c_right) / 2
            n_center = (n_left + n_right) / 2
            is_centered = abs(n_center - c_center) <= 10

            # 计算水平左右边界差异（左对齐的换行情况）
            x_start_diff = abs(n_left - c_left)
            x_end_diff = abs(n_right - c_right)
            is_aligned = x_start_diff < 50 and x_end_diff < 50

            # 判断是否应该合并
            # 条件1：垂直重合
            # 条件2：中心点对齐（居中）或 左右边界都对齐（左对齐）
            if vertical_overlap and (is_centered or is_aligned):
                # 合并文本（去掉前后空格直接合并）
                current["text"] = current["text"].strip() + next_row["text"].strip()

                # 扩展坐标范围
                current["x0"] = min(current["x0"], next_row["x0"])
                current["y0"] = min(current["y0"], next_row["y0"])
                current["x1"] = max(current["x1"], next_row["x1"])
                current["y1"] = max(current["y1"], next_row["y1"])

                j += 1  # 继续尝试合并下一行
            else:
                break  # 不满足合并条件，停止

        merged.append(current)
        i = j  # 跳过已合并的行

    # 重新编号
    page_counters = {}
    for row in merged:
        page = row["page"]
        page_counters[page] = page_counters.get(page, 0) + 1
        row["index"] = page_counters[page]

    return merged


def clean_text(text: str) -> str:
    """
    清理文本。

    处理：
        1. 替换中文括号为英文括号
        2. 去掉括号前后的空格

    Args:
        text: 原始文本

    Returns:
        清理后的文本

    Example:
        "VALVE （THERMAL）" → "VALVE(THERMAL)"
    """
    # 替换中文括号为英文括号
    text = text.replace("（", "(").replace("）", ")")

    # 去掉括号前后的空格
    text = text.replace(" (", "(").replace("( ", "(")
    text = text.replace(" )", ")").replace(") ", ")")

    return text
