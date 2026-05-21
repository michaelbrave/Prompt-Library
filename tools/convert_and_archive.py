#!/usr/bin/env python3
"""Convert PDF and EPUB files to text, then move originals to Archive folder."""

import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_DIR = os.path.join(SCRIPT_DIR, "Archive")


def ensure_archive():
    os.makedirs(ARCHIVE_DIR, exist_ok=True)


def extract_pdf_text(pdf_path):
    try:
        import pypdf
        reader = pypdf.PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n\n"
        return text
    except ImportError:
        pass

    try:
        import pdfplumber
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n\n"
        return text
    except ImportError:
        pass

    result = subprocess.run(
        ["pdftotext", "-layout", pdf_path, "-"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout

    print(f"  WARNING: No PDF library available for {os.path.basename(pdf_path)}")
    return ""


def extract_epub_text(epub_path):
    try:
        from ebooklib import epub
        book = epub.read_epub(epub_path)
        text = ""
        for item in book.get_items_of_type(9):  # DOCUMENT type
            text += item.get_content().decode("utf-8", errors="ignore") + "\n\n"
        import re
        text = re.sub(r"<[^>]+>", "", text)
        return text
    except ImportError:
        pass

    result = subprocess.run(
        ["ebook-convert", epub_path, "-"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout

    print(f"  WARNING: No EPUB library available for {os.path.basename(epub_path)}")
    return ""


def process_files(extension, extract_func):
    files = [
        f for f in os.listdir(SCRIPT_DIR)
        if f.lower().endswith(extension) and os.path.isfile(os.path.join(SCRIPT_DIR, f))
    ]

    if not files:
        print(f"No {extension.upper()} files found.")
        return

    print(f"Found {len(files)} {extension.upper()} file(s).")

    for filename in sorted(files):
        filepath = os.path.join(SCRIPT_DIR, filename)
        txt_filename = os.path.splitext(filename)[0] + ".txt"
        txt_filepath = os.path.join(SCRIPT_DIR, txt_filename)

        print(f"  Converting: {filename}")
        text = extract_func(filepath)

        if text.strip():
            with open(txt_filepath, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"    -> {txt_filename}")
        else:
            print(f"    -> No text extracted, skipping .txt creation")

        archive_path = os.path.join(ARCHIVE_DIR, filename)
        shutil.move(filepath, archive_path)
        print(f"    -> Moved to Archive/")


def main():
    ensure_archive()

    print("=== Processing PDF files ===")
    process_files(".pdf", extract_pdf_text)

    print("\n=== Processing EPUB files ===")
    process_files(".epub", extract_epub_text)

    print("\nDone.")


if __name__ == "__main__":
    main()
