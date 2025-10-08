"""
PDF 发票文本提取和校验工具

模块架构（按数据流）：
    reader.py      → PDF 文本读取（PyMuPDF + OCR）
    preprocessor.py → 文本预处理（换行合并、清理）
    extractor.py    → 内容抽取算法（截断、规则匹配、发票解析）
    validator.py    → 数据校验（三层校验）
    writer.py       → 输出模块（JSON/CSV/JSONL）
    cli.py          → 命令行接口（主入口）

公共 API：
    extract_text_from_pdf   - 基础文本提取
    read_pdf_elements       - 读取带坐标的行/块/词
    merge_adjacent_lines    - 智能合并相邻行
    extract_invoice_items   - 发票货物自动提取
    validate_invoice_data   - 三层校验
    write_json/csv/jsonl    - 格式化输出
"""

__version__ = "2.0.0"

# === Reader 模块 ===
from .reader import (
    ExtractResult,
    extract_text_from_pdf,
    read_pdf_elements,
    prepare_ocr_pdf,
    ensure_file_exists,
)

# === Preprocessor 模块 ===
from .preprocessor import (
    merge_adjacent_lines,
    clean_text,
)

# === Extractor 模块 ===
from .extractor import (
    truncate_at_marker,
    extract_by_rules,
    extract_invoice_items,
)

# === Validator 模块 ===
from .validator import (
    validate_invoice_data,
    parse_number,
)

# === Writer 模块 ===
from .writer import (
    write_json,
    write_jsonl,
    write_csv,
    write_auto,
    print_json,
    print_jsonl,
)

__all__ = [
    # 版本
    "__version__",

    # Reader
    "ExtractResult",
    "extract_text_from_pdf",
    "read_pdf_elements",
    "prepare_ocr_pdf",
    "ensure_file_exists",

    # Preprocessor
    "merge_adjacent_lines",
    "clean_text",

    # Extractor
    "truncate_at_marker",
    "extract_by_rules",
    "extract_invoice_items",

    # Validator
    "validate_invoice_data",
    "parse_number",

    # Writer
    "write_json",
    "write_jsonl",
    "write_csv",
    "write_auto",
    "print_json",
    "print_jsonl",
]
