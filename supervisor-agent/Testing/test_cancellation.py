"""
Test cancellation handling - verifies that cancelled requests preserve data
"""

from conversational_agent import ConversationalAgent, ConversationState, ConversationIntent
import os
from dotenv import load_dotenv

load_dotenv()

def test_cancellation_preserves_data():
    """Test that cancelling a request preserves the extracted information"""
    
    agent = ConversationalAgent(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o",
        db_path=":memory:"  # In-memory database for testing
    )
    
    print("\n" + "="*60)
    print("TEST: Cancellation Preserves Data")
    print("="*60)
    
    # Step 1: Start a request
    print("\n📨 Step 1: User starts email request")
    print("User: 'Send an email to john@example.com'")
    
    state = ConversationState()
    response1, state = agent.process_message(
        "Send an email to john@example.com",
        state,
        state_id="test_cancel"
    )
    
    print(f"\nBot: {response1}")
    print(f"\n📊 State after step 1:")
    print(f"   Intent: {state.intent}")
    print(f"   Extracted: {state.extracted_info}")
    print(f"   Missing: {state.missing_fields}")
    
    # Step 2: Provide subject
    print("\n\n📝 Step 2: User provides subject")
    print("User: 'Q4 Planning Meeting'")
    
    response2, state = agent.process_message(
        "Q4 Planning Meeting",
        state,
        state_id="test_cancel"
    )
    
    print(f"\nBot: {response2}")
    print(f"\n📊 State after step 2:")
    print(f"   Intent: {state.intent}")
    print(f"   Extracted: {state.extracted_info}")
    print(f"   Missing: {state.missing_fields}")
    
    # Step 3: Provide body (now ready to execute)
    print("\n\n✍️ Step 3: User provides body")
    print("User: 'Hi John, let's discuss Q4 goals tomorrow at 2pm.'")
    
    response3, state = agent.process_message(
        "Hi John, let's discuss Q4 goals tomorrow at 2pm.",
        state,
        state_id="test_cancel"
    )
    
    print(f"\nBot: {response3}")
    print(f"\n📊 State after step 3:")
    print(f"   Intent: {state.intent}")
    print(f"   Extracted: {state.extracted_info}")
    print(f"   Ready to execute: {state.ready_for_execution}")
    
    # Step 4: CANCEL!
    print("\n\n🚫 Step 4: User cancels")
    print("User: 'No, cancel that'")
    
    response4, state = agent.process_message(
        "No, cancel that",
        state,
        state_id="test_cancel"
    )
    
    print(f"\nBot: {response4}")
    print(f"\n📊 State after cancellation:")
    print(f"   Intent: {state.intent}")
    print(f"   Extracted: {state.extracted_info}")
    print(f"   Ready to execute: {state.ready_for_execution}")
    
    # VERIFY: Data should still be there!
    print("\n" + "="*60)
    print("VERIFICATION:")
    print("="*60)
    
    if state.intent == ConversationIntent.CANCELLED:
        print("✅ Intent correctly set to CANCELLED")
    else:
        print(f"❌ Intent is {state.intent}, expected CANCELLED")
    
    # Check for both 'to' and 'recipient' field names
    email_to = state.extracted_info.get("to") or state.extracted_info.get("recipient")
    if email_to == "john@example.com":
        print("✅ Email recipient preserved: john@example.com")
    else:
        print(f"❌ Email recipient lost: {email_to}")
        print(f"   Available fields: {list(state.extracted_info.keys())}")
    
    if state.extracted_info.get("subject") == "Q4 Planning Meeting":
        print("✅ Subject preserved: Q4 Planning Meeting")
    else:
        print(f"❌ Subject lost: {state.extracted_info.get('subject')}")
    
    if "Hi John" in state.extracted_info.get("body", ""):
        print("✅ Body preserved")
    else:
        print(f"❌ Body lost: {state.extracted_info.get('body')}")
    
    if not state.ready_for_execution:
        print("✅ Execution blocked (ready_for_execution = False)")
    else:
        print("❌ Execution not blocked!")
    
    # Step 5: User modifies and proceeds
    print("\n\n🔄 Step 5: User modifies subject and wants to proceed")
    print("User: 'Actually, change the subject to Q3 Planning and send it'")
    
    response5, state = agent.process_message(
        "Actually, change the subject to Q3 Planning and send it",
        state,
        state_id="test_cancel"
    )
    
    print(f"\nBot: {response5}")
    print(f"\n📊 Final state:")
    print(f"   Intent: {state.intent}")
    print(f"   Extracted: {state.extracted_info}")
    print(f"   Ready to execute: {state.ready_for_execution}")
    
    # VERIFY: Should still have all data with modified subject
    print("\n" + "="*60)
    print("FINAL VERIFICATION:")
    print("="*60)
    
    # Check for both 'to' and 'recipient' field names
    email_to = state.extracted_info.get("to") or state.extracted_info.get("recipient")
    if email_to == "john@example.com":
        print("✅ Email recipient still preserved after modification")
    else:
        print(f"❌ Email recipient lost after modification: {email_to}")
        print(f"   Available fields: {list(state.extracted_info.keys())}")
    
    if "Q3 Planning" in state.extracted_info.get("subject", ""):
        print("✅ Subject successfully modified to Q3 Planning")
    else:
        print(f"❌ Subject not modified: {state.extracted_info.get('subject')}")
    
    if "Hi John" in state.extracted_info.get("body", ""):
        print("✅ Body still preserved after modification")
    else:
        print(f"❌ Body lost after modification")
    
    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)

if __name__ == "__main__":
    test_cancellation_preserves_data()
