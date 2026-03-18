"""
Quick single-message test for Unified LLM.
Modify the USER_MESSAGE variable and run to test.
"""

import os
from dotenv import load_dotenv
from conversational_agent import ConversationalAgent
from models import ConversationState

# Load environment
load_dotenv()

# ============================================================================
# CONFIGURE YOUR TEST HERE
# ============================================================================

USER_MESSAGE = "find the latest email from joshdenziel.joves.cics@ust.edu.ph and forward it to jdenziieel@gmail.com with the exact content"  # 👈 Change this to test different messages

# Number of LLM responses to generate (1-10 recommended, higher = more expensive)
N_RESPONSES = 1  # 👈 Change this to generate more/fewer variations

# Simulate conversation state (optional - uncomment to test with context)
CONVERSATION_STATE = ConversationState()

# Uncomment to simulate awaiting confirmation:
# CONVERSATION_STATE.extracted_info = {"task_type": "send_email", "recipient": "john@example.com"}
# CONVERSATION_STATE.ready_for_execution = True

# Uncomment to simulate awaiting clarification:
# CONVERSATION_STATE.extracted_info = {"task_type": "send_email"}
# CONVERSATION_STATE.missing_fields = ["recipient"]
# CONVERSATION_STATE.clarification_question = "Who should I send this to?"

# ============================================================================

# Initialize agent in TEST MODE
agent = ConversationalAgent(
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    test_mode=True,  # 🧪 Only runs Unified LLM, saves JSON
    test_n_responses=N_RESPONSES  # 🎲 Generate N different responses
)

# Run test
print("🧪 TESTING UNIFIED LLM")
print("="*80)
print(f"Message: {USER_MESSAGE}")
print(f"Generating: {N_RESPONSES} different responses")
print("="*80 + "\n")

response, updated_state = agent.process_message(USER_MESSAGE, CONVERSATION_STATE)

print(f"\n🤖 Response:\n{response}\n")
print("="*80)
print(f"✅ Check 'Unified_LLM_results.json' for all {N_RESPONSES} responses")
print("="*80)
