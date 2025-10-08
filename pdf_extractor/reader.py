"""
PDF 文本读取模块

职责：
- 打开 PDF 文件
- 提取原始文本/行/块/词（带坐标）
- OCR 处理（可选）
- 返回原始数据，不做任何业务逻辑处理
"""

import os
import sys
import tempfile
import subprocess
import logging
from typing import List, Dict, Any, Optional, Tuple

import fitz  # PyMuPDF

logger = logging.getLogger("pdf_text")


class ExtractResult(dict):
    """统一返回结构：{'ok': bool, 'pages': List[str], 'meta': {...}, 'error': Optional[str]}"""
    pass


def ensure_file_exists(pdf_path: str) -> None:
    """
    检查文件是否存在。

    Args:
        pdf_path: PDF 文件路径

    Raises:
        FileNotFoundError: 文件不存在
    """
    if not os.path.isfile(pdf_path):
        logger.error("File not found: %s", pdf_path)
        raise FileNotFoundError(pdf_path)


def run_ocr(src_path: str, dst_path: str, lang: str) -> bool:
    """
    使用 ocrmypdf 对 PDF 添加 OCR 文本层。

    Args:
        src_path: 源 PDF 路径
        dst_path: 输出 PDF 路径
        lang: OCR 语言，如 "chi_sim+eng"

    Returns:
        是否成功
    """
    cmd = [sys.executable, "-m", "ocrmypdf", "--skip-text", "-l", lang, src_path, dst_path]
    try:
        res = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.debug("ocrmypdf stdout: %s", res.stdout.decode(errors="ignore")[:2000])
        logger.debug("ocrmypdf stderr: %s", res.stderr.decode(errors="ignore")[:2000])
        return True
    except subprocess.CalledProcessError as e:
        logger.error("ocrmypdf failed (exit=%s). cmd=%s", e.returncode, " ".join(cmd))
        logger.error("ocrmypdf stdout: %s", (e.output or b"").decode(errors="ignore")[:2000])
        logger.error("ocrmypdf stderr: %s", (e.stderr or b"").decode(errors="ignore")[:2000])
        return False


def prepare_ocr_pdf(pdf_path: str, ocr_lang: str) -> str:
    """
    为 dump/extract 准备 OCR 输入（如果需要）。

    Args:
        pdf_path: 原始 PDF 路径
        ocr_lang: OCR 语言，空字符串表示不使用 OCR

    Returns:
        处理后的 PDF 路径（可能是临时文件）
    """
    if not ocr_lang:
        return pdf_path

    td = tempfile.mkdtemp(prefix="pdf_ocr_")
    out_pdf = os.path.join(td, "ocr.pdf")
    cmd = [sys.executable, "-m", "ocrmypdf", "--skip-text", "-l", ocr_lang, pdf_path, out_pdf]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info("Prepared OCR PDF → %s", out_pdf)
        return out_pdf
    except subprocess.CalledProcessError as e:
        # exit=1-3: 错误, exit=4+: 警告（PDF 仍然生成）
        if e.returncode <= 3:
            logger.error("ocrmypdf failed (exit=%s).", e.returncode)
            logger.error("stdout: %s", (getattr(e, "output", b"") or b"").decode(errors="ignore")[:2000])
            logger.error("stderr: %s", (getattr(e, "stderr", b"") or b"").decode(errors="ignore")[:2000])
            return pdf_path
        else:
            logger.warning("ocrmypdf completed with warnings (exit=%s), continuing...", e.returncode)
            if os.path.isfile(out_pdf):
                return out_pdf
            return pdf_path


def extract_page_text(page, sort_text: bool, layout_mode: str) -> str:
    """
    从 PDF 页面提取文本。

    Args:
        page: PyMuPDF 页面对象
        sort_text: 是否按阅读顺序排序
        layout_mode: "text" 或 "blocks"

    Returns:
        页面文本内容
    """
    if layout_mode == "blocks":
        blocks = page.get_text("blocks", sort=sort_text)
        lines = []
        for x0, y0, x1, y1, text, block_no, block_type in blocks:
            if text:
                lines.append(text.strip())
        return "\n\n".join(lines)
    else:
        return page.get_text("text", sort=sort_text)


def extract_text_from_pdf(
    pdf_path: str,
    return_pages: bool = True,
    sort_text: bool = True,
    use_ocr_fallback: bool = False,
    ocr_lang: str = "eng",
    layout_mode: str = "text",
    pages: Optional[List[int]] = None,
) -> ExtractResult:
    """
    从 PDF 提取文本，支持 OCR 兜底。

    Args:
        pdf_path: PDF 文件路径
        return_pages: 是否按页返回
        sort_text: 是否按阅读顺序排序
        use_ocr_fallback: 空白页是否使用 OCR
        ocr_lang: OCR 语言
        layout_mode: "text" 或 "blocks"
        pages: 指定页码（1-based），None 表示全部

    Returns:
        ExtractResult 字典
    """
    ensure_file_exists(pdf_path)
    meta: Dict[str, Any] = {"src": pdf_path, "layout_mode": layout_mode, "ocr_lang": ocr_lang}
    result_pages: List[str] = []

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.exception("Failed to open PDF")
        return ExtractResult(ok=False, pages=[], meta=meta, error=f"open_failed: {e!r}")

    if doc.is_encrypted:
        try:
            doc.authenticate("")
        except Exception:
            doc.close()
            return ExtractResult(ok=False, pages=[], meta=meta, error="encrypted_pdf_not_supported")

    total_pages = doc.page_count
    sel_pages = pages or list(range(1, total_pages + 1))
    meta["total_pages"] = total_pages
    meta["selected_pages"] = sel_pages

    empty_indices = []
    try:
        for i in sel_pages:
            page = doc[i - 1]
            t = extract_page_text(page, sort_text=sort_text, layout_mode=layout_mode)
            t = t if t is not None else ""
            result_pages.append(t)
            logger.debug("Page %d extracted, %d chars", i, len(t))
            if len(t.strip()) == 0:
                empty_indices.append(i)
    finally:
        doc.close()

    # OCR 兜底
    if use_ocr_fallback and empty_indices:
        logger.info("Empty text detected on pages=%s; running OCR fallback...", empty_indices)
        with tempfile.TemporaryDirectory() as td:
            ocr_out = os.path.join(td, "out.ocr.pdf")
            if run_ocr(pdf_path, ocr_out, ocr_lang):
                try:
                    ocr_doc = fitz.open(ocr_out)
                    for i in empty_indices:
                        page = ocr_doc[i - 1]
                        t = extract_page_text(page, sort_text=sort_text, layout_mode=layout_mode)
                        result_pages[sel_pages.index(i)] = t or ""
                        logger.debug("Page %d re-extracted via OCR, %d chars", i, len(t or ""))
                finally:
                    ocr_doc.close()

    joined = "\n".join(result_pages)
    return ExtractResult(
        ok=True,
        pages=result_pages if return_pages else [],
        meta=meta | {"joined_chars": len(joined)},
        error=None
    )


def extract_lines_from_page(page) -> List[Tuple[float, float, float, float, str]]:
    """
    从页面提取带坐标的行。

    使用 page.get_text('dict') 解析 blocks→lines→spans 组装"行"。

    Args:
        page: PyMuPDF 页面对象

    Returns:
        [(x0, y0, x1, y1, text), ...]
    """
    info = page.get_text("dict")
    rows = []
    for blk in info.get("blocks", []):
        if blk.get("type", 0) != 0:
            continue
        for ln in blk.get("lines", []):
            x0 = y0 = float("inf")
            x1 = y1 = float("-inf")
            parts = []
            for sp in ln.get("spans", []):
                txt = (sp.get("text") or "").rstrip()
                if not txt:
                    continue
                parts.append(txt)
                if "bbox" in sp:
                    bx0, by0, bx1, by1 = sp["bbox"]
                    x0 = min(x0, float(bx0))
                    y0 = min(y0, float(by0))
                    x1 = max(x1, float(bx1))
                    y1 = max(y1, float(by1))
            text = " ".join(p.strip() for p in parts if p.strip())
            if text:
                if (x0 == float("inf")) or (y0 == float("inf")):
                    lbox = ln.get("bbox") or [0, 0, 0, 0]
                    x0, y0, x1, y1 = map(float, lbox)
                rows.append((round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2), text))

    # 兜底：如果没有提取到行，尝试用 blocks
    if not rows:
        blocks = page.get_text("blocks", sort=True)
        for b in blocks:
            if len(b) >= 5 and b[4] and str(b[4]).strip():
                bx0, by0, bx1, by1, txt = float(b[0]), float(b[1]), float(b[2]), float(b[3]), str(b[4]).rstrip()
                for part in txt.splitlines():
                    p = part.strip()
                    if p:
                        rows.append((bx0, by0, bx1, by1, p))

    return rows


def extract_blocks_from_page(page) -> List[Tuple[float, float, float, float, str]]:
    """
    从页面提取版面块。

    Args:
        page: PyMuPDF 页面对象

    Returns:
        [(x0, y0, x1, y1, text), ...]
    """
    blocks = page.get_text("blocks", sort=True)
    out = []
    for b in blocks:
        if len(b) >= 5 and b[4] and str(b[4]).strip():
            out.append((float(b[0]), float(b[1]), float(b[2]), float(b[3]), str(b[4]).rstrip()))
    return out


def extract_words_from_page(page) -> List[Tuple[float, float, float, float, str]]:
    """
    从页面提取词。

    Args:
        page: PyMuPDF 页面对象

    Returns:
        [(x0, y0, x1, y1, text), ...]
    """
    words = page.get_text("words")
    out = []
    for w in words:
        if len(w) >= 5:
            x0, y0, x1, y1, text = w[:5]
            if text and str(text).strip():
                out.append((float(x0), float(y0), float(x1), float(y1), str(text)))
    return out


def read_pdf_elements(
    pdf_path: str,
    mode: str = "lines",
    pages: Optional[List[int]] = None
) -> List[Dict[str, Any]]:
    """
    从 PDF 读取元素（行/块/词）。

    Args:
        pdf_path: PDF 文件路径
        mode: "lines", "blocks", 或 "words"
        pages: 指定页码（1-based），None 表示全部

    Returns:
        [{"page": int, "index": int, "x0": float, "y0": float,
          "x1": float, "y1": float, "text": str}, ...]
    """
    ensure_file_exists(pdf_path)
    doc = fitz.open(pdf_path)
    rows = []

    try:
        for pno in range(doc.page_count):
            page_num = pno + 1
            if pages and page_num not in pages:
                continue

            page = doc.load_page(pno)

            if mode == "blocks":
                items = extract_blocks_from_page(page)
            elif mode == "words":
                items = extract_words_from_page(page)
            else:  # lines
                items = extract_lines_from_page(page)

            for idx, (x0, y0, x1, y1, txt) in enumerate(items, start=1):
                rows.append({
                    "page": page_num,
                    "index": idx,
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "text": txt
                })
    finally:
        doc.close()

    return rows
