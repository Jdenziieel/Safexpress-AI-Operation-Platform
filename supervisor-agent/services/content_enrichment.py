"""
Content Enrichment Service

Handles two responsibilities:
1. Deterministic file content extraction (PDF, plain text)
2. LLM-based content generation/transformation (subjects, summaries, grammar fixes)

Sits between Tier 0.5 and Tier 1 in the analysis pipeline.
Only invoked when Tier 0.5 detects enrichment needs.
"""

import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from langchain_openai import ChatOpenAI
from execution_logger import trace
from logging_config import memory_logger as logger

# Type A tasks produce short inline content
INLINE_TASKS = {"generate_subject", "generate_title", "generate_summary", "fix_grammar", "formalize_text"}
# Type B tasks store file content as a context variable for orchestrator resolution
PASSTHROUGH_TASKS = {"use_file_content"}


@dataclass
class EnrichmentResult:
    """Result of the enrichment phase."""
    enriched_message: str
    context_variables: Dict[str, str] = field(default_factory=dict)


def extract_file_context(uploaded_file: Dict[str, Any], max_chars: int = 3000) -> Optional[str]:
    """
    Deterministic file parsing. No LLM involved.

    Supports:
    - PDF via pdfplumber (first max_chars characters)
    - Plain text / HTML (direct read, first max_chars characters)
    - CSV/Excel: NOT parsed here (stays in mapping_agent pipeline)

    Returns truncated text or None if unsupported/unreadable.
    """
    mime = uploaded_file.get("mime_type", "")
    file_path = uploaded_file.get("temp_path")

    if not file_path or not os.path.exists(file_path):
        trace.warning("Enrichment: file not found for extraction", {"path": file_path})
        return None

    try:
        if "pdf" in mime:
            return _extract_pdf(file_path, max_chars)
        elif mime.startswith("text/") or mime in ("application/json",):
            return _extract_text(file_path, max_chars)
        else:
            trace.info(f"Enrichment: unsupported mime type for extraction", {"mime": mime})
            return None
    except Exception as e:
        trace.warning("Enrichment: file extraction failed", {"error": str(e), "mime": mime})
        return None


def _extract_pdf(file_path: str, max_chars: int) -> Optional[str]:
    """Extract text from PDF using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        trace.warning("Enrichment: pdfplumber not installed, cannot extract PDF")
        return None

    text_parts = []
    total_chars = 0
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            total_chars += len(page_text)
            if total_chars >= max_chars:
                break

    full_text = "\n".join(text_parts)
    return full_text[:max_chars] if full_text.strip() else None


def _extract_text(file_path: str, max_chars: int) -> Optional[str]:
    """Extract text from plain text or HTML files."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read(max_chars)
    return content if content.strip() else None


def enrich_message(
    user_message: str,
    enrichment_tasks: List[str],
    file_context: Optional[str] = None,
    openai_api_key: Optional[str] = None,
) -> EnrichmentResult:
    """
    Single LLM call to generate/transform content.

    For inline tasks (Type A): generates short content, inlines it in the enriched message.
    For passthrough tasks (Type B): stores file content as a context variable,
    tells Tier 1 to use {{ extracted_file_text }} variable reference.

    No conversation history. No entity memory. Only current message + file context.

    Returns EnrichmentResult with enriched_message and optional context_variables.
    """
    task_set = set(enrichment_tasks)
    context_variables = {}

    # Type B: passthrough — store file content as variable, don't send to LLM
    has_passthrough = bool(task_set & PASSTHROUGH_TASKS)
    if has_passthrough and file_context:
        context_variables["extracted_file_text"] = file_context
        # Remove passthrough tasks; only inline tasks go to LLM
        task_set -= PASSTHROUGH_TASKS

    # If only passthrough tasks (no inline tasks), return early with variable reference
    if not task_set:
        enriched = user_message + '\n[File content stored as {{ extracted_file_text }} for use in task parameters]'
        trace.step("enrichment", "passthrough only — file content stored as context variable", {
            "content_length": len(file_context) if file_context else 0,
        })
        return EnrichmentResult(enriched_message=enriched, context_variables=context_variables)

    # Type A: inline tasks — call LLM to generate short content
    api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.4, openai_api_key=api_key)

    file_section = ""
    if file_context:
        file_section = f"\n\nFILE CONTENT (truncated):\n{file_context}"

    system_prompt = """You are a content enrichment assistant. The user has a task request but needs help generating or transforming specific content.

RULES:
- Only generate content that was EXPLICITLY requested in the enrichment tasks.
- Do NOT infer recipients, dates, email addresses, or any factual information not present in the message or file.
- If the user's message does not provide enough information for a field, leave it as-is.
- Keep generated content concise and relevant.
- For grammar fixes: correct only grammar/spelling, preserve meaning.
- For subject generation: create a clear, concise subject line (max 10 words).
- For summary generation: produce a concise summary (max 200 words).

OUTPUT:
Return the user's original message rewritten with the generated content inserted inline.
For example:
  Original: "send email to john, create a subject about the quarterly report"
  Enriched: "send email to john with subject 'Quarterly Report Summary and Key Findings'"

Return ONLY the enriched message text, nothing else."""

    user_prompt = f"""Enrichment tasks: {list(task_set)}

Original message: "{user_message}"{file_section}"""

    try:
        start_time = time.time()
        llm_response = llm.invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            config={"timeout": 30, "max_tokens": 500}
        )
        duration_ms = (time.time() - start_time) * 1000

        enriched_text = llm_response.content.strip()

        # Token tracking
        input_tokens = 0
        output_tokens = 0
        if hasattr(llm_response, 'response_metadata'):
            token_usage = llm_response.response_metadata.get('token_usage', {})
            input_tokens = token_usage.get('prompt_tokens', 0)
            output_tokens = token_usage.get('completion_tokens', 0)

        logger.llm_call(
            model="gpt-4o-mini",
            operation="content_enrichment",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            tier="enrichment",
            prompt_summary=f"Enriching: {', '.join(task_set)}",
            success=True,
        )

        trace.step("enrichment", "LLM enrichment complete", {
            "tasks": list(task_set),
            "original_len": len(user_message),
            "enriched_len": len(enriched_text),
            "duration_ms": round(duration_ms, 2),
            "has_passthrough_vars": bool(context_variables),
        })

        return EnrichmentResult(enriched_message=enriched_text, context_variables=context_variables)

    except Exception as e:
        trace.warning("Enrichment: LLM call failed, returning original message", {"error": str(e)})
        return EnrichmentResult(enriched_message=user_message, context_variables=context_variables)
