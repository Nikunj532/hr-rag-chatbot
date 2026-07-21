import re

# Supported file types for policy uploads
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}

# Policy name normalization: lowercase, spaces/hyphens -> underscores,
# strip anything that isn't alphanumeric or underscore.
POLICY_NAME_CLEAN_PATTERN = re.compile(r"[^a-z0-9_]+")

# ChromaDB collection name
CHROMA_COLLECTION_NAME = "hr_policies"

# Chunk settings
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

# Conversation
SUMMARY_THRESHOLD = 200          # messages before summarisation
SUMMARY_KEEP_RECENT = 20         # recent messages kept verbatim after summary

# Model names
GROQ_MODEL = "llama-3.3-70b-versatile"#"qwen/qwen3-32b"# 
# Free, local, no-API-key embedding model (runs on CPU via sentence-transformers)
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Retrieval
TOP_K_RETRIEVAL = 12  # Increased from 6 to get ~9,600 chars for better context
