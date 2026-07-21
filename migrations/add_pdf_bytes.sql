-- Migration: Add pdf_bytes column to policy_documents table
-- This stores raw PDF bytes (base64-encoded) for accurate diff generation
-- Previously, diffs were computed from text chunks which lost table structure

ALTER TABLE policy_documents
ADD COLUMN pdf_bytes TEXT DEFAULT NULL;

-- Note: Any existing PolicyDocument records won't have pdf_bytes.
-- The system will continue to work:
-- - New uploads will store pdf_bytes
-- - New diffs will use pdf_bytes for accuracy
-- - Old diffs remain unchanged
-- 
-- To re-generate diffs for existing documents, you would need to re-upload them.
-- Or, if you have the original PDFs, you can:
-- 1. Read the PDF file
-- 2. Encode as base64
-- 3. Update the record: UPDATE policy_documents SET pdf_bytes = '...' WHERE id = '...'
