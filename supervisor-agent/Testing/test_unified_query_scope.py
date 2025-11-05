"""
Test unified quick check with query_scope classification
"""

import os
from conversational_agent import ConversationalAgent, ConversationState

# Initialize agent
agent = ConversationalAgent(
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    model="gpt-4o-mini"
)

print("="*60)
print("Testing Unified Quick Check with Query Scope Classification")
print("="*60)

# Test 1: General capabilities question
print("\n📋 Test 1: General capabilities question")
print("User: 'What can you do?'")
state = ConversationState()
analysis = agent.analyze_request("What can you do?", state)
print(f"Intent: {analysis.intent}")
print(f"Task Type: {analysis.task_type}")
print(f"Should show ALL capabilities in Tier 1")

# Test 2: Specific task request
print("\n📋 Test 2: Specific task request")
print("User: 'Send email to john@example.com'")
state = ConversationState()
analysis = agent.analyze_request("Send email to john@example.com", state)
print(f"Intent: {analysis.intent}")
print(f"Task Type: {analysis.task_type}")
print(f"Should filter to relevant agents")

# Test 3: Confirmation (should be caught by Tier 0.5)
print("\n📋 Test 3: Confirmation")
print("User: 'yes'")
state = ConversationState(
    ready_for_execution=True,
    extracted_info={"task_type": "send_email", "recipient": "john@example.com"},
    execution_summary="Send email to john@example.com"
)
analysis = agent.analyze_request("yes", state)
print(f"Intent: {analysis.intent}")
print(f"Execution Ready: {analysis.execution_ready}")

# Test 4: Show me features (general)
print("\n📋 Test 4: Show me features")
print("User: 'Show me all features'")
state = ConversationState()
analysis = agent.analyze_request("Show me all features", state)
print(f"Intent: {analysis.intent}")
print(f"Task Type: {analysis.task_type}")

print("\n" + "="*60)
print("✅ All tests completed!")
print("="*60)
