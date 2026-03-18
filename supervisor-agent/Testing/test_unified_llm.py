"""
Test script for Unified LLM in isolation.
Only runs Tier 0.5 check and saves JSON output.
"""

import os
from dotenv import load_dotenv
from conversational_agent import ConversationalAgent
from models import ConversationState

# Load environment variables
load_dotenv()

# Initialize agent in TEST MODE
agent = ConversationalAgent(
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    test_mode=True  # 🧪 This stops execution after Unified LLM call
)

# Test cases to try
test_cases = [
    # Confirmations
    "yes",
    "ok proceed",
    "go ahead",
    
    # Cancellations
    "cancel",
    "nevermind",
    "cancel and send email to john@example.com",  # Compound
    
    # Modifications
    "change subject to Q4 Report",
    "make it urgent",
    
    # Followup answers
    "john@example.com",
    "tomorrow at 3pm",
    
    # Task requests
    "send email to sarah",
    "what can you do?",
    "search my inbox",
    
    # Casual
    "how are you?",
    "thanks",
    
    # Unintelligible
    "asdfkj3489"
]

def test_message(message: str, state: ConversationState = None):
    """Test a single message and show results"""
    print("\n" + "="*80)
    print(f"📝 Testing: '{message}'")
    print("="*80)
    
    if state is None:
        state = ConversationState()
    
    response, updated_state = agent.process_message(message, state)
    
    print(f"\n🤖 Response:\n{response}\n")
    print(f"📄 Check 'Unified_LLM_results.json' for detailed output")
    
    return updated_state

# Main test flow
if __name__ == "__main__":
    print("🧪 UNIFIED LLM TEST MODE")
    print("="*80)
    print("This will ONLY run the Unified LLM check and save results to JSON.")
    print("Full analysis is SKIPPED to speed up testing.\n")
    
    # Run all test cases
    for i, test_msg in enumerate(test_cases, 1):
        print(f"\n\n{'#'*80}")
        print(f"TEST CASE {i}/{len(test_cases)}")
        print(f"{'#'*80}")
        
        # Create fresh state for each test
        state = ConversationState()
        
        # For modification/followup tests, simulate having data
        if "change" in test_msg.lower() or test_msg.count("@") > 0:
            state.extracted_info = {
                "task_type": "send_email",
                "recipient": "old@example.com",
                "subject": "Old Subject"
            }
            state.missing_fields = ["body"]
            state.clarification_question = "What should the email say?"
        
        test_message(test_msg, state)
        
        input("\nPress Enter to continue to next test...")
    
    print("\n\n✅ All tests completed!")
    print("Check 'Unified_LLM_results.json' for the last result.")
