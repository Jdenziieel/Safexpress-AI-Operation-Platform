"""
Test Compound "Cancel + New Task" Requests
Tests that "cancel X and do Y" in one message works gracefully
"""

from conversational_agent import ConversationalAgent
from models import ConversationState, ConversationIntent
import os
from dotenv import load_dotenv

load_dotenv()

def test_compound_cancel_and_new_task():
    """Test compound 'cancel X and do Y' requests"""
    
    agent = ConversationalAgent(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o",
        db_path=":memory:"
    )
    
    print("\n" + "="*70)
    print("COMPOUND CANCEL TEST: 'Cancel X and Do Y' in One Message")
    print("="*70)
    
    state = ConversationState()
    
    # === TEST 1: Start email task, collect some data ===
    print("\n" + "-"*70)
    print("TEST 1: Build Email Task Context")
    print("-"*70)
    
    print("\n1️⃣  User: 'Send email to alice@example.com about Project Update'")
    r1, state = agent.process_message(
        "Send email to alice@example.com about Project Update",
        state, "test1"
    )
    print(f"✓ State: {list(state.extracted_info.keys())}")
    
    print("\n2️⃣  User: 'Body: Hi Alice, here is the quarterly update.'")
    r2, state = agent.process_message(
        "Body: Hi Alice, here is the quarterly update.",
        state, "test1"
    )
    print(f"✓ State: {list(state.extracted_info.keys())}")
    assert len(state.extracted_info) >= 2, "Should have email data"
    
    # === TEST 2: Compound "cancel + new task" ===
    print("\n" + "-"*70)
    print("TEST 2: Compound Request - Cancel Email + Start Search")
    print("-"*70)
    
    print("\n3️⃣  User: 'Cancel that email and search my emails from bob@example.com'")
    r3, state = agent.process_message(
        "Cancel that email and search my emails from bob@example.com",
        state, "test1"
    )
    print(f"✓ Intent: {state.intent}")
    print(f"✓ State: {list(state.extracted_info.keys())}")
    print(f"✓ Data: {state.extracted_info}")
    
    # Verify:
    # 1. Intent should NOT be CANCELLED (should be READY_TO_EXECUTE for search)
    # 2. Should have search fields, NOT email fields
    # 3. Old email data should be gone
    
    assert state.intent != ConversationIntent.CANCELLED, f"❌ Should not be CANCELLED, got: {state.intent}"
    
    has_email_fields = any(k in state.extracted_info for k in ['recipient', 'to', 'subject', 'body'])
    has_search_fields = any(k in state.extracted_info for k in ['query', 'max_results'])
    
    assert not has_email_fields, f"❌ Old email data present: {state.extracted_info}"
    assert has_search_fields, f"❌ Search data missing: {state.extracted_info}"
    
    print("✅ Compound cancel worked! Old email cleared, new search extracted!")
    
    # === TEST 3: Another compound request ===
    print("\n" + "-"*70)
    print("TEST 3: Compound Request - Cancel Search + Start Document")
    print("-"*70)
    
    print("\n4️⃣  User: 'Cancel that and create a Google doc titled Meeting Notes'")
    r4, state = agent.process_message(
        "Cancel that and create a Google doc titled Meeting Notes",
        state, "test1"
    )
    print(f"✓ Intent: {state.intent}")
    print(f"✓ State: {list(state.extracted_info.keys())}")
    print(f"✓ Data: {state.extracted_info}")
    
    # Verify document task extracted, search data cleared
    assert state.intent != ConversationIntent.CANCELLED
    
    has_search_fields = any(k in state.extracted_info for k in ['query', 'max_results'])
    has_doc_fields = any(k in state.extracted_info for k in ['title', 'doc_id', 'content'])
    
    assert not has_search_fields, f"❌ Old search data present: {state.extracted_info}"
    assert has_doc_fields, f"❌ Document data missing: {state.extracted_info}"
    assert 'Meeting Notes' in str(state.extracted_info.get('title', '')), "Should have doc title"
    
    print("✅ Second compound cancel worked! Old search cleared, new doc extracted!")
    
    # === TEST 4: Pure cancellation still works ===
    print("\n" + "-"*70)
    print("TEST 4: Pure Cancellation (No New Task)")
    print("-"*70)
    
    print("\n5️⃣  User: 'Cancel that document'")
    r5, state = agent.process_message(
        "Cancel that document",
        state, "test1"
    )
    print(f"✓ Intent: {state.intent}")
    print(f"✓ State: {state.extracted_info}")
    
    # Pure cancel should return CANCELLED intent and empty state
    assert state.intent == ConversationIntent.CANCELLED, f"❌ Should be CANCELLED, got: {state.intent}"
    assert state.extracted_info == {}, f"❌ Should be empty, got: {state.extracted_info}"
    
    print("✅ Pure cancellation still works correctly!")
    
    # === TEST 5: Variations of compound cancel ===
    print("\n" + "-"*70)
    print("TEST 5: Different Compound Cancel Phrasings")
    print("-"*70)
    
    # Setup: Create email task
    print("\n6️⃣  User: 'Send email to test@example.com'")
    r6, state = agent.process_message("Send email to test@example.com", state, "test1")
    print(f"✓ State: {list(state.extracted_info.keys())}")
    
    # Test variation: "instead"
    print("\n7️⃣  User: 'Actually cancel that and search for invoices instead'")
    r7, state = agent.process_message(
        "Actually cancel that and search for invoices instead",
        state, "test1"
    )
    print(f"✓ Intent: {state.intent}")
    print(f"✓ State: {list(state.extracted_info.keys())}")
    
    assert state.intent != ConversationIntent.CANCELLED
    has_search = 'query' in state.extracted_info or 'invoices' in str(state.extracted_info).lower()
    assert has_search, f"❌ Search not extracted: {state.extracted_info}"
    
    print("✅ 'Cancel and X instead' phrasing works!")
    
    # === FINAL SUMMARY ===
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print("✅ Compound 'cancel + new task' extracts new task correctly")
    print("✅ Old task data is cleared automatically")
    print("✅ Intent is set to new task (not CANCELLED)")
    print("✅ Pure cancellation (no new task) still works")
    print("✅ Different phrasings handled correctly")
    print("✅ Graceful UX - one message does both actions")
    print("\n🎉 ALL TESTS PASSED!")
    print("="*70)

if __name__ == "__main__":
    test_compound_cancel_and_new_task()
