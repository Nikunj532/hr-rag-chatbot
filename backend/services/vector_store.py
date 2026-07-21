"""
Vector store service using ChromaDB + free local HuggingFace embeddings.

API compatibility notes:
- chromadb 1.x: PersistentClient(path=...) only, Settings class removed
- langchain-chroma 1.x: Chroma class moved to langchain_chroma, persist() removed
  (persistence is automatic), collection_metadata still supported
- langchain 1.x: RecursiveCharacterTextSplitter moved to langchain_text_splitters
- langchain-huggingface: HuggingFaceEmbeddings runs sentence-transformers models
  locally on CPU — no API key, no network calls, completely free.
"""
from __future__ import annotations

import logging
from typing import Optional

import chromadb
from core.config import get_settings
from core.constants import (CHROMA_COLLECTION_NAME, CHUNK_OVERLAP, CHUNK_SIZE,
                            EMBEDDING_MODEL, TOP_K_RETRIEVAL)
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from services.document_parser import ParsedDocument

logger = logging.getLogger(__name__)

_embeddings_cache: Optional[HuggingFaceEmbeddings] = None
_chroma_client_cache: Optional[chromadb.PersistentClient] = None
_vectorstore_cache: Optional[Chroma] = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    """
    Free, local embedding model — downloads once from HuggingFace Hub on first
    run (cached under ~/.cache/huggingface) then runs entirely on CPU with no
    API key and no per-call cost.
    """
    global _embeddings_cache
    if _embeddings_cache is None:
        _embeddings_cache = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embeddings_cache


def _get_chroma_client() -> chromadb.PersistentClient:
    """
    chromadb 1.x: only accepts path= argument.

    IMPORTANT: cached as a process-wide singleton. Repeatedly opening a fresh
    PersistentClient against the same on-disk SQLite-backed store was the
    root cause of unreliable/empty query results — a freshly-opened client's
    first query sometimes wouldn't see fully-synced data (especially under
    Windows' stricter SQLite file-locking behavior), while a second client
    opened moments later would. A single long-lived client avoids the churn
    entirely. There were 8 separate call sites creating fresh clients before
    this fix — all of them now share one client via this function.
    """
    global _chroma_client_cache
    if _chroma_client_cache is None:
        settings = get_settings()
        _chroma_client_cache = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return _chroma_client_cache


def _get_vectorstore() -> Chroma:
    """Cached singleton — see _get_chroma_client() for why this matters."""
    global _vectorstore_cache
    if _vectorstore_cache is None:
        client = _get_chroma_client()
        _vectorstore_cache = Chroma(
            collection_name=CHROMA_COLLECTION_NAME,
            client=client,
            embedding_function=_get_embeddings(),
            collection_metadata={"hnsw:space": "cosine"},
        )
    return _vectorstore_cache


# ─── Chunking ────────────────────────────────────────────────────────────────

def _build_chunks(
    parsed: ParsedDocument,
    base_name: str,
    version: int,
    doc_id: str,
) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks: list[Document] = []

    for page in parsed.pages:
        page_text = page.full_text()
        if not page_text.strip():
            continue

        splits = splitter.split_text(page_text)
        for idx, chunk_text in enumerate(splits):
            has_table = "---" in chunk_text and "|" in chunk_text
            chunks.append(
                Document(
                    page_content=chunk_text,
                    metadata={
                        "doc_id": doc_id,
                        "base_name": base_name,
                        "version": version,
                        "filename": parsed.filename,
                        "page_number": page.page_number,
                        "chunk_index": idx,
                        "has_table": has_table,
                        "page_count": parsed.page_count,
                        "policy_name": base_name.replace("_", " ").title(),
                        "source": f"{parsed.filename}#page{page.page_number}",
                    },
                )
            )

    return chunks


# ─── Public API ──────────────────────────────────────────────────────────────

def ingest_document(
    parsed: ParsedDocument,
    base_name: str,
    version: int,
    doc_id: str,
) -> int:
    chunks = _build_chunks(parsed, base_name, version, doc_id)
    if not chunks:
        logger.warning("No chunks generated for %s v%s", base_name, version)
        return 0

    vectorstore = _get_vectorstore()
    ids = [
        f"{base_name}_v{version}_p{c.metadata['page_number']}_c{c.metadata['chunk_index']}"
        for c in chunks
    ]

    vectorstore.add_documents(documents=chunks, ids=ids)
    logger.info("Ingested %d chunks for %s v%s", len(chunks), base_name, version)
    return len(chunks)


def get_all_policy_names() -> list[str]:
    try:
        client = _get_chroma_client()
        collection = client.get_or_create_collection(CHROMA_COLLECTION_NAME)
        results = collection.get(include=["metadatas"], limit=10000)
        names = list({m.get("base_name") for m in results["metadatas"] if m.get("base_name")})
        return sorted(names)
    except Exception:
        return []


def _normalize_policy_name(base_name: Optional[str]) -> Optional[str]:
    """
    Normalize policy name from classifier output to match database format.
    
    Classifier outputs: "leave_policy", "travel_policy", "office_time", etc.
    Database has: "leavepolicy", "travel", "officetime", "noticeperiod", "separation"
    
    Strategy: Try multiple normalization approaches to find a database match.
    """
    if not base_name:
        return None
    
    # Get all valid policy names in database
    valid_names = get_all_policy_names()
    
    # Try multiple normalization strategies in order
    strategies = [
        base_name.lower(),                           # 1. Just lowercase
        base_name.replace("_", "").lower(),          # 2. Remove underscores
        (base_name.replace("_policy", "")            # 3. Remove "_policy" suffix
         .replace("_", "").lower()),
        (base_name.replace("_", "")                  # 4. Remove underscores, then "policy"
         .replace("policy", "").lower()),
    ]
    
    # Return first strategy that matches a valid policy
    for strategy_result in strategies:
        if strategy_result in valid_names:
            return strategy_result
    
    # If no match, return the best guess (underscores removed)
    return base_name.replace("_", "").lower()


def get_retriever(
    base_name: Optional[str] = None,
    version: Optional[int] = None,
    top_k: int = TOP_K_RETRIEVAL,
):
    vectorstore = _get_vectorstore()

    # Normalize base_name using smart strategy matching
    base_name = _normalize_policy_name(base_name)

    where_filter: Optional[dict] = None
    if base_name and version:
        # If both specified, use them
        where_filter = {"$and": [{"base_name": base_name}, {"version": version}]}
    elif base_name:
        # If only base_name specified, search that policy across all versions
        # (ChromaDB will naturally prioritize semantic similarity, including latest)
        where_filter = {"base_name": base_name}
    # If neither specified, search all policies (no filter)

    search_kwargs = {
        "k": top_k,
    }
    # Only include "filter" when we actually have one — passing filter=None
    # gets treated as filter={} by ChromaDB, which matches ZERO documents
    # rather than "no filter".
    if where_filter is not None:
        search_kwargs["filter"] = where_filter

    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs=search_kwargs,
    )
    return retriever


def get_documents_for_query(query: str, base_name: Optional[str] = None, top_k: int = TOP_K_RETRIEVAL) -> list[Document]:
    """
    Main retrieval entry point — handles both single-policy and cross-policy queries.

    - If base_name is given: filtered retrieval against that policy only
      (unchanged behavior).
    - If base_name is None: instead of a single global similarity search
      (which can let 1-2 semantically-dominant policies crowd out every
      other uploaded policy from the results), retrieve a BALANCED sample —
      top_k/n_policies chunks from each known policy — so a query like
      "summarize all policies" reliably pulls from every document, not just
      whichever ranks highest for that specific wording.
    """
    if base_name:
        retriever = get_retriever(base_name=base_name, top_k=top_k)
        try:
            return retriever.invoke(query)
        except Exception as exc:
            logger.error("get_documents_for_query failed for %s: %s", base_name, exc)
            return []

    policy_names = get_all_policy_names()
    if not policy_names:
        return []
    if len(policy_names) == 1:
        retriever = get_retriever(base_name=policy_names[0], top_k=top_k)
        try:
            return retriever.invoke(query)
        except Exception as exc:
            logger.error("get_documents_for_query failed for %s: %s", policy_names[0], exc)
            return []

    # Balanced retrieval: at least a few chunks per policy, guaranteed.
    per_policy_k = max(2, top_k // len(policy_names))
    all_docs: list[Document] = []
    seen_ids: set[str] = set()

    for name in policy_names:
        retriever = get_retriever(base_name=name, top_k=per_policy_k)
        try:
            docs = retriever.invoke(query)
        except Exception as exc:
            logger.error("Balanced retrieval failed for %s: %s", name, exc)
            docs = []
        for d in docs:
            key = f"{d.metadata.get('base_name')}_{d.metadata.get('version')}_p{d.metadata.get('page_number')}_c{d.metadata.get('chunk_index')}"
            if key not in seen_ids:
                seen_ids.add(key)
                all_docs.append(d)

    logger.info(
        "Balanced multi-policy retrieval: %d policies, %d total docs (%d per policy target)",
        len(policy_names), len(all_docs), per_policy_k,
    )
    return all_docs


def get_latest_version_in_store(base_name: str) -> Optional[int]:
    try:
        # Normalize base_name using smart strategy matching
        base_name = _normalize_policy_name(base_name)
        
        if not base_name:
            return None
        
        client = _get_chroma_client()
        collection = client.get_or_create_collection(CHROMA_COLLECTION_NAME)
        results = collection.get(
            where={"base_name": base_name},
            include=["metadatas"],
            limit=1000,
        )
        if not results["metadatas"]:
            return None
        versions = [m["version"] for m in results["metadatas"] if "version" in m]
        return max(versions) if versions else None
    except Exception as exc:
        logger.error("Error querying ChromaDB for latest version: %s", exc)
        return None


def delete_policy_version(base_name: str, version: int) -> int:
    """Delete all chunks for one specific version of a policy. Returns count deleted."""
    base_name = _normalize_policy_name(base_name) or base_name
    client = _get_chroma_client()
    collection = client.get_or_create_collection(CHROMA_COLLECTION_NAME)
    results = collection.get(
        where={"$and": [{"base_name": base_name}, {"version": version}]},
        include=[],
    )
    ids = results.get("ids", [])
    if ids:
        collection.delete(ids=ids)
    logger.info("Deleted %d chunks for %s v%s", len(ids), base_name, version)
    return len(ids)


def delete_policy_all_versions(base_name: str) -> int:
    """Delete all chunks for every version of a policy. Returns count deleted."""
    base_name = _normalize_policy_name(base_name) or base_name
    client = _get_chroma_client()
    collection = client.get_or_create_collection(CHROMA_COLLECTION_NAME)
    results = collection.get(where={"base_name": base_name}, include=[])
    ids = results.get("ids", [])
    if ids:
        collection.delete(ids=ids)
    logger.info("Deleted %d chunks for %s (all versions)", len(ids), base_name)
    return len(ids)


def fetch_chunks_for_version(base_name: str, version: int) -> list[str]:
    try:
        # Normalize base_name using smart strategy matching
        base_name = _normalize_policy_name(base_name)
        
        if not base_name:
            return []
        
        client = _get_chroma_client()
        collection = client.get_or_create_collection(CHROMA_COLLECTION_NAME)
        results = collection.get(
            where={"$and": [{"base_name": base_name}, {"version": version}]},
            include=["documents"],
            limit=5000,
        )
        return results["documents"] or []
    except Exception:
        return []
