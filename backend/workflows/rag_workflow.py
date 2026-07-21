"""
LangGraph RAG Workflow
======================
Compatibility notes:
- langgraph 1.x: StateGraph API unchanged, START/END still importable from langgraph.graph
- langchain-groq 1.x: ChatGroq constructor uses api_key= not groq_api_key=
- langchain-core 1.x: HumanMessage/AIMessage/SystemMessage unchanged
- Unused imports (ChatPromptTemplate, MessagesPlaceholder, operator) removed
"""
from __future__ import annotations

import logging
from typing import Optional, TypedDict

from core.config import get_settings
from core.constants import GROQ_MODEL, TOP_K_RETRIEVAL
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)


# ─── Error Handling Utilities ─────────────────────────────────────────────────

def get_user_friendly_error_message(exc: Exception) -> str:
    """
    Parse exception and return a user-friendly error message.
    Handles API rate limits, timeouts, and other common errors gracefully.
    """
    error_str = str(exc).lower()
    
    # Rate limit errors (429)
    if "429" in str(exc) or "rate_limit" in error_str or "rate limit" in error_str:
        if "tokens per day" in error_str or "tpd" in error_str:
            return (
                "⏳ I've hit the daily token limit for the AI service. "
                "Please try again in a few minutes, or contact your administrator. "
                "The system will be ready to assist you shortly!"
            )
        else:
            return (
                "⏳ The AI service is temporarily busy due to high requests. "
                "Please try again in a moment."
            )
    
    # Timeout errors
    if "timeout" in error_str:
        return (
            "⏱️ The AI service is taking too long to respond. "
            "Please try again in a moment."
        )
    
    # Authentication/API key errors
    if "api" in error_str and ("key" in error_str or "auth" in error_str or "unauthorized" in error_str):
        return (
            "🔑 There's a configuration issue with the AI service. "
            "Please contact your administrator."
        )
    
    # Connection errors
    if "connection" in error_str or "network" in error_str:
        return (
            "🌐 There's a network issue connecting to the AI service. "
            "Please check your connection and try again."
        )
    
    # Default fallback
    return (
        "❌ I encountered an error processing your request. "
        "Please try again or rephrase your question."
    )




# ─── State Schema ─────────────────────────────────────────────────────────────

class RAGState(TypedDict):
    user_query: str
    session_id: str
    chat_history: list

    query_type: str
    target_policy: Optional[str]

    retrieved_docs: list
    diff_summary: Optional[str]

    answer: str
    sources: list

    error: Optional[str]


# ─── LLM Factory ─────────────────────────────────────────────────────────────

def _get_llm(temperature: float = 0.1) -> ChatGroq:
    settings = get_settings()
    return ChatGroq(
        model=GROQ_MODEL,
        api_key=settings.groq_api_key,       # langchain-groq 1.x uses api_key=
        temperature=temperature,
        max_tokens=1500,
    )


# ─── Node: classify_query ─────────────────────────────────────────────────────

CLASSIFY_SYSTEM = """You are a query classifier for an HR policy chatbot.
Given a user query, output EXACTLY one JSON object (no other text):
{{
  "query_type": "<general_rag|policy_change|greeting|conversation_history>",
  "target_policy": "<snake_case_policy_base_name or null>"
}}

Rules:
- "policy_change": user asks about changes, differences, updates, new version, what changed
- "general_rag": user asks about policy content, rules, entitlements, procedures
- "greeting": hello, hi, thanks, how are you, small talk
- "conversation_history": user asks about conversation history, what we discussed, show history, summarize our chat, previous messages
- target_policy: best guess at the policy name in snake_case (e.g. "leave_policy") or null

Available policies: {policy_names}
"""


def classify_query_node(state: RAGState) -> dict:
    import json

    from services.vector_store import get_all_policy_names

    llm = _get_llm(temperature=0.0)
    policy_names = get_all_policy_names()
    prompt = CLASSIFY_SYSTEM.format(policy_names=", ".join(policy_names) or "none yet")

    try:
        response = llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=state["user_query"]),
        ])
        raw = response.content.strip()
        # Strip markdown fences if present
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())
        query_type   = parsed.get("query_type", "general_rag")
        target_policy = parsed.get("target_policy")
    except Exception as exc:
        logger.warning("classify_query failed (%s), defaulting to general_rag", exc)
        query_type    = "general_rag"
        target_policy = None

    return {"query_type": query_type, "target_policy": target_policy}


# ─── Node: retrieve ───────────────────────────────────────────────────────────

def retrieve_node(state: RAGState) -> dict:
    query  = state["user_query"]
    target = state.get("target_policy")

    logger.info(f"[RETRIEVE] Query: '{query}', Target: {target}")

    try:
        from services.vector_store import get_documents_for_query
        logger.info(f"[RETRIEVE] Calling get_documents_for_query(base_name={target}, top_k={TOP_K_RETRIEVAL})")
        docs = get_documents_for_query(query, base_name=target, top_k=TOP_K_RETRIEVAL)
        logger.info(f"[RETRIEVE] Retrieved {len(docs)} documents")

        # Log first doc if available
        if docs:
            logger.info(f"[RETRIEVE] First doc metadata: {docs[0].metadata}")
            logger.info(f"[RETRIEVE] First doc content (first 100 chars): {docs[0].page_content[:100]}")
        else:
            logger.warning(f"[RETRIEVE] NO DOCUMENTS FOUND!")

    except Exception as exc:
        logger.error(f"[RETRIEVE] Exception: {exc}", exc_info=True)
        docs = []

    sources = [
        {
            "source":      doc.metadata.get("source", ""),
            "policy_name": doc.metadata.get("policy_name", ""),
            "version":     doc.metadata.get("version"),
            "page_number": doc.metadata.get("page_number"),
            "has_table":   doc.metadata.get("has_table", False),
        }
        for doc in docs
    ]
    
    logger.info(f"[RETRIEVE] Returning {len(docs)} docs, {len(sources)} sources")
    
    return {"retrieved_docs": docs, "sources": sources}


# ─── Node: check_diff ────────────────────────────────────────────────────────

def check_diff_node(state: RAGState) -> dict:
    from db.models import PolicyDiff, _SessionLocal

    diff_summary  = None
    target        = state.get("target_policy")
    new_target    = target

    try:
        if _SessionLocal:
            db = _SessionLocal()
            try:
                q = db.query(PolicyDiff).order_by(PolicyDiff.created_at.desc())
                if target:
                    q = q.filter(PolicyDiff.base_name == target)
                diff = q.first()
                if diff:
                    diff_summary = diff.diff_summary
                    new_target   = diff.base_name
            finally:
                db.close()
    except Exception as exc:
        logger.error("check_diff_node error: %s", exc)

    # Also pull supporting chunks
    retrieval = retrieve_node({**state, "target_policy": new_target})
    return {
        **retrieval,
        "diff_summary":  diff_summary,
        "target_policy": new_target,
    }


# ─── Node: generate ──────────────────────────────────────────────────────────

HR_SYSTEM_PROMPT = """You are HRBot, a knowledgeable and friendly HR policy assistant.
Answer questions about company HR policies accurately and concisely.

CRITICAL RULES - DO NOT VIOLATE:
1. **Only answer based on provided context** - Do NOT make up or assume policy details
2. If context is unavailable or insufficient, respond: "I don't have information about that in the current policies. Please contact HR for clarification."
3. Never claim knowledge of policies not in the context
4. For policy change questions, ONLY use the diff summary provided
5. ALWAYS cite the exact policy name and version you're referencing
6. When uncertain, ask for clarification rather than guessing
7. If no relevant context found, explicitly state: "This information is not available in the current policy documents."

FORMATTING - choose the structure that fits the content, don't default to a single paragraph:
- **Numbered lists** for anything sequential/procedural (steps to do something, a process, "how do I...")
- **Bullet points** for a set of facts, options, or items that don't have to happen in order
  (eligibility criteria, list of contacts, list of documents needed, list of benefits)
- **Tables** (Markdown pipe tables) when comparing multiple items across the same attributes
  (e.g. different scenarios, different policy versions, different plans/tiers, contact directories
  with name/role/number columns) — a table beats a paragraph whenever there are 2+ rows and 2+
  columns worth of structured data
- **Short paragraphs** only for a single, simple fact or a brief explanation with no sub-parts
- **Bold** key terms, numbers, dates, and deadlines so they're scannable, not buried in prose
- If an answer naturally has multiple parts (e.g. "how to do X" touching several sub-topics), use
  a heading or bold lead-in per part, each followed by its own list or table — never merge multiple
  distinct sub-answers into one long paragraph
- Keep each bullet/row short - one idea per line, not a mini-paragraph inside a bullet
- Be empathetic and professional
"""

GENERAL_RAG_TEMPLATE = """Answer the user's question using the HR policy context below.

CONTEXT FROM POLICIES:
{context}

Answer using the most appropriate structure (numbered steps, bullets, or a table - see formatting
rules) rather than a single dense paragraph, unless the answer is genuinely a single simple fact.
Cite the policy name and version where relevant."""

DIFF_TEMPLATE = """The user is asking about changes in an HR policy.

POLICY CHANGE SUMMARY:
{diff_summary}

ADDITIONAL CONTEXT (from current policy documents):
{context}

Provide a clear, structured explanation of what changed. If there are 2+ distinct changes, prefer
a Markdown table with columns like Section | Old | New | Impact over a bulleted wall of text -
tables make version-to-version comparisons much easier to scan. Use bullet points only when a
table doesn't fit (e.g. a single narrative change)."""


def _format_docs(docs: list) -> str:
    if not docs:
        return "No relevant policy sections found."
    parts = []
    for doc in docs:
        meta = doc.metadata
        parts.append(
            f"[{meta.get('policy_name', 'Policy')} v{meta.get('version', '?')} "
            f"| Page {meta.get('page_number', '?')}]\n{doc.page_content}"
        )
    return "\n\n---\n\n".join(parts)


HISTORY_SUMMARY_TEMPLATE = """Based on our conversation history below, answer the user's question about our discussion.

User's question: {query}

CONVERSATION HISTORY:
{history}

Provide a clear, helpful response about what we've discussed. If the question doesn't match the conversation, let them know what topics we have covered."""


def generate_history_node(state: RAGState) -> dict:
    """Generate response to conversation history questions."""
    chat_history = state.get("chat_history", [])
    
    if not chat_history:
        return {
            "answer": (
                "This is the beginning of our conversation. We haven't discussed any policies yet. "
                "What would you like to know about our HR policies?"
            )
        }
    
    # Build conversation summary from history
    llm = _get_llm(temperature=0.1)
    
    history_text = ""
    for msg in chat_history:
        if isinstance(msg, HumanMessage):
            history_text += f"USER: {msg.content}\n"
        elif isinstance(msg, AIMessage):
            history_text += f"ASSISTANT: {msg.content}\n"
        elif isinstance(msg, SystemMessage):
            continue
    
    if not history_text.strip():
        return {
            "answer": (
                "This is the beginning of our conversation. We haven't discussed any topics yet. "
                "What would you like to know?"
            )
        }
    
    prompt = HISTORY_SUMMARY_TEMPLATE.format(
        query=state["user_query"],
        history=history_text,
    )
    
    try:
        response = llm.invoke([SystemMessage(content=prompt)])
        answer = response.content.strip()
    except Exception as exc:
        logger.error("History generation error: %s", exc)
        answer = get_user_friendly_error_message(exc)
    
    return {"answer": answer}


def generate_node(state: RAGState) -> dict:
    llm          = _get_llm(temperature=0.1)  # Lower temperature for better grounding
    query_type   = state.get("query_type", "general_rag")
    docs         = state.get("retrieved_docs", [])
    context      = _format_docs(docs)
    chat_history = state.get("chat_history", [])

    if query_type == "greeting":
        return {
            "answer": (
                "Hello! 👋 I'm HRBot, your HR policy assistant. "
                "I can help you with questions about leave policies, working hours, health benefits, "
                "office guidelines, and other HR policies. What would you like to know?"
            )
        }

    if query_type == "policy_change" and state.get("diff_summary"):
        user_content = DIFF_TEMPLATE.format(
            diff_summary=state["diff_summary"],
            context=context,
        )
    else:
        user_content = GENERAL_RAG_TEMPLATE.format(context=context)

    messages = [SystemMessage(content=HR_SYSTEM_PROMPT)]
    messages.extend(chat_history)
    messages.append(
        HumanMessage(content=f"User question: {state['user_query']}\n\n{user_content}")
    )

    try:
        response = llm.invoke(messages)
        answer   = response.content.strip()
    except Exception as exc:
        logger.error("Generation error: %s", exc)
        answer = get_user_friendly_error_message(exc)

    return {"answer": answer}


# ─── Routing ─────────────────────────────────────────────────────────────────

def route_after_classify(state: RAGState) -> str:
    query_type = state.get("query_type")
    if query_type == "conversation_history":
        return "history"
    elif query_type == "greeting":
        return "generate"
    elif query_type == "policy_change":
        return "check_diff"
    else:
        return "retrieve"


# ─── Build Graph ──────────────────────────────────────────────────────────────

def build_rag_graph():
    graph = StateGraph(RAGState)

    graph.add_node("classify_query", classify_query_node)
    graph.add_node("retrieve",       retrieve_node)
    graph.add_node("check_diff",     check_diff_node)
    graph.add_node("generate",       generate_node)
    graph.add_node("history",        generate_history_node)

    graph.add_edge(START, "classify_query")
    graph.add_conditional_edges(
        "classify_query",
        route_after_classify,
        {
            "retrieve": "retrieve",
            "check_diff": "check_diff",
            "generate": "generate",
            "history": "history",
        },
    )
    graph.add_edge("retrieve",   "generate")
    graph.add_edge("check_diff", "generate")
    graph.add_edge("generate",   END)
    graph.add_edge("history",    END)

    return graph.compile()


_rag_graph = None


def get_rag_graph():
    global _rag_graph
    if _rag_graph is None:
        _rag_graph = build_rag_graph()
    return _rag_graph


def run_rag(user_query: str, session_id: str, chat_history: list) -> dict:
    graph = get_rag_graph()
    initial_state: RAGState = {
        "user_query":    user_query,
        "session_id":    session_id,
        "chat_history":  chat_history,
        "query_type":    "",
        "target_policy": None,
        "retrieved_docs": [],
        "diff_summary":  None,
        "answer":        "",
        "sources":       [],
        "error":         None,
    }
    result = graph.invoke(initial_state)
    return {
        "answer":     result["answer"],
        "sources":    result.get("sources", []),
        "query_type": result.get("query_type"),
    }