"""
Extract raw words from PDF using get_text("words") and save to CSV
Similar to debug mode output for get_text("dict")
"""
import fitz
import csv
import sys
import os

def extract_words_to_csv(pdf_path: str, output_path: str = None):
    """
    Extract words from PDF and save to CSV

    Args:
        pdf_path: PDF file path
        output_path: Output CSV path (default: pdf_name_words_raw.csv)
    """
    if not output_path:
        output_path = pdf_path.replace('.pdf', '_words_raw.csv')

    doc = fitz.open(pdf_path)
    total_pages = doc.page_count

    # Collect all words from all pages
    all_words = []

    for page_num in range(total_pages):
        page = doc.load_page(page_num)
        words = page.get_text("words")

        for word in words:
            if len(word) >= 8:
                x0, y0, x1, y1, text, block_no, line_no, word_no = word[:8]
                all_words.append({
                    'page': page_num + 1,
                    'word_index': len(all_words) + 1,
                    'x0': round(x0, 2),
                    'y0': round(y0, 2),
                    'x1': round(x1, 2),
                    'y1': round(y1, 2),
                    'width': round(x1 - x0, 2),
                    'height': round(y1 - y0, 2),
                    'text': text,
                    'block_no': block_no,
                    'line_no': line_no,
                    'word_no': word_no
                })

    doc.close()

    # Write to CSV
    if all_words:
        fieldnames = ['page', 'word_index', 'x0', 'y0', 'x1', 'y1', 'width', 'height', 'text', 'block_no', 'line_no', 'word_no']

        with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_words)

        print(f"Extracted {len(all_words)} words from {total_pages} page(s)")
        print(f"Output saved to: {output_path}")
    else:
        print("No words extracted!")

    return all_words


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_words_raw.py <PDF_file> [output.csv]")
        print("Example: python extract_words_raw.py invoice.pdf")
        print("         python extract_words_raw.py invoice.pdf output_words.csv")
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    extract_words_to_csv(pdf_path, output_path)
