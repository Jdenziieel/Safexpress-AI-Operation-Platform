"""
Comprehensive test: Simple Cancellation for Multi-Task Scenarios
Tests that cancellation empties everything for clean supervisor integration
"""

from conversational_agent import ConversationalAgent, ConversationState, ConversationIntent
import os
from dotenv import load_dotenv

load_dotenv()

def test_comprehensive_flow():
    """Test complete flow: cancel empties state, tasks always start clean"""
    
    agent = ConversationalAgent(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o",
        db_path=":memory:"
    )
    
    print("\n" + "="*70)
    print("COMPREHENSIVE TEST: Simple Cancellation for Multi-Task")
    print("="*70)
    
    state = ConversationState()
    
    # === SCENARIO 1: Start email, cancel, state emptied ===
    print("\n" + "-"*70)
    print("SCENARIO 1: Email Task → Cancel (Everything Cleared)")
    print("-"*70)
    
    print("\n1️⃣  User: 'Send email to alice@example.com about Project Update'")
    r1, state = agent.process_message(
        "Send email to alice@example.com about Project Update",
        state, "test1"
    )
    print(f"Bot: {r1[:150]}...")
    print(f"✓ State: Intent={state.intent}, Data={list(state.extracted_info.keys())}")
    
    print("\n2️⃣  User: 'Body: Hi Alice, here is the project update for Q4.'")
    r2, state = agent.process_message(
        "Body: Hi Alice, here is the project update for Q4.",
        state, "test1"
    )
    print(f"Bot: Ready={state.ready_for_execution}")
    print(f"✓ State: Data={list(state.extracted_info.keys())}")
    
    print("\n3️⃣  User: 'No, cancel that'")
    r3, state = agent.process_message("No, cancel that", state, "test1")
    print(f"Bot: Intent={state.intent}")
    print(f"✓ State: Data after cancel={list(state.extracted_info.keys())}")
    
    assert state.intent == ConversationIntent.CANCELLED
    assert state.extracted_info == {}, f"❌ Should be empty! Got: {state.extracted_info}"
    assert state.ready_for_execution == False
    print("✅ Cancellation empties all data!")
    
    # === SCENARIO 2: Switch to different task, clean start ===
    print("\n" + "-"*70)
    print("SCENARIO 2: Switch to Search (Clean Start)")
    print("-"*70)
    
    print("\n4️⃣  User: 'Search my emails from bob@example.com'")
    r4, state = agent.process_message(
        "Search my emails from bob@example.com",
        state, "test1"
    )
    print(f"Bot: Intent={state.intent}")
    print(f"✓ State: Data={list(state.extracted_info.keys())}")
    
    # Verify ONLY search fields, no old email data
    has_email_fields = any(k in state.extracted_info for k in ['recipient', 'to', 'subject', 'body'])
    has_search_fields = any(k in state.extracted_info for k in ['query', 'max_results'])
    
    assert not has_email_fields, f"❌ Old email data present: {state.extracted_info}"
    assert has_search_fields, f"❌ Search data missing: {state.extracted_info}"
    print("✅ New task has clean state!")
    
    # === SCENARIO 3: Cancel search, switch to document ===
    print("\n" + "-"*70)
    print("SCENARIO 3: Cancel Search → Switch to Document")
    print("-"*70)
    
    print("\n5️⃣  User: 'Cancel that search'")
    r5, state = agent.process_message("Cancel that search", state, "test1")
    print(f"Bot: Intent={state.intent}")
    print(f"✓ State: Data after cancel={state.extracted_info}")
    
    assert state.extracted_info == {}, f"❌ Should be empty! Got: {state.extracted_info}"
    print("✅ Cancel empties state!")
    
    print("\n6️⃣  User: 'Create a Google doc titled Meeting Notes'")
    r6, state = agent.process_message(
        "Create a Google doc titled Meeting Notes",
        state, "test1"
    )
    print(f"Bot: Intent={state.intent}")
    print(f"✓ State: Data={list(state.extracted_info.keys())}")
    
    # Verify ONLY document data
    has_search_fields = any(k in state.extracted_info for k in ['query', 'max_results'])
    has_doc_fields = any(k in state.extracted_info for k in ['title', 'doc_id', 'content'])
    
    assert not has_search_fields, f"❌ Old search data present: {state.extracted_info}"
    assert has_doc_fields, f"❌ Document data missing: {state.extracted_info}"
    print("✅ Document task has clean state!")
    
    # === SCENARIO 4: Modify same task (no cleanup) ===
    print("\n" + "-"*70)
    print("SCENARIO 4: Modify Same Task (No Cleanup)")
    print("-"*70)
    
    print("\n7️⃣  User: 'Actually, change the title to Q4 Summary'")
    r7, state = agent.process_message(
        "Actually, change the title to Q4 Summary",
        state, "test1"
    )
    print(f"Bot: Intent={state.intent}")
    print(f"✓ State: Data={list(state.extracted_info.keys())}")
    
    # Verify title was modified (still document task)
    assert 'title' in state.extracted_info
    assert 'Q4 Summary' in str(state.extracted_info.get('title', ''))
    print("✅ Same task modification works!")
    
    # === SCENARIO 5: Back to email (new task, empty start) ===
    print("\n" + "-"*70)
    print("SCENARIO 5: Back to Email (New Email, Clean State)")
    print("-"*70)
    
    print("\n8️⃣  User: 'Cancel that'")
    r8a, state = agent.process_message("Cancel that", state, "test1")
    print(f"✓ State after cancel: {state.extracted_info}")
    assert state.extracted_info == {}, "Should be empty"
    
    print("\n9️⃣  User: 'Send an email to charlie@example.com'")
    r8, state = agent.process_message(
        "Send an email to charlie@example.com",
        state, "test1"
    )
    print(f"Bot: Intent={state.intent}")
    print(f"✓ State: Data={list(state.extracted_info.keys())}")
    
    # Verify ONLY new email data
    has_doc_fields = any(k in state.extracted_info for k in ['title', 'doc_id', 'content'])
    has_email_fields = any(k in state.extracted_info for k in ['recipient', 'to', 'subject', 'body'])
    
    assert not has_doc_fields, f"❌ Old document data present: {state.extracted_info}"
    assert has_email_fields, f"❌ Email data missing: {state.extracted_info}"
    
    # Verify it's NEW email, not old alice@ email
    email_to = state.extracted_info.get('recipient') or state.extracted_info.get('to')
    assert 'charlie' in str(email_to).lower(), f"❌ Not new email: {email_to}"
    assert 'alice' not in str(email_to).lower(), f"❌ Old email present: {email_to}"
    print("✅ New email task has clean state!")
    
    # === FINAL SUMMARY ===
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print("✅ Cancellation empties extracted_info completely")
    print("✅ Task switching always gets clean state")
    print("✅ Same task modifications work correctly")
    print("✅ Multiple cancel/switch cycles work properly")
    print("✅ New instances of same task type get clean state")
    print("✅ Perfect for supervisor workflow planning layer")
    print("\n🎉 ALL TESTS PASSED!")
    print("="*70)

if __name__ == "__main__":
    test_comprehensive_flow()
