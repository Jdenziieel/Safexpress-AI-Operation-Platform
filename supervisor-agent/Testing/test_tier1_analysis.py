"""
Test Tier 1 Full Task Analysis LLM with configurable pre-processing.
Tests the task validation and clarification logic in isolation.
"""

import os
import json
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from config import OPENAI_API_KEY

# Load environment
load_dotenv()

# ============================================================================
# CONFIGURE YOUR TEST HERE
# ============================================================================

USER_MESSAGE = "find the latest email from joshdenziel.joves.cics@ust.edu.ph and forward it to jdenziieel@gmail.com with the exact content"

# Number of LLM responses to generate
N_RESPONSES = 3

# ============================================================================
# PRE-PROCESSED DATA CONFIGURATION
# ============================================================================

# 1. HISTORY TEXT (conversation context)
# Set to empty string for first message, or provide conversation history
HISTORY_TEXT = ""  # First message (no history)

# Example with history (uncomment to use):
# HISTORY_TEXT = """
# CONVERSATION SUMMARY:
# User asked to send an email to john@example.com about the meeting.
# Bot asked for the meeting details.
# 
# RECENT MESSAGES (last 3):
# User: "Send an email to john about the meeting"
# Assistant: "What should I say in the email about the meeting?"
# User: "Tell him it's at 3pm tomorrow"
# """

# 2. EXECUTION CONTEXT (post-execution modifications)
# Set to empty string if no previous execution
EXEC_CONTEXT = ""  # No previous execution

# Example with execution (uncomment to use):
# EXEC_CONTEXT = """
# EXECUTION CONTEXT:
# - Executed 1 task(s) | Last: 2024-11-09 14:30:00 | Status: success | Result: Email sent successfully
# - User may be modifying/redoing previous execution
# """

# 3. CAPABILITIES (filtered or full)
# Default: Gmail agent capabilities only
CAPABILITIES = """
**GMAIL_AGENT:**
  • search_emails(query, max_results, [label_ids])
  • get_thread_conversation(thread_id)
  • reply_to_email(message_id, reply_body)
  • forward_email(message_id, to, [forward_message])
  • create_draft_email(to, subject, body)
  • send_draft_email(draft_id)
  • search_drafts([query, max_results])
  • send_email(to, subject, body)
  • send_email_with_attachment(to, subject, body, file_path)
  • add_label(message_id, label)
  • remove_label(message_id, label)
  • download_attachment(message_id, attachment_id, save_path)
"""

# Alternative: Full capabilities (uncomment to use all agents)
# CAPABILITIES = """
# **GMAIL_AGENT:**
#   • search_emails(query, max_results, [label_ids])
#   • forward_email(message_id, to, [forward_message])
#   • create_draft_email(to, subject, body)
#   • send_email(to, subject, body)
# 
# **DOCS_AGENT:**
#   • create_doc(title)
#   • add_text(document_id, text)
#   • read_doc(document_id)
# 
# **CALENDAR_AGENT:**
#   • list_events([time_min, time_max, max_results])
#   • create_event(summary, start_time, [end_time, description])
# 
# **SHEETS_AGENT:**
#   • create_sheet(title)
#   • upload_mapped_data(sheet_id, transformed_data, [sheet_name])
# """

# ============================================================================

def test_tier1_analysis(
    user_message: str,
    history_text: str = "",
    exec_context: str = "",
    capabilities: str = "",
    n_responses: int = 1
) -> dict:
    """
    Test Tier 1 Full Task Analysis LLM with configurable pre-processing.
    
    Args:
        user_message: User's current message
        history_text: Conversation history context
        exec_context: Previous execution context
        capabilities: Available capabilities (filtered or full)
        n_responses: Number of different LLM responses to generate
    
    Returns:
        Dictionary with count and all responses
    """
    
    # Build system prompt (same as conversational_agent.py line 880)
    system_prompt = f"""Validate and clarify user requests before execution. Check feasibility against AVAILABLE CAPABILITIES, extract required fields, ask specific questions for missing info.

AVAILABLE CAPABILITIES:
{capabilities}

CONTEXT RULES:
- Post-execution: Conversation continues. Treat modification requests as NEW tasks
- Compound cancel ("cancel X and do Y"): Extract ONLY new task (Y), ignore old context, set intent based on new task

INTENT CLASSIFICATION:
- needs_clarification: Missing required fields
- not_feasible: No matching capability (explain why, suggest alternatives)
- too_complex: Multi-step/unclear (break down, suggest simpler approach)
- ready_to_execute: All fields present
- small_talk: Non-task conversation

JSON OUTPUT:
{{
    "intent": "needs_clarification|not_feasible|too_complex|ready_to_execute|small_talk",
    "task_type": "send_email|search_emails|reply_to_email|etc",
    "extracted_info": {{"recipient": "john@example.com", "subject": "Meeting"}},
    "missing_fields": ["recipient"],
    "clarification_question": "Who should I send this to?",
    "reasoning": "1 sentence explanation",
    "suggested_alternatives": ["Alternative 1", "Alternative 2"],
    "execution_ready": false,
    "execution_summary": "Send email to john@example.com about Meeting"
}}

CLARIFICATION QUESTIONS - Be specific:
✓ "Who would you like to send this email to?"
✓ "What should the subject line be?"
✗ "What are the details?" (too vague)
"""
    
    # Build user prompt (same as conversational_agent.py line 918)
    user_prompt = f"""{history_text}{exec_context}CURRENT USER MESSAGE: {user_message}"""
    
    # Initialize LLM (using gpt-4o as in conversational_agent)
    llm = ChatOpenAI(
        model="gpt-4o",
        temperature=0.2,
        openai_api_key=OPENAI_API_KEY
    )
    
    print(f"🧪 Testing Tier 1 Full Task Analysis")
    print(f"📝 User message: {user_message}")
    print(f"📊 History: {'Yes (' + str(len(history_text)) + ' chars)' if history_text else 'No (first message)'}")
    print(f"🔄 Exec context: {'Yes' if exec_context else 'No'}")
    print(f"🎲 Generating {n_responses} response(s)...")
    print(f"{'='*80}\n")
    
    if n_responses == 1:
        # Single response
        try:
            response = llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                config={"timeout": 320}
            )
            
            response_text = response.content.strip()
            
            # Remove markdown code blocks
            if response_text.startswith("```json"):
                response_text = response_text[7:-3].strip()
            elif response_text.startswith("```"):
                response_text = response_text[3:-3].strip()
            
            try:
                result = json.loads(response_text)
                all_results = [{
                    "response_number": 1,
                    "intent": result.get("intent"),
                    "task_type": result.get("task_type"),
                    "extracted_info": result.get("extracted_info", {}),
                    "missing_fields": result.get("missing_fields", []),
                    "clarification_question": result.get("clarification_question"),
                    "reasoning": result.get("reasoning"),
                    "execution_ready": result.get("execution_ready", False),
                    "execution_summary": result.get("execution_summary"),
                    "raw_response": response_text,
                    "success": True,
                    "error": None
                }]
            except json.JSONDecodeError as e:
                all_results = [{
                    "response_number": 1,
                    "raw_response": response_text,
                    "success": False,
                    "error": f"JSON parse error: {str(e)}"
                }]
        except Exception as e:
            all_results = [{
                "response_number": 1,
                "success": False,
                "error": f"LLM error: {str(e)}"
            }]
    else:
        # Multiple responses
        try:
            from langchain.schema import SystemMessage, HumanMessage
            
            llm_responses = llm.generate(
                [[
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt)
                ]],
                n=n_responses,
                timeout=320
            )
            
            all_results = []
            for i, generation in enumerate(llm_responses.generations[0], 1):
                response_text = generation.text.strip()
                
                # Remove markdown code blocks
                if response_text.startswith("```json"):
                    response_text = response_text[7:-3].strip()
                elif response_text.startswith("```"):
                    response_text = response_text[3:-3].strip()
                
                try:
                    result = json.loads(response_text)
                    all_results.append({
                        "response_number": i,
                        "intent": result.get("intent"),
                        "task_type": result.get("task_type"),
                        "extracted_info": result.get("extracted_info", {}),
                        "missing_fields": result.get("missing_fields", []),
                        "clarification_question": result.get("clarification_question"),
                        "reasoning": result.get("reasoning"),
                        "execution_ready": result.get("execution_ready", False),
                        "execution_summary": result.get("execution_summary"),
                        "raw_response": response_text,
                        "success": True,
                        "error": None
                    })
                except json.JSONDecodeError as e:
                    all_results.append({
                        "response_number": i,
                        "raw_response": response_text,
                        "success": False,
                        "error": f"JSON parse error: {str(e)}"
                    })
        except Exception as e:
            all_results = [{
                "response_number": 1,
                "success": False,
                "error": f"LLM error: {str(e)}"
            }]
    
    return {
        "count": len(all_results),
        "user_message": user_message,
        "config": {
            "has_history": bool(history_text),
            "has_exec_context": bool(exec_context),
            "capabilities_length": len(capabilities),
            "history_length": len(history_text),
            "exec_context_length": len(exec_context)
        },
        "responses": all_results,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt
    }


# ============================================================================
# RUN TEST
# ============================================================================

print("🧪 TESTING Tier 1 Full Task Analysis LLM")
print("="*80)
print(f"Message: {USER_MESSAGE}")
print(f"N Responses: {N_RESPONSES}")
print("="*80 + "\n")

# Run test
results = test_tier1_analysis(
    user_message=USER_MESSAGE,
    history_text=HISTORY_TEXT,
    exec_context=EXEC_CONTEXT,
    capabilities=CAPABILITIES,
    n_responses=N_RESPONSES
)

# Save to JSON file
output_file = "tier1_analysis_results.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=4)

print(f"\n✅ Results saved to '{output_file}'")
print("="*80)

# Display summary
print(f"\n📊 SUMMARY:")
print(f"   Total Responses: {results['count']}")
print(f"   Configuration:")
print(f"     - Has history: {results['config']['has_history']}")
print(f"     - Has exec context: {results['config']['has_exec_context']}")
print(f"     - Capabilities: {results['config']['capabilities_length']} chars")

# Count successful parses
successful = sum(1 for r in results['responses'] if r.get('success'))
failed = results['count'] - successful
print(f"   Successful: {successful}/{results['count']}")
if failed > 0:
    print(f"   ❌ Failed: {failed}")

# Show intent distribution
from collections import Counter
intents = [r.get('intent') for r in results['responses'] if r.get('success')]
intent_counts = Counter(intents)

print(f"\n🎯 INTENT DISTRIBUTION:")
for intent, count in intent_counts.most_common():
    percentage = (count / results['count']) * 100
    print(f"   {intent} → {count}x ({percentage:.1f}%)")

# Consistency check
if len(intent_counts) == 1:
    print(f"\n   ✅ 100% CONSISTENT - All responses have same intent")
elif len(intent_counts) > 1:
    print(f"\n   ⚠️ INCONSISTENT - Found {len(intent_counts)} different intents")

# Show individual responses
print(f"\n📋 INDIVIDUAL RESPONSES:")
for response in results['responses']:
    num = response.get('response_number', '?')
    if response.get('success'):
        intent = response.get('intent', 'unknown')
        ready = response.get('execution_ready', False)
        task = response.get('task_type', 'unknown')
        
        print(f"\n   Response {num}:")
        print(f"     Intent: {intent}")
        print(f"     Task Type: {task}")
        print(f"     Execution Ready: {ready}")
        
        if response.get('extracted_info'):
            print(f"     Extracted: {response['extracted_info']}")
        
        if response.get('missing_fields'):
            print(f"     Missing: {response['missing_fields']}")
        
        if response.get('clarification_question'):
            question = response['clarification_question']
            print(f"     Question: {question[:80]}..." if len(question) > 80 else f"     Question: {question}")
        
        if response.get('reasoning'):
            reasoning = response['reasoning']
            print(f"     Reasoning: {reasoning[:80]}..." if len(reasoning) > 80 else f"     Reasoning: {reasoning}")
    else:
        print(f"\n   Response {num}: ❌ {response.get('error', 'Unknown error')}")
        if response.get('raw_response'):
            print(f"     Raw: {response['raw_response'][:100]}...")

print("\n" + "="*80)
print(f"✅ Full output saved to '{output_file}'")
print("="*80)
print("\n💡 TIP: Edit HISTORY_TEXT, EXEC_CONTEXT, or CAPABILITIES to test different scenarios!")
print("   Current config:")
print(f"     - History: {'Enabled (' + str(results['config']['history_length']) + ' chars)' if results['config']['has_history'] else 'Disabled (first message)'}")
print(f"     - Exec Context: {'Enabled' if results['config']['has_exec_context'] else 'Disabled'}")
print(f"     - Capabilities: Gmail agent only ({results['config']['capabilities_length']} chars)")
