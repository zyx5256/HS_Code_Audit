#!/usr/bin/env python3
"""
HS Code 审计工具 - CLI 入口

命令行用法：
    python get_text_from_pdf.py dump invoice.pdf --mode lines --out lines.csv
    python get_text_from_pdf.py extract invoice.pdf --rules rules.json --out result.json
    python get_text_from_pdf.py auto invoice.pdf --out result.json

兼容旧用法：
    python get_text_from_pdf.py invoice.pdf --out text.txt

依赖：
    pip install pymupdf
    可选 OCR 支持：ocrmypdf + tesseract-ocr
"""

from pdf_extractor.cli import main

if __name__ == "__main__":
    main()
