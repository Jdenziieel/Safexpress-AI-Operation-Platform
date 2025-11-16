"""
Test identify_relevant_agents function with multiple LLM responses.
Tests the agent classification logic in isolation.
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

USER_MESSAGE = "find the latest email from joshdenziel.joves.cics@ust.edu.ph and forward it to jdenziieel@gmail.com with the exact content. Check my schedule for 5-6pm and if I am available, schedule a meeting with the both of them and write it in documents and sheet file"  # 👈 Change this to test different messages

# Number of LLM responses to generate (1-10 recommended)
N_RESPONSES = 2  # 👈 Generate N different variations

# ============================================================================

def identify_relevant_agents_test(user_input: str, n_responses: int = 1, custom_prompt: str = None) -> dict:
    """
    Test version of identify_relevant_agents that supports:
    1. Multiple responses (n parameter)
    2. Custom system prompts for testing
    
    Args:
        user_input: User's message to classify
        n_responses: Number of different LLM responses to generate
        custom_prompt: Optional custom prompt template (use {user_input} as placeholder)
    
    Returns:
        Dictionary with count and all responses
    """
    
    # Default classifier prompt (from utils.py)
    default_prompt = """Based on this user request, which agents are needed? 

Available agents:
- gmail_agent, docs_agent, mapping_agent, sheets_agent, calendar_agent,drive_agent
User request: {user_input}

Return ONLY a JSON array of agent names needed with exact name.
"""
    
    # Use custom prompt if provided, otherwise use default
    if custom_prompt:
        classifier_prompt = custom_prompt.format(user_input=user_input)
    else:
        classifier_prompt = default_prompt.format(user_input=user_input)
    
    # Initialize LLM (using same model as utils.py)
    classifier_llm = ChatOpenAI(
        model="gpt-3.5-turbo",
        temperature=0,
        openai_api_key=OPENAI_API_KEY
    )
    
    print(f"🧪 Generating {n_responses} response(s)...")
    print(f"📝 User message: {user_input}")
    print(f"{'='*80}\n")
    
    if n_responses == 1:
        # Single response (normal mode)
        response = classifier_llm.invoke([{"role": "user", "content": classifier_prompt}])
        
        try:
            agent_list = json.loads(response.content.strip())
            all_results = [{
                "agents": agent_list,
                "raw_response": response.content.strip(),
                "success": True,
                "error": None
            }]
        except json.JSONDecodeError as e:
            all_results = [{
                "agents": [],
                "raw_response": response.content.strip(),
                "success": False,
                "error": str(e)
            }]
    else:
        # Multiple responses (test mode)
        llm_responses = classifier_llm.generate(
            [[HumanMessage(content=classifier_prompt)]],
            n=n_responses
        )
        
        all_results = []
        for i, generation in enumerate(llm_responses.generations[0], 1):
            response_text = generation.text.strip()
            
            try:
                agent_list = json.loads(response_text)
                all_results.append({
                    "response_number": i,
                    "agents": agent_list,
                    "raw_response": response_text,
                    "success": True,
                    "error": None
                })
            except json.JSONDecodeError as e:
                all_results.append({
                    "response_number": i,
                    "agents": [],
                    "raw_response": response_text,
                    "success": False,
                    "error": str(e)
                })
    
    return {
        "count": len(all_results),
        "user_message": user_input,
        "responses": all_results,
        "prompt_used": classifier_prompt
    }


# Run test
print("🧪 TESTING identify_relevant_agents")
print("="*80)
print(f"Message: {USER_MESSAGE}")
print(f"Generating: {N_RESPONSES} different responses")
print("="*80 + "\n")

# Test with default prompt
results = identify_relevant_agents_test(USER_MESSAGE, N_RESPONSES)

# Save to JSON file
output_file = "identify_agents_results.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=4)

print(f"\n✅ Results saved to '{output_file}'")
print("="*80)

# Display summary
print(f"\n📊 SUMMARY:")
print(f"   Total responses: {results['count']}")

# Count successful parses
successful = sum(1 for r in results['responses'] if r['success'])
print(f"   Successful: {successful}/{results['count']}")

# Show unique agent combinations
from collections import Counter
agent_combos = [tuple(sorted(r['agents'])) for r in results['responses'] if r['success']]
combo_counts = Counter(agent_combos)

print(f"\n🎯 AGENT COMBINATIONS:")
for combo, count in combo_counts.most_common():
    percentage = (count / results['count']) * 100
    print(f"   {list(combo)} → {count}x ({percentage:.1f}%)")

# Show individual responses
print(f"\n📋 INDIVIDUAL RESPONSES:")
for i, response in enumerate(results['responses'], 1):
    if response['success']:
        print(f"   Response {i}: {response['agents']}")
    else:
        print(f"   Response {i}: ❌ Parse error - {response['error']}")
        print(f"      Raw: {response['raw_response'][:100]}...")

print("\n" + "="*80)
print(f"✅ Check '{output_file}' for full JSON output including prompt used")
print("="*80)
