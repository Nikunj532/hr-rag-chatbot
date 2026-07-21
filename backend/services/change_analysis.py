"""
Change Analysis Service - Filters meaningful policy changes from noise.
Uses LLM to intelligently classify changes for ANY policy type - no hardcoded patterns.
Reusable across email, RAG chat, and UI for consistent change detection.
"""
import json
import logging
import re

from core.config import get_settings
from core.constants import GROQ_MODEL
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from services.diff_service import ParagraphDiff, StructuredDiff, TableDiff

logger = logging.getLogger(__name__)


def is_meaningful_change(old_text: str, new_text: str) -> bool:
    """
    Filter out pure formatting noise. The LLM will handle semantic analysis.
    Just needs to detect: structural changes, numeric changes, and significant text edits.
    """
    if not old_text or not new_text:
        return True
    
    old = old_text.strip()
    new = new_text.strip()
    
    # 1. Remove formatting characters (bullets, encoding, whitespace variations)
    cleanup_chars = ['•', '\uf0b7']
    old_clean = old
    new_clean = new
    for char in cleanup_chars:
        old_clean = old_clean.replace(char, ' ')
        new_clean = new_clean.replace(char, ' ')
    
    # Normalize whitespace (preserve line breaks for now as they may indicate structure)
    old_clean = ' '.join(old_clean.split())
    new_clean = ' '.join(new_clean.split())
    
    # If only formatting differs, skip it
    if old_clean == new_clean:
        return False
    
    # 2. Detect NUMERIC changes (e.g., 26 → 30 days)
    old_numbers = re.findall(r'\d+', old)
    new_numbers = re.findall(r'\d+', new)
    
    if old_numbers != new_numbers:
        return True  # Numeric change = meaningful
    
    # 3. Text must be substantially different (>30 chars and <95% similar)
    if len(old_clean) < 30 or len(new_clean) < 30:
        return False  # Very short diffs = formatting noise
    
    similarity = sum(1 for a, b in zip(old_clean, new_clean) if a == b) / max(len(old_clean), len(new_clean))
    if similarity >= 0.95:
        return False  # Too similar = likely punctuation/minor edits
    
    # If we got here: meaningful text change
    return True


class MeaningfulChanges:
    """Extract and organize meaningful changes from a StructuredDiff."""
    
    def __init__(self, diff: StructuredDiff):
        self.diff = diff
        
        # Filter for meaningful changes
        self.modified = [
            d for d in diff.paragraph_diffs 
            if d.kind == 'modified' and is_meaningful_change(d.old_text, d.new_text)
        ]
        self.added = [d for d in diff.paragraph_diffs if d.kind == 'added']
        self.removed = [d for d in diff.paragraph_diffs if d.kind == 'removed']
        
        # Filter for significant table changes
        self.tables = [
            t for t in diff.table_diffs 
            if len(t.added_rows) + len(t.removed_rows) + len(t.changed_cells) > 2
        ]
        
        # Extract specific policy changes
        self.specific_changes = self._extract_specific_changes()
    
    def _extract_specific_changes(self) -> dict:
        """
        Use LLM to extract meaningful policy changes from diffs.
        Works for ANY policy type - no hardcoded patterns.
        
        IMPORTANT: Send ALL diffs to LLM, not just pre-filtered ones.
        The LLM is better at semantic analysis than simple heuristics.
        Includes both paragraph and table diffs for complete coverage.
        """
        changes = {}
        
        try:
            # Collect ALL diffs (added, removed, modified) with full context.
            # The LLM will intelligently determine what's meaningful.
            # Don't pre-filter - give it complete picture to analyze semantically.
            
            all_para_diffs = self.diff.paragraph_diffs  # All: added, removed, modified
            all_table_diffs = self.diff.table_diffs      # All: added, removed, modified
            
            if not all_para_diffs and not all_table_diffs:
                logger.debug("No diffs found for LLM analysis")
                return changes
            
            # Limit to avoid token limits but include diverse types
            sample_para_diffs = all_para_diffs[:15]
            sample_table_diffs = all_table_diffs[:5]  # Include more tables to capture context
            
            # Build rich context for LLM with clear change type annotations
            changes_text_parts = []
            
            # Add paragraph diffs with TYPE information
            for i, d in enumerate(sample_para_diffs):
                if d.kind == 'added':
                    changes_text_parts.append(
                        f"Change {i+1} (NEW PARAGRAPH - not in v1):\n{d.new_text.strip()[:400]}"
                    )
                elif d.kind == 'removed':
                    changes_text_parts.append(
                        f"Change {i+1} (DELETED PARAGRAPH - removed from v2):\n{d.old_text.strip()[:400]}"
                    )
                else:  # modified
                    changes_text_parts.append(
                        f"Change {i+1} (MODIFIED PARAGRAPH):\nOld: {d.old_text.strip()[:300]}\nNew: {d.new_text.strip()[:300]}"
                    )
            
            # Add table diffs with TYPE information
            for i, t in enumerate(sample_table_diffs):
                change_num = len(sample_para_diffs) + i + 1
                
                if t.kind == 'added':
                    table_context = f"Change {change_num} (NEW TABLE - not in v1, page {t.page_number}):\n"
                    table_context += "All rows in new table:\n"
                    for row in t.added_rows[:5]:
                        row_text = " | ".join(str(cell) for cell in row)
                        table_context += f"  + {row_text[:150]}\n"
                        
                elif t.kind == 'removed':
                    table_context = f"Change {change_num} (DELETED TABLE - removed from v2, was on page {t.page_number}):\n"
                    table_context += "All rows that were deleted:\n"
                    for row in t.removed_rows[:5]:
                        row_text = " | ".join(str(cell) for cell in row)
                        table_context += f"  - {row_text[:150]}\n"
                        
                else:  # modified
                    table_context = f"Change {change_num} (MODIFIED TABLE, page {t.page_number}):\n"
                    if t.changed_cells:
                        table_context += "Header/Structure changed:\n"
                        for cell_change in t.changed_cells[:2]:
                            table_context += f"  {cell_change}\n"
                    if t.removed_rows:
                        table_context += f"Removed {len(t.removed_rows)} row(s):\n"
                        for row in t.removed_rows[:3]:
                            row_text = " | ".join(str(cell) for cell in row)
                            table_context += f"  - {row_text[:150]}\n"
                    if t.added_rows:
                        table_context += f"Added {len(t.added_rows)} row(s):\n"
                        for row in t.added_rows[:3]:
                            row_text = " | ".join(str(cell) for cell in row)
                            table_context += f"  + {row_text[:150]}\n"
                
                changes_text_parts.append(table_context)
            
            changes_text = "\n\n".join(changes_text_parts)
            
            # Use LLM to analyze changes generically
            llm = self._get_llm()
            
            prompt = f"""You are an expert HR policy analyst. Analyze ALL policy changes and extract MEANINGFUL business impacts.

UNDERSTANDING CHANGE TYPES:
The diffs are annotated as:
- "NEW PARAGRAPH" = Added in v2, not in v1 (could be new section, new rules, etc.)
- "DELETED PARAGRAPH" = Removed from v2 (existing section eliminated)
- "MODIFIED PARAGRAPH" = Exists in both, but content changed
- "NEW TABLE" = Added in v2, not in v1 (could be new leave type, new requirements table, etc.)
- "DELETED TABLE" = Removed from v2 (entire policy section deleted)
- "MODIFIED TABLE" = Exists in both, but rows/cells/structure changed

YOUR TASK: Extract MEANINGFUL changes - those that affect HR operations, employee entitlements, or compliance.

IMPORTANT FILTERING RULES:
1. IGNORE pure formatting (bullets •→•, spacing, column alignment, encoding)
2. REPORT all substantive changes:
   - New rules/requirements (even if newly added section) = IS a change
   - Modified numbers/entitlements = IS a change
   - Removed clauses/restrictions = IS a change
   - Changed approval processes = IS a change
   - New leave types with eligibility rules = IS a change (business expansion = operational impact)
3. For completely new sections/tables: Report if they introduce new policy items employees need to know about
4. For removed sections: Always report (policy was deleted/consolidated)
5. For modified: Report if values, rules, or requirements differ

For EACH meaningful change, provide:
1. What changed (concise description)
2. Type: leave_change, salary_change, approval_change, eligibility_change, new_requirement, hours_change, policy_addition, policy_removal, structural_change, or other
3. Impact: beneficial (improves for employees), restrictive (worsens for employees), neutral (administrative/clarification)
4. Affected employees: Who this applies to
5. Business impact: 1-2 sentence summary

Policy Changes:
{changes_text}

Return ONLY valid JSON with structure:
{{
  "changes": [
    {{
      "id": "change_1",
      "area": "E.g., Maternity Leave, Privilege Leave, Approvals, Salary",
      "type": "leave_change|salary_change|approval_change|eligibility_change|new_requirement|hours_change|other",
      "old_value": "Previous value or rule",
      "new_value": "New value or rule",
      "impact_direction": "beneficial|restrictive|neutral",
      "affected_employees": "Who this affects",
      "business_impact": "1-2 sentence summary"
    }}
  ]
}}"""
            
            response = llm.invoke([
                SystemMessage(content="You are an HR policy analyst. Return ONLY valid JSON. Ignore formatting-only changes."),
                HumanMessage(content=prompt)
            ])
            
            # Parse LLM response
            response_text = response.content.strip()
            logger.debug(f"LLM raw response: {response_text[:500]}")
            
            # Handle markdown code blocks
            if response_text.startswith("```json"):
                response_text = response_text[7:]  # Remove ```json
            if response_text.startswith("```"):
                response_text = response_text[3:]  # Remove ```
            if response_text.endswith("```"):
                response_text = response_text[:-3]  # Remove trailing ```
            response_text = response_text.strip()
            
            # Try to extract JSON if wrapped in other text
            if "{" in response_text and "}" in response_text:
                start_idx = response_text.find("{")
                end_idx = response_text.rfind("}") + 1
                response_text = response_text[start_idx:end_idx]
            
            parsed = json.loads(response_text)
            
            # Convert LLM response to our format
            # IMPORTANT: Filter out false positives (where old_value == new_value)
            for i, llm_change in enumerate(parsed.get('changes', []), 1):
                old_val = llm_change.get('old_value', '').strip()
                new_val = llm_change.get('new_value', '').strip()
                
                # Skip false positives: if old and new are identical, it's a formatting change
                if old_val and new_val and old_val == new_val:
                    logger.debug(f"Skipping false positive: {llm_change.get('area')} (old==new)")
                    continue
                
                change_id = f"change_{len(changes) + 1}"
                changes[change_id] = {
                    'type': llm_change.get('type', 'other'),
                    'area': llm_change.get('area', 'Policy'),
                    'old': old_val,
                    'new': new_val,
                    'impact_direction': llm_change.get('impact_direction', 'neutral'),
                    'affected': llm_change.get('affected_employees', 'All employees'),
                    'impact': llm_change.get('business_impact', 'Change detected')
                }
            
            logger.debug(f"Extracted {len(changes)} specific changes from LLM (after filtering false positives)")
        
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
        except Exception as e:
            logger.warning(f"LLM analysis failed: {e}")
        
        return changes
    
    def _get_llm(self):
        """Get LLM instance for analysis."""
        settings = get_settings()
        return ChatGroq(
            model=GROQ_MODEL,
            api_key=settings.groq_api_key,
            temperature=0.2,  # Low temp for consistent analysis
            max_tokens=1500,
        )
    
    def has_changes(self) -> bool:
        """Check if there are any meaningful changes."""
        return bool(self.modified or self.added or self.removed or self.tables or self.specific_changes)
    
    def get_summary_for_chat(self) -> str:
        """
        Generate summary for RAG chat responses.
        Uses LLM-analyzed changes for any policy type.
        """
        lines = []
        
        # Show specific changes first
        if self.specific_changes:
            for key, change in self.specific_changes.items():
                area = change.get('area', 'Policy Change')
                old_val = change.get('old', '')
                new_val = change.get('new', '')
                impact_dir = change.get('impact_direction', 'neutral')
                impact_text = change.get('impact', '')
                
                # Use appropriate emoji based on impact
                emoji = '✅' if impact_dir == 'beneficial' else '⚠️' if impact_dir == 'restrictive' else '📋'
                
                if old_val and new_val:
                    lines.append(f"{emoji} **{area}:** {old_val} → {new_val}")
                else:
                    lines.append(f"{emoji} **{area}**")
                lines.append(f"   Impact: {impact_text}")
        
        # Add summary of other changes if no specific changes extracted
        if not self.specific_changes and self.modified:
            lines.append(f"**{len(self.modified)} policy sections changed:**")
            for i, change in enumerate(self.modified[:3], 1):
                old = change.old_text.strip()[:50].replace('\n', ' ')
                new = change.new_text.strip()[:50].replace('\n', ' ')
                lines.append(f"  • {old}... → {new}...")
            if len(self.modified) > 3:
                lines.append(f"  ... and {len(self.modified) - 3} more")
        
        if self.added and not self.specific_changes:
            lines.append(f"\n**{len(self.added)} new rule(s) added**")
        
        if self.removed and not self.specific_changes:
            lines.append(f"\n**{len(self.removed)} rule(s) removed**")
        
        return "\n".join(lines) if lines else "No meaningful changes detected."
    
    def get_impact_for_ui(self) -> dict:
        """
        Generate structured data for UI display.
        Categorizes changes by impact direction (beneficial vs restrictive).
        """
        beneficial = [
            c for c in self.specific_changes.values()
            if c.get('impact_direction') == 'beneficial'
        ]
        restrictive = [
            c for c in self.specific_changes.values()
            if c.get('impact_direction') == 'restrictive'
        ]
        neutral = [
            c for c in self.specific_changes.values()
            if c.get('impact_direction') == 'neutral'
        ]
        
        return {
            "has_changes": self.has_changes(),
            "specific_changes": self.specific_changes,
            "modified_count": len(self.modified),
            "added_count": len(self.added),
            "removed_count": len(self.removed),
            "tables_affected": len(self.tables),
            "summary": self.get_summary_for_chat(),
            "impact_categories": {
                "beneficial": beneficial,
                "restrictive": restrictive,
                "neutral": neutral,
            }
        }
    
    def get_detailed_summary(self) -> str:
        """
        Full narrative summary for email or detailed view.
        Uses LLM analysis for any policy type, formatted as a table.
        """
        lines = []
        
        lines.append("## Policy Changes Summary")
        lines.append("")
        
        # Create table format for email
        if self.specific_changes:
            lines.append("| Impact | Section | Old Value | New Value | Business Impact | Affected |")
            lines.append("|--------|---------|-----------|-----------|-----------------|----------|")
            
            for key, change in self.specific_changes.items():
                area = change.get('area', 'Policy Change')
                old_val = change.get('old', '')
                new_val = change.get('new', '')
                impact_dir = change.get('impact_direction', 'neutral')
                impact_text = change.get('impact', '')
                affected = change.get('affected', 'All employees')
                
                # Use emoji indicator for impact
                emoji = '✅' if impact_dir == 'beneficial' else '⚠️' if impact_dir == 'restrictive' else '📋'
                
                # Truncate long values for table readability
                old_display = old_val[:40] + '...' if len(old_val) > 40 else old_val
                new_display = new_val[:40] + '...' if len(new_val) > 40 else new_val
                impact_display = impact_text[:50] + '...' if len(impact_text) > 50 else impact_text
                affected_display = affected[:25] + '...' if len(affected) > 25 else affected
                
                lines.append(f"| {emoji} {impact_dir.upper()[:3]} | {area} | {old_display} | {new_display} | {impact_display} | {affected_display} |")
            
            lines.append("")
            lines.append("---")
            lines.append("")
        
        # Add detailed impact analysis below table
        if self.specific_changes:
            lines.append("### Detailed Impact Analysis:")
            lines.append("")
            
            beneficial = [c for c in self.specific_changes.values() if c.get('impact_direction') == 'beneficial']
            restrictive = [c for c in self.specific_changes.values() if c.get('impact_direction') == 'restrictive']
            neutral = [c for c in self.specific_changes.values() if c.get('impact_direction') == 'neutral']
            
            if beneficial:
                lines.append("**✅ Beneficial Changes:**")
                for c in beneficial:
                    lines.append(f"  • **{c.get('area')}**: {c.get('impact')}")
                lines.append("")
            
            if restrictive:
                lines.append("**⚠️  Restrictive Changes:**")
                for c in restrictive:
                    lines.append(f"  • **{c.get('area')}**: {c.get('impact')}")
                lines.append("")
            
            if neutral:
                lines.append("**📋 Neutral Changes (Formatting):**")
                for c in neutral[:3]:  # Show only first 3 neutral changes
                    lines.append(f"  • **{c.get('area')}**: {c.get('impact')}")
                if len(neutral) > 3:
                    lines.append(f"  ... and {len(neutral) - 3} more formatting updates")
                lines.append("")
        
        if self.modified and not self.specific_changes:
            lines.append("### Policy Modifications:")
            lines.append("")
            lines.append("| # | Old Text | New Text |")
            lines.append("|---|----------|----------|")
            for i, change in enumerate(self.modified[:8], 1):
                old_text = change.old_text.strip()[:40].replace('\n', ' ')
                new_text = change.new_text.strip()[:40].replace('\n', ' ')
                lines.append(f"| {i} | {old_text}... | {new_text}... |")
            if len(self.modified) > 8:
                lines.append(f"| ... | ... | ... and {len(self.modified) - 8} more changes |")
            lines.append("")
        
        if self.added and not self.specific_changes:
            lines.append("### New Requirements:")
            for i, change in enumerate(self.added[:5], 1):
                text = change.new_text.strip()[:90].replace('\n', ' ')
                lines.append(f"  **{i}.** ✨ {text}...")
            if len(self.added) > 5:
                lines.append(f"  ... and {len(self.added) - 5} more")
            lines.append("")
        
        if self.removed and not self.specific_changes:
            lines.append("### Removed Provisions:")
            for i, change in enumerate(self.removed[:5], 1):
                text = change.old_text.strip()[:90].replace('\n', ' ')
                lines.append(f"  **{i}.** ❌ {text}...")
            if len(self.removed) > 5:
                lines.append(f"  ... and {len(self.removed) - 5} more")
            lines.append("")
        
        if self.tables and not self.specific_changes:
            lines.append("### Table Changes:")
            lines.append("")
            lines.append("| Page | Added Rows | Removed Rows | Modified Cells |")
            lines.append("|------|-----------|------------|----------------|")
            for table in self.tables[:4]:
                total_changes = len(table.added_rows) + len(table.removed_rows) + len(table.changed_cells)
                lines.append(f"| {table.page_number} | {len(table.added_rows)} | {len(table.removed_rows)} | {len(table.changed_cells)} |")
            lines.append("")
        
        if not self.has_changes():
            lines.append("*No meaningful policy changes detected. Only formatting updates.*")
            lines.append("")
        else:
            lines.append("### Action Items:")
            lines.append("1. Share this summary with affected employees")
            lines.append("2. Update your HR systems with new rules")
            lines.append("3. Brief your team on impact")
        
        lines.append("")
        lines.append("---")
        lines.append("*You can also ask the HR Chatbot: \"What changed in this policy?\" to get an interactive explanation.*")
        
        return "\n".join(lines)


def analyze_changes(diff: StructuredDiff) -> MeaningfulChanges:
    """
    Analyze a StructuredDiff and filter for meaningful changes.
    
    Usage:
        analysis = analyze_changes(diff_result)
        
        # For email
        email_body = analysis.get_detailed_summary()
        
        # For RAG chat
        chat_response = analysis.get_summary_for_chat()
        
        # For UI
        ui_data = analysis.get_impact_for_ui()
    """
    return MeaningfulChanges(diff)
