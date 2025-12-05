# Token Optimization Strategy for Summarize Execution

## Current Token Consumption Analysis

### Where Tokens Are Consumed in `summarize_execution`

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        TOKEN BREAKDOWN (Typical Call)                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   System Prompt:    ~200 tokens (fixed)                                     │
│   User Prompt:      ~100 tokens (variable: original_request + status)       │
│   Context Data:     500-5000 tokens (BIGGEST CULPRIT!)                      │
│   ─────────────────────────────────────────────────────────────────────     │
│   Total Input:      800-5300 tokens per call                                │
│   Output:           100-300 tokens (summary)                                │
│                                                                             │
│   COST PER CALL:    ~$0.01-0.08 (gpt-4o pricing)                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### What Goes Into Context Data

The `final_context` from orchestrator can include:
```python
{
    "emails": [                    # Array of email objects
        {
            "subject": "...",
            "from": "...",
            "body": "Full body...",  # Can be 1000s of chars!
            "date": "...",
            "attachments": [...]
        },
        # ... potentially 5+ emails
    ],
    "documents": [...],            # Similar structure
    "events": [...],
    "results": [...],              # Step-by-step results
    "variables": {...},            # All extracted variables
}
```

### Current Filtering (What We're Already Doing)

✅ `_filter_context_for_user()` removes:
- Technical IDs (message_id, thread_id, etc.)
- Timestamps (created_at, internal_date)
- Full HTML body (body_html)
- Query echoes (user knows what they asked)

✅ `_build_readable_context()`:
- Limits item display to first 5 items
- Truncates strings to 150 chars

✅ Error Handling (no LLM):
- Errors skip LLM entirely (0 tokens)
- No-results skip LLM entirely (0 tokens)

---

## 🚀 Optimization Strategies

### Strategy 1: Progressive Summarization (Recommended)

**Problem:** We send ALL email content to LLM, even when user only needs "who/what/when"

**Solution:** Extract key facts BEFORE sending to LLM

```python
def _extract_key_facts(self, context: Dict) -> Dict:
    """Extract only essential facts for summarization."""
    facts = {}
    
    if "emails" in context:
        emails = context["emails"]
        facts["email_summary"] = {
            "count": len(emails),
            "senders": [e.get("from", "Unknown")[:50] for e in emails[:3]],
            "subjects": [e.get("subject", "No subject")[:60] for e in emails[:3]],
            "dates": [e.get("date", "Unknown") for e in emails[:3]],
            # NO body content - just metadata
        }
    
    # Similar for documents, events, etc.
    return facts
```

**Token Savings:** 60-80% (from 3000 → 500 tokens)

---

### Strategy 2: Tiered Model Selection

**Current:** Always uses `gpt-4o` (~$0.005/1K input)

**Proposed:** Use cheaper models for simple summaries

```python
def _select_model_for_summary(self, context: Dict, execution_status: str) -> str:
    """Select appropriate model based on complexity."""
    
    # Simple cases: use gpt-3.5-turbo ($0.0005/1K - 10x cheaper)
    simple_cases = [
        len(context.get("emails", [])) <= 2,  # Few items
        "created" in execution_status,         # Create operations
        "sent" in execution_status,            # Send operations
        len(json.dumps(context)) < 500,        # Small context
    ]
    
    if any(simple_cases):
        return "gpt-3.5-turbo"  # 10x cheaper
    
    return "gpt-4o"  # Complex analysis
```

**Cost Savings:** 60-80% for simple operations

---

### Strategy 3: Template-Based Summary for Common Patterns

**Problem:** LLM generates same structure every time

**Solution:** Use templates for predictable outcomes

```python
SUMMARY_TEMPLATES = {
    "email_search": """✅ Found {count} email(s) matching your search.

📧 **Top Results:**
{email_list}

{suggestion}""",

    "email_sent": """✅ Email sent successfully!

**To:** {recipients}
**Subject:** {subject}
**Sent at:** {timestamp}""",

    "document_created": """✅ Document created successfully!

📄 **Title:** {title}
**Location:** {location}
**Link:** [Open Document]({url})""",
}

def _try_template_summary(self, context: Dict, operation: str) -> Optional[str]:
    """Try to use template before falling back to LLM."""
    
    if operation == "search_emails" and "emails" in context:
        emails = context["emails"]
        email_list = "\n".join([
            f"  • **{e['subject'][:50]}** from {e['from'][:30]}"
            for e in emails[:5]
        ])
        return SUMMARY_TEMPLATES["email_search"].format(
            count=len(emails),
            email_list=email_list,
            suggestion="Reply to narrow your search." if len(emails) > 5 else ""
        )
    
    return None  # Fall back to LLM
```

**Token Savings:** 100% for templated cases

---

### Strategy 4: Context Window Budgeting

**Problem:** No limit on context size sent to LLM

**Solution:** Set hard budget and prioritize content

```python
MAX_CONTEXT_TOKENS = 1000  # Budget for context

def _budget_context(self, context: Dict, max_tokens: int = MAX_CONTEXT_TOKENS) -> str:
    """Fit context within token budget, prioritizing important data."""
    
    # Priority order for what to include
    priority_fields = [
        "subject", "from", "title", "count", "created",  # High priority
        "date", "to", "filename",                         # Medium priority
        "body_links", "attachments",                      # Lower priority
    ]
    
    context_text = ""
    current_tokens = 0
    
    for field in priority_fields:
        if field in context:
            field_text = f"{field}: {context[field]}\n"
            field_tokens = len(field_text) // 4
            
            if current_tokens + field_tokens > max_tokens:
                context_text += f"... (truncated to fit budget)"
                break
            
            context_text += field_text
            current_tokens += field_tokens
    
    return context_text
```

**Token Savings:** Predictable, capped usage

---

### Strategy 5: Caching Similar Summaries

**Problem:** Same email searched multiple times = multiple LLM calls

**Solution:** Hash-based caching

```python
import hashlib
from functools import lru_cache

# In-memory cache (or Redis for production)
SUMMARY_CACHE = {}

def _get_cache_key(self, context: Dict, request: str) -> str:
    """Generate cache key from context + request."""
    # Use hash of meaningful content (ignoring timestamps)
    content = json.dumps({
        "request": request[:100],
        "count": len(context.get("emails", [])),
        "subjects": [e.get("subject", "")[:50] for e in context.get("emails", [])[:3]]
    }, sort_keys=True)
    return hashlib.md5(content.encode()).hexdigest()

def summarize_execution_with_cache(self, ...):
    cache_key = self._get_cache_key(user_relevant_context, original_request)
    
    if cache_key in SUMMARY_CACHE:
        print(f"📦 Cache hit! Saved ~{estimated_tokens} tokens")
        return SUMMARY_CACHE[cache_key]
    
    # Generate and cache
    summary = self._generate_llm_summary(...)
    SUMMARY_CACHE[cache_key] = summary
    return summary
```

**Token Savings:** 100% for repeated queries

---

## 📊 Implementation Priority

| Strategy | Token Savings | Effort | Recommend |
|----------|--------------|--------|-----------|
| 1. Progressive Summarization | 60-80% | Medium | ⭐⭐⭐ YES |
| 2. Tiered Model Selection | 60-80% cost | Low | ⭐⭐⭐ YES |
| 3. Template-Based Summary | 100% some | Medium | ⭐⭐ YES |
| 4. Context Budgeting | Predictable | Low | ⭐⭐ YES |
| 5. Caching | 100% repeat | Medium | ⭐ Maybe |

---

## 🔧 Quick Wins (Implement Now)

### Quick Win 1: Stricter Email Body Handling

```python
# In _filter_context_for_user, add:
if key == "body" and isinstance(value, str):
    # Only keep first 100 chars of body for summary
    filtered[key] = value[:100] + "..." if len(value) > 100 else value
    continue
```

### Quick Win 2: Skip LLM for Single-Item Success

```python
# In summarize_execution, add before LLM call:
if len(results) == 1 and results[0].get("status") == "success":
    tool = results[0].get("tool", "operation")
    return f"✅ Successfully completed: {original_request}\n\n{self._format_single_result(results[0])}"
```

### Quick Win 3: Use GPT-3.5 for Simple Operations

```python
# In summarize_execution, before LLM call:
simple_ops = ["create_draft", "send_email", "create_event", "create_document"]
operation = conversation_state.extracted_info.get("action", "")

model_to_use = "gpt-3.5-turbo" if operation in simple_ops else "gpt-4o"
llm = ChatOpenAI(model=model_to_use, temperature=0.3)
```

---

## 📈 Expected Savings

| Scenario | Current Tokens | After Optimization | Savings |
|----------|---------------|-------------------|---------|
| Email Search (5 emails) | 3,500 | 800 | 77% |
| Send Email | 1,200 | 0 (template) | 100% |
| Create Doc | 1,000 | 0 (template) | 100% |
| Error Case | 0 | 0 | Already 0 |
| Complex Multi-Step | 5,000 | 2,000 | 60% |

**Estimated Monthly Savings:** 60-80% token reduction

---

## Implementation Order

1. **Day 1:** Add stricter body truncation (Quick Win 1)
2. **Day 2:** Add single-result template path (Quick Win 2)
3. **Day 3:** Implement tiered model selection (Strategy 2)
4. **Week 2:** Progressive summarization (Strategy 1)
5. **Week 3:** Template-based summaries (Strategy 3)
6. **Future:** Caching (if needed)

---

## Code Reference

Current implementation location:
- `conversational_agent.py` lines 1664-1820: `summarize_execution`
- `conversational_agent.py` lines 1556-1663: `_filter_context_for_user`
- `conversational_agent.py` lines 1822-1880: `_build_readable_context`
