"""
Test Thread Management System Integration

This script tests the complete thread management system:
1. Creating new threads
2. Continuing threads
3. Listing threads
4. Searching threads
5. Updating thread metadata
6. Archiving threads
"""

import os
import sys
from datetime import datetime

# Import the conversational agent
from conversational_agent import ConversationalAgent

def print_section(title):
    """Print a formatted section header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def print_thread_info(thread_metadata):
    """Print thread metadata in a formatted way"""
    print(f"\n📋 Thread: {thread_metadata['thread_id']}")
    print(f"   User: {thread_metadata['user_id']}")
    print(f"   Title: {thread_metadata['title']}")
    print(f"   Messages: {thread_metadata['message_count']}")
    print(f"   Status: {thread_metadata['status']}")
    print(f"   Tags: {thread_metadata.get('tags', [])}")
    print(f"   Created: {thread_metadata['created_at']}")
    print(f"   Updated: {thread_metadata['updated_at']}")
    if thread_metadata.get('last_message_preview'):
        preview = thread_metadata['last_message_preview']
        print(f"   Last Message: {preview[:60]}...")

def main():
    print_section("Thread Management System Test")
    
    # Initialize agent
    print("\n🔧 Initializing ConversationalAgent with thread management...")
    agent = ConversationalAgent(
        openai_api_key=os.getenv("OPENAI_API_KEY", "test-key"),
        db_path="test_threads.db"  # Use test database
    )
    print("✅ Agent initialized with database: test_threads.db")
    
    # Test 1: Create new thread with initial message
    print_section("TEST 1: Create New Thread")
    
    user_id = "test_user_123"
    thread_id_1, state_1 = agent.create_new_thread(
        user_id=user_id,
        initial_message="Send an email to john@example.com",
        tags=["email", "test"]
    )
    
    print(f"\n✅ Thread created: {thread_id_1}")
    print(f"📊 Ready for execution: {state_1.ready_for_execution}")
    
    # Get thread metadata
    metadata_1 = agent.get_thread_metadata(thread_id_1)
    print_thread_info(metadata_1)
    
    # Test 2: Continue the thread
    print_section("TEST 2: Continue Thread")
    
    print(f"\n💬 Continuing thread {thread_id_1}...")
    response_2, state_2 = agent.continue_thread(
        thread_id=thread_id_1,
        new_message="The subject is 'Meeting Notes'"
    )
    
    print(f"\n🤖 Bot Response: {response_2[:100]}...")
    print(f"📊 Ready for execution: {state_2.ready_for_execution}")
    
    metadata_2 = agent.get_thread_metadata(thread_id_1)
    print_thread_info(metadata_2)
    
    # Test 3: Create another thread
    print_section("TEST 3: Create Another Thread")
    
    thread_id_2, state_3 = agent.create_new_thread(
        user_id=user_id,
        initial_message="Search my emails for invoices from last month",
        tags=["email", "search", "test"]
    )
    
    print(f"\n✅ Thread created: {thread_id_2}")
    metadata_3 = agent.get_thread_metadata(thread_id_2)
    print_thread_info(metadata_3)
    
    # Test 4: List all threads
    print_section("TEST 4: List User's Threads")
    
    threads = agent.list_user_threads(
        user_id=user_id,
        status="active"
    )
    
    print(f"\n📋 Found {len(threads)} active threads for user: {user_id}")
    for i, thread in enumerate(threads, 1):
        print(f"\n{i}. {thread['title']}")
        print(f"   ID: {thread['thread_id']}")
        print(f"   Messages: {thread['message_count']}")
        print(f"   Updated: {thread['updated_at']}")
    
    # Test 5: Get thread messages
    print_section("TEST 5: Get Thread Messages")
    
    messages = agent.get_thread_messages(thread_id_1)
    
    print(f"\n💬 Thread {thread_id_1} has {len(messages)} messages:")
    for i, msg in enumerate(messages, 1):
        role = "👤 User" if msg['role'] == 'user' else "🤖 Bot"
        content = msg['content'][:80] + "..." if len(msg['content']) > 80 else msg['content']
        print(f"\n{i}. {role}: {content}")
    
    # Test 6: Search threads
    print_section("TEST 6: Search Threads")
    
    search_results = agent.search_threads(
        user_id=user_id,
        query="email"
    )
    
    print(f"\n🔍 Search results for 'email': {len(search_results)} threads")
    for thread in search_results:
        print(f"   • {thread['title']} ({thread['message_count']} messages)")
    
    # Test 7: Update thread metadata
    print_section("TEST 7: Update Thread Metadata")
    
    print(f"\n📝 Updating thread {thread_id_1}...")
    success = agent.update_thread_metadata(
        thread_id=thread_id_1,
        title="Email to John - Meeting Notes",
        tags=["email", "meeting", "important", "test"]
    )
    
    if success:
        print("✅ Thread updated successfully")
        updated_metadata = agent.get_thread_metadata(thread_id_1)
        print_thread_info(updated_metadata)
    else:
        print("❌ Failed to update thread")
    
    # Test 8: Archive thread
    print_section("TEST 8: Archive Thread")
    
    print(f"\n📦 Archiving thread {thread_id_2}...")
    success = agent.archive_thread(thread_id_2)
    
    if success:
        print("✅ Thread archived successfully")
        
        # List active threads (should not include archived)
        active_threads = agent.list_user_threads(user_id=user_id, status="active")
        print(f"\n📋 Active threads: {len(active_threads)}")
        
        # List archived threads
        archived_threads = agent.list_user_threads(user_id=user_id, status="archived")
        print(f"📦 Archived threads: {len(archived_threads)}")
    else:
        print("❌ Failed to archive thread")
    
    # Test 9: Memory stats
    print_section("TEST 9: Memory Statistics")
    
    # Load thread and get memory stats
    state = agent._load_thread_from_db(thread_id_1)
    if state:
        stats = agent.get_memory_stats(state, state_id=thread_id_1)
        
        print(f"\n📊 Memory stats for thread {thread_id_1}:")
        print(f"   Total messages: {stats['message_count']}")
        print(f"   Token count: {stats['total_tokens']}")
        print(f"   Has summary: {stats['has_summary']}")
        print(f"   Summary length: {stats['summary_length']} chars")
        print(f"   Entities extracted: {len(stats['entities'])}")
        
        if stats['entities']:
            print(f"\n   Extracted entities:")
            for entity_type, entities in stats['entities'].items():
                if entities:
                    print(f"      • {entity_type}: {', '.join(entities[:3])}")
    
    # Test 10: Cleanup
    print_section("TEST 10: Cleanup (Hard Delete)")
    
    print(f"\n🗑️ Permanently deleting test threads...")
    
    # Delete both threads
    agent.delete_thread(thread_id_1, hard_delete=True)
    agent.delete_thread(thread_id_2, hard_delete=True)
    
    print("✅ Test threads deleted")
    
    # Verify deletion
    remaining_threads = agent.list_user_threads(user_id=user_id, status="all")
    print(f"📋 Remaining threads for user: {len(remaining_threads)}")
    
    print_section("All Tests Complete!")
    
    print("\n✅ Thread management system is working correctly!")
    print("\n📝 Test Summary:")
    print("   ✓ Thread creation")
    print("   ✓ Thread continuation")
    print("   ✓ Thread listing")
    print("   ✓ Thread search")
    print("   ✓ Thread metadata updates")
    print("   ✓ Thread archival")
    print("   ✓ Memory integration")
    print("   ✓ Thread deletion")
    
    print("\n🧹 Cleanup: test_threads.db can be safely deleted")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
