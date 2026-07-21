-- Migration: generalize policy_documents for multi-format uploads (PDF/DOCX/TXT)
-- and add content-hash based duplicate detection.
--
-- Only needed if you already have a `policy_documents` table from before this
-- change (i.e. you've run the app at least once). If you're setting up fresh
-- and haven't uploaded anything yet, it's simpler to just drop the table and
-- let SQLAlchemy recreate it on next backend startup:
--
--   DROP TABLE IF EXISTS policy_diffs;
--   DROP TABLE IF EXISTS policy_documents;
--
-- Otherwise, run this to migrate in place without losing existing rows:

ALTER TABLE policy_documents RENAME COLUMN pdf_bytes TO file_bytes;

ALTER TABLE policy_documents
ADD COLUMN IF NOT EXISTS file_type VARCHAR(10) DEFAULT 'pdf';

ALTER TABLE policy_documents
ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);

CREATE INDEX IF NOT EXISTS ix_policy_documents_content_hash
ON policy_documents (content_hash);

-- Note: existing rows won't have content_hash populated, so duplicate
-- detection only kicks in going forward for newly uploaded versions.
