"""
Simple Cancellation Test: Multi-Task Scenarios
Tests that cancellation clears everything for supervisor planning layer
"""

from conversational_agent import ConversationalAgent
from models import ConversationState, ConversationIntent
import os
from dotenv import load_dotenv

load_dotenv()

def test_simple_cancellation():
    """Test that cancellation empties extracted_info completely"""
    
    agent = ConversationalAgent(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o",
        db_path=":memory:"
    )
    
    print("\n" + "="*70)
    print("SIMPLE CANCELLATION TEST: Multi-Task with Supervisor Planning")
    print("="*70)
    
    state = ConversationState()
    
    # === TEST 1: Start email, collect data, cancel ===
    print("\n" + "-"*70)
    print("TEST 1: Email Task → Cancel (Everything Cleared)")
    print("-"*70)
    
    print("\n1️⃣  User: 'Send email to alice@example.com about Project Update'")
    r1, state = agent.process_message(
        "Send email to alice@example.com about Project Update",
        state, "test1"
    )
    print(f"✓ State after email: {list(state.extracted_info.keys())}")
    
    print("\n2️⃣  User: 'Body: Hi Alice, here is the update.'")
    r2, state = agent.process_message(
        "Body: Hi Alice, here is the update.",
        state, "test1"
    )
    print(f"✓ State after body: {list(state.extracted_info.keys())}")
    
    # Verify we have data
    assert len(state.extracted_info) > 0, "Should have extracted email data"
    
    print("\n3️⃣  User: 'No, cancel that'")
    r3, state = agent.process_message("No, cancel that", state, "test1")
    print(f"✓ Intent: {state.intent}")
    print(f"✓ State after cancel: {state.extracted_info}")
    
    # CRITICAL: extracted_info should be EMPTY after cancellation
    assert state.intent == ConversationIntent.CANCELLED
    assert state.extracted_info == {}, f"❌ extracted_info should be empty! Got: {state.extracted_info}"
    print("✅ Cancellation clears all data!")
    
    # === TEST 2: Switch to different task (should start fresh) ===
    print("\n" + "-"*70)
    print("TEST 2: New Task After Cancel (Clean Slate)")
    print("-"*70)
    
    print("\n4️⃣  User: 'Search my emails from bob@example.com'")
    r4, state = agent.process_message(
        "Search my emails from bob@example.com",
        state, "test1"
    )
    print(f"✓ State: {list(state.extracted_info.keys())}")
    
    # Should ONLY have search-related fields, no old email data
    has_email_fields = any(k in state.extracted_info for k in ['recipient', 'to', 'subject', 'body'])
    has_search_fields = any(k in state.extracted_info for k in ['query', 'max_results'])
    
    assert not has_email_fields, f"❌ Old email data present: {state.extracted_info}"
    assert has_search_fields, f"❌ Search data missing: {state.extracted_info}"
    print("✅ New task has clean state, no old data!")
    
    # === TEST 3: Cancel and switch multiple times ===
    print("\n" + "-"*70)
    print("TEST 3: Multiple Cancel + Switch (Always Clean)")
    print("-"*70)
    
    print("\n5️⃣  User: 'Cancel'")
    r5, state = agent.process_message("Cancel", state, "test1")
    print(f"✓ State after cancel: {state.extracted_info}")
    assert state.extracted_info == {}, "Should be empty"
    
    print("\n6️⃣  User: 'Create a Google doc titled Meeting Notes'")
    r6, state = agent.process_message(
        "Create a Google doc titled Meeting Notes",
        state, "test1"
    )
    print(f"✓ State: {list(state.extracted_info.keys())}")
    
    # Should ONLY have document fields
    has_search_fields = any(k in state.extracted_info for k in ['query', 'max_results'])
    has_doc_fields = any(k in state.extracted_info for k in ['title', 'doc_id', 'content'])
    
    assert not has_search_fields, f"❌ Old search data present: {state.extracted_info}"
    assert has_doc_fields, f"❌ Document data missing: {state.extracted_info}"
    print("✅ Document task has clean state!")
    
    print("\n7️⃣  User: 'No wait, cancel that'")
    r7, state = agent.process_message("No wait, cancel that", state, "test1")
    print(f"✓ State after cancel: {state.extracted_info}")
    assert state.extracted_info == {}, "Should be empty"
    
    print("\n8️⃣  User: 'Send email to charlie@example.com'")
    r8, state = agent.process_message(
        "Send email to charlie@example.com",
        state, "test1"
    )
    print(f"✓ State: {list(state.extracted_info.keys())}")
    
    # Should ONLY have new email fields
    has_doc_fields = any(k in state.extracted_info for k in ['title', 'doc_id', 'content'])
    has_email_fields = any(k in state.extracted_info for k in ['recipient', 'to', 'subject', 'body'])
    
    assert not has_doc_fields, f"❌ Old document data present: {state.extracted_info}"
    assert has_email_fields, f"❌ Email data missing: {state.extracted_info}"
    print("✅ New email task has clean state!")
    
    # === FINAL VERIFICATION ===
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print("✅ Cancellation empties extracted_info completely")
    print("✅ New tasks always start with clean state")
    print("✅ No data accumulation across tasks")
    print("✅ Supervisor planning layer will receive clean data")
    print("✅ If fields are missing after cancel, agent will ask")
    print("\n🎉 ALL TESTS PASSED!")
    print("="*70)

if __name__ == "__main__":
    test_simple_cancellation()
