"""
Test script for Conversation Memory Manager integration with Conversational Agent
"""

import os
from conversational_agent import ConversationalAgent

def test_memory_integration():
    """Test that memory manager is properly integrated with conversational agent"""
    
    print("="*80)
    print("TESTING MEMORY MANAGER INTEGRATION")
    print("="*80)
    
    # Initialize agent
    agent = ConversationalAgent(
        openai_api_key=os.getenv("OPENAI_API_KEY", "your-key-here")
    )
    
    # Simulate long conversation to trigger summarization
    test_messages = [
        "I need to send an email to john@example.com",
        "The subject should be 'Q4 Planning Meeting'",
        "In the body, mention that we need to discuss budget allocation for next quarter",
        "Yes, send it",
        "Now search my emails for invoices from last month",
        "Show me the one from Acme Corp",
        "Create a Google Doc summarizing all invoices",
        "Title it 'October Invoices Summary'",
        "Add a table with columns for vendor, amount, and date",
        "Yes, create it",
        "Search for emails from sarah@example.com",
        "Reply to the most recent one",
        "Say that I'll review the proposal by Friday",
        "Yes, send the reply",
    ]
    
    state = None
    
    print("\n" + "="*80)
    print("SIMULATING CONVERSATION")
    print("="*80)
    
    for i, message in enumerate(test_messages, 1):
        print(f"\n--- Turn {i} ---")
        print(f"User: {message}")
        
        response, state = agent.process_message(message, state, state_id="test_conversation")
        
        print(f"Bot: {response[:150]}{'...' if len(response) > 150 else ''}")
        
        # Show memory stats every 3 turns
        if i % 3 == 0:
            stats = agent.get_memory_stats(state, "test_conversation")
            print(f"\n📊 Memory Stats:")
            print(f"   Total messages: {stats['total_messages']}")
            print(f"   Working context: {stats['working_context_messages']}")
            print(f"   Token utilization: {stats['token_utilization']}")
            print(f"   Has summary: {stats['has_summary']}")
            print(f"   Total entities: {stats['total_entities']}")
    
    print("\n" + "="*80)
    print("FINAL MEMORY STATE")
    print("="*80)
    
    final_stats = agent.get_memory_stats(state, "test_conversation")
    for key, value in final_stats.items():
        print(f"{key}: {value}")
    
    print("\n" + "="*80)
    print("TESTING PERSISTENCE")
    print("="*80)
    
    # Export state
    print("Exporting conversation state...")
    import json
    exported_state = state.dict()
    print(f"Exported state size: {len(json.dumps(exported_state))} characters")
    print(f"Memory state present: {exported_state.get('memory_state') is not None}")
    
    # Create new agent and load state
    print("\nCreating new agent and loading state...")
    new_agent = ConversationalAgent(
        openai_api_key=os.getenv("OPENAI_API_KEY", "your-key-here")
    )
    
    # Recreate state from dict
    from conversational_agent import ConversationState
    loaded_state = ConversationState(**exported_state)
    
    # Test that memory is properly loaded
    loaded_stats = new_agent.get_memory_stats(loaded_state, "test_conversation")
    print(f"Loaded memory stats:")
    for key, value in loaded_stats.items():
        print(f"  {key}: {value}")
    
    # Verify continuity by sending a new message
    print("\nTesting continuity with new message...")
    response, loaded_state = new_agent.process_message(
        "What was that email about again?",
        loaded_state,
        "test_conversation"
    )
    print(f"Bot: {response[:150]}{'...' if len(response) > 150 else ''}")
    
    print("\n" + "="*80)
    print("✅ MEMORY INTEGRATION TEST COMPLETE")
    print("="*80)


if __name__ == "__main__":
    test_memory_integration()
