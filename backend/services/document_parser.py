"""
Document parsing service — supports PDF, DOCX, and TXT.

- PDF: pdfplumber for accurate text + table extraction (page-aware).
- DOCX: python-docx for paragraph + table extraction (single logical "page",
  since .docx has no reliable page-break concept without a rendering engine).
- TXT: plain text, single "page".

All three funnel into the same ParsedDocument/PageContent/TableContent shape
so downstream code (chunking, diffing, retrieval) doesn't need to know or
care what the original file format was.
"""
from __future__ import annotations
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pdfplumber


@dataclass
class TableContent:
    page_number: int
    headers: list[str]
    rows: list[list[str]]

    def to_text(self) -> str:
        """Convert table to pipe-delimited text for embedding."""
        lines = []
        if self.headers:
            lines.append(" | ".join(str(h) for h in self.headers))
            lines.append("-" * (sum(len(str(h)) for h in self.headers) + 3 * len(self.headers)))
        for row in self.rows:
            lines.append(" | ".join(str(c) if c is not None else "" for c in row))
        return "\n".join(lines)


@dataclass
class PageContent:
    page_number: int          # 1-indexed
    text: str                 # plain text (tables replaced with markers)
    tables: list[TableContent] = field(default_factory=list)

    def full_text(self) -> str:
        """Text with table content inlined."""
        result = self.text
        for i, tbl in enumerate(self.tables):
            placeholder = f"[TABLE_{i+1}_PAGE_{self.page_number}]"
            table_text = f"\n--- Table {i+1} (Page {self.page_number}) ---\n{tbl.to_text()}\n---\n"
            result = result.replace(placeholder, table_text)
        return result


@dataclass
class ParsedDocument:
    filename: str
    pages: list[PageContent]
    page_count: int
    char_count: int

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.full_text() for p in self.pages)

    @property
    def all_tables(self) -> list[TableContent]:
        tables = []
        for p in self.pages:
            tables.extend(p.tables)
        return tables


# ─── PDF ───────────────────────────────────────────────────────────────────

def parse_pdf(file_bytes: bytes, filename: str) -> ParsedDocument:
    """
    Parse a PDF into structured page content with table detection.
    Tables are extracted separately and also kept inline in text.
    """
    pages: list[PageContent] = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables_on_page: list[TableContent] = []
            raw_tables = page.extract_tables()

            for tbl_data in (raw_tables or []):
                if not tbl_data:
                    continue
                headers = [str(c) if c is not None else "" for c in tbl_data[0]]
                rows = [
                    [str(c) if c is not None else "" for c in row]
                    for row in tbl_data[1:]
                ]
                tables_on_page.append(
                    TableContent(page_number=page_num, headers=headers, rows=rows)
                )

            raw_text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""

            text_with_placeholders = raw_text
            for i in range(len(tables_on_page)):
                text_with_placeholders += f"\n[TABLE_{i+1}_PAGE_{page_num}]"

            pages.append(
                PageContent(page_number=page_num, text=text_with_placeholders, tables=tables_on_page)
            )

    full = "\n\n".join(p.full_text() for p in pages)
    return ParsedDocument(filename=filename, pages=pages, page_count=len(pages), char_count=len(full))


# ─── DOCX ──────────────────────────────────────────────────────────────────

def parse_docx(file_bytes: bytes, filename: str) -> ParsedDocument:
    """
    Parse a .docx into a single logical page (Word doesn't expose reliable
    page boundaries without rendering). Paragraphs and tables are extracted
    in document order; tables use the same inline-placeholder approach as PDF
    so the diff engine and chunker treat them identically.
    """
    from docx import Document as DocxDocument

    doc = DocxDocument(io.BytesIO(file_bytes))

    tables: list[TableContent] = []
    for tbl in doc.tables:
        rows_data = [[cell.text for cell in row.cells] for row in tbl.rows]
        if not rows_data:
            continue
        headers = rows_data[0]
        rows = rows_data[1:]
        tables.append(TableContent(page_number=1, headers=headers, rows=rows))

    paragraph_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    text_with_placeholders = paragraph_text
    for i in range(len(tables)):
        text_with_placeholders += f"\n[TABLE_{i+1}_PAGE_1]"

    page = PageContent(page_number=1, text=text_with_placeholders, tables=tables)
    full = page.full_text()

    return ParsedDocument(filename=filename, pages=[page], page_count=1, char_count=len(full))


# ─── TXT ───────────────────────────────────────────────────────────────────

def parse_txt(file_bytes: bytes, filename: str) -> ParsedDocument:
    """Parse a plain-text file as a single page, no tables."""
    text = file_bytes.decode("utf-8", errors="replace")
    page = PageContent(page_number=1, text=text, tables=[])
    return ParsedDocument(filename=filename, pages=[page], page_count=1, char_count=len(text))


# ─── Dispatcher ────────────────────────────────────────────────────────────

_PARSERS = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".txt": parse_txt,
}


def parse_document(file_bytes: bytes, filename: str) -> ParsedDocument:
    """Dispatch to the right parser based on file extension."""
    ext = Path(filename).suffix.lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported: {', '.join(_PARSERS.keys())}"
        )
    return parser(file_bytes, filename)
