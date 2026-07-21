"""
Policy diff service.
Computes granular differences between two policy versions:
  - Page count change
  - Added / removed / modified text paragraphs
  - Table-level diffs (added rows, removed rows, changed cells)
  - Produces human-readable Markdown summary via Groq LLM
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Optional

from services.document_parser import ParsedDocument, TableContent

# ─── Data Classes ────────────────────────────────────────────────────────────

@dataclass
class ParagraphDiff:
    kind: str            # "added" | "removed" | "modified"
    old_text: Optional[str] = None
    new_text: Optional[str] = None
    page_hint: Optional[int] = None


@dataclass
class TableDiff:
    page_number: int
    table_index: int     # 1-indexed
    kind: str            # "added" | "removed" | "modified"
    added_rows: list[list[str]] = field(default_factory=list)
    removed_rows: list[list[str]] = field(default_factory=list)
    changed_cells: list[dict] = field(default_factory=list)


@dataclass
class StructuredDiff:
    base_name: str
    old_version: int
    new_version: int
    old_page_count: int
    new_page_count: int
    paragraph_diffs: list[ParagraphDiff] = field(default_factory=list)
    table_diffs: list[TableDiff] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.paragraph_diffs or self.table_diffs or
                    self.old_page_count != self.new_page_count)

    def to_dict(self) -> dict:
        return {
            "base_name": self.base_name,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "old_page_count": self.old_page_count,
            "new_page_count": self.new_page_count,
            "paragraph_diffs": [
                {
                    "kind": d.kind,
                    "old_text": d.old_text,
                    "new_text": d.new_text,
                    "page_hint": d.page_hint,
                }
                for d in self.paragraph_diffs
            ],
            "table_diffs": [
                {
                    "page_number": t.page_number,
                    "table_index": t.table_index,
                    "kind": t.kind,
                    "added_rows": t.added_rows,
                    "removed_rows": t.removed_rows,
                    "changed_cells": t.changed_cells,
                }
                for t in self.table_diffs
            ],
        }


# ─── Core Diff Logic ─────────────────────────────────────────────────────────

def _split_paragraphs(text: str) -> list[str]:
    """Split text into meaningful paragraphs, filtering empty lines."""
    paragraphs = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            current.append(stripped)
        else:
            if current:
                paragraphs.append(" ".join(current))
                current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _normalize_row(row: list[str]) -> str:
    """
    Normalize a row for intelligent comparison:
    - Join all cells into single string
    - Strip whitespace
    - Lowercase
    - Remove extra spaces
    This captures semantic equivalence: "Max 45 PL per FY" vs "Max 45 PL per financial year"
    """
    row_text = " ".join(str(cell).strip() for cell in row if cell)
    # Normalize spaces and case for fuzzy matching
    normalized = " ".join(row_text.split()).lower()
    return normalized


def _calculate_row_similarity(row1_normalized: str, row2_normalized: str) -> float:
    """
    Calculate similarity between two normalized row strings (0.0 to 1.0).
    Uses SequenceMatcher for fuzzy string matching.
    """
    return difflib.SequenceMatcher(None, row1_normalized, row2_normalized).ratio()


def _diff_tables(
    old_tables: list[TableContent],
    new_tables: list[TableContent],
) -> list[TableDiff]:
    """
    Pair tables by index, detect added/removed/modified tables.
    Uses FUZZY MATCHING to handle formatting variations and cell structure differences.
    
    This avoids false positives when tables have minor formatting changes like:
    - "45 PL per FY" vs "45 PL per financial year"
    - Different cell boundaries in PDF extraction
    - Whitespace/punctuation variations
    """
    diffs: list[TableDiff] = []
    max_len = max(len(old_tables), len(new_tables))
    SIMILARITY_THRESHOLD = 0.85  # 85% similarity = treat as same row (with potential modifications)

    for i in range(max_len):
        if i >= len(old_tables):
            # Entirely new table
            tbl = new_tables[i]
            diffs.append(TableDiff(
                page_number=tbl.page_number,
                table_index=i + 1,
                kind="added",
                added_rows=tbl.rows,
            ))
        elif i >= len(new_tables):
            # Removed table
            tbl = old_tables[i]
            diffs.append(TableDiff(
                page_number=tbl.page_number,
                table_index=i + 1,
                kind="removed",
                removed_rows=tbl.rows,
            ))
        else:
            old_tbl = old_tables[i]
            new_tbl = new_tables[i]

            # Normalize all rows for comparison
            old_rows_normalized = [(r, _normalize_row(r)) for r in old_tbl.rows]
            new_rows_normalized = [(r, _normalize_row(r)) for r in new_tbl.rows]

            # Track which rows have been matched
            matched_old_indices = set()
            matched_new_indices = set()
            
            added_rows = []
            removed_rows = []

            # For each NEW row, try to find a SIMILAR old row using fuzzy matching
            for new_idx, (new_row, new_norm) in enumerate(new_rows_normalized):
                best_match_idx = None
                best_similarity = 0.0

                # Find most similar row in old table
                for old_idx, (old_row, old_norm) in enumerate(old_rows_normalized):
                    if old_idx in matched_old_indices:
                        continue  # Already matched this old row
                    
                    similarity = _calculate_row_similarity(old_norm, new_norm)
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match_idx = old_idx

                if best_similarity >= SIMILARITY_THRESHOLD:
                    # Found a matching row - treat as existing (not added)
                    matched_old_indices.add(best_match_idx)
                    matched_new_indices.add(new_idx)
                else:
                    # No similar row found - this is a truly new row
                    added_rows.append(new_row)
                    matched_new_indices.add(new_idx)

            # Any old rows that weren't matched are removed
            for old_idx, (old_row, old_norm) in enumerate(old_rows_normalized):
                if old_idx not in matched_old_indices:
                    removed_rows.append(old_row)

            # Detect header changes
            changed_cells = []
            if old_tbl.headers != new_tbl.headers:
                changed_cells.append({
                    "type": "header",
                    "old": old_tbl.headers,
                    "new": new_tbl.headers,
                })

            if added_rows or removed_rows or changed_cells:
                diffs.append(TableDiff(
                    page_number=new_tbl.page_number,
                    table_index=i + 1,
                    kind="modified",
                    added_rows=added_rows,
                    removed_rows=removed_rows,
                    changed_cells=changed_cells,
                ))

    return diffs


def compute_diff(
    old_doc: ParsedDocument,
    new_doc: ParsedDocument,
    base_name: str,
    old_version: int,
    new_version: int,
) -> StructuredDiff:
    """
    Main entry point. Returns a StructuredDiff between two parsed documents.
    """
    old_paragraphs = _split_paragraphs(old_doc.full_text)
    new_paragraphs = _split_paragraphs(new_doc.full_text)

    # Use SequenceMatcher for paragraph-level diff
    matcher = difflib.SequenceMatcher(None, old_paragraphs, new_paragraphs, autojunk=False)
    paragraph_diffs: list[ParagraphDiff] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        elif tag == "insert":
            for j in range(j1, j2):
                paragraph_diffs.append(ParagraphDiff(kind="added", new_text=new_paragraphs[j]))
        elif tag == "delete":
            for i in range(i1, i2):
                paragraph_diffs.append(ParagraphDiff(kind="removed", old_text=old_paragraphs[i]))
        elif tag == "replace":
            old_chunk = old_paragraphs[i1:i2]
            new_chunk = new_paragraphs[j1:j2]
            max_chunk = max(len(old_chunk), len(new_chunk))
            for k in range(max_chunk):
                old_p = old_chunk[k] if k < len(old_chunk) else None
                new_p = new_chunk[k] if k < len(new_chunk) else None
                if old_p and new_p:
                    paragraph_diffs.append(
                        ParagraphDiff(kind="modified", old_text=old_p, new_text=new_p)
                    )
                elif new_p:
                    paragraph_diffs.append(ParagraphDiff(kind="added", new_text=new_p))
                else:
                    paragraph_diffs.append(ParagraphDiff(kind="removed", old_text=old_p))

    # Table diffs
    table_diffs = _diff_tables(old_doc.all_tables, new_doc.all_tables)

    return StructuredDiff(
        base_name=base_name,
        old_version=old_version,
        new_version=new_version,
        old_page_count=old_doc.page_count,
        new_page_count=new_doc.page_count,
        paragraph_diffs=paragraph_diffs,
        table_diffs=table_diffs,
    )


def build_diff_prompt(diff: StructuredDiff) -> str:
    """
    Build a prompt for the LLM to produce a human-readable diff summary.
    """
    lines = [
        f"You are an HR policy analyst. Summarise the changes between v{diff.old_version} "
        f"and v{diff.new_version} of the '{diff.base_name.replace('_', ' ').title()}' policy "
        f"in clear, professional Markdown for HR staff.\n",
        f"**Page count:** {diff.old_page_count} pages → {diff.new_page_count} pages\n",
    ]

    if diff.paragraph_diffs:
        lines.append("### Text Changes\n")
        for d in diff.paragraph_diffs[:40]:   # cap to avoid huge prompts
            if d.kind == "added":
                lines.append(f"- **ADDED:** {d.new_text[:300]}")
            elif d.kind == "removed":
                lines.append(f"- **REMOVED:** {d.old_text[:300]}")
            else:
                lines.append(f"- **CHANGED:**\n  - Before: {d.old_text[:200]}\n  - After: {d.new_text[:200]}")

    if diff.table_diffs:
        lines.append("\n### Table Changes\n")
        for t in diff.table_diffs:
            lines.append(f"**Table {t.table_index} (Page {t.page_number}) — {t.kind.upper()}**")
            if t.added_rows:
                lines.append(f"  Added rows: {t.added_rows[:5]}")
            if t.removed_rows:
                lines.append(f"  Removed rows: {t.removed_rows[:5]}")
            if t.changed_cells:
                lines.append(f"  Header change: {t.changed_cells}")

    lines.append(
        "\nWrite a concise, well-formatted Markdown summary (use bullet points and sections). "
        "Focus on what HR staff need to know. Do not hallucinate — only describe changes listed above."
    )
    return "\n".join(lines)
