"""
Test cancellation + task switching - what happens when user cancels and switches to a different task?
"""

from conversational_agent import ConversationalAgent
from models import ConversationState, ConversationIntent
import os
from dotenv import load_dotenv

load_dotenv()

def test_cancel_and_switch_task():
    """Test cancelling an email and switching to search task"""
    
    agent = ConversationalAgent(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o",
        db_path=":memory:"
    )
    
    print("\n" + "="*60)
    print("TEST: Cancel Email, Switch to Search Task")
    print("="*60)
    
    # Step 1: Start email task
    print("\n📨 Step 1: User wants to send email")
    print("User: 'Send an email to john@example.com about Q4 Planning'")
    
    state = ConversationState()
    response1, state = agent.process_message(
        "Send an email to john@example.com about Q4 Planning",
        state,
        state_id="test_switch"
    )
    
    print(f"\nBot: {response1[:200]}...")
    print(f"\n📊 State:")
    print(f"   Intent: {state.intent}")
    print(f"   Task type: {state.extracted_info.get('task_type', 'N/A')}")
    print(f"   Extracted: {state.extracted_info}")
    
    # Step 2: Provide body (make it ready)
    print("\n\n📝 Step 2: Complete the email")
    print("User: 'Body: Let's meet tomorrow to discuss Q4 goals.'")
    
    response2, state = agent.process_message(
        "Body: Let's meet tomorrow to discuss Q4 goals.",
        state,
        state_id="test_switch"
    )
    
    print(f"\nBot: {response2[:200]}...")
    print(f"\n📊 State:")
    print(f"   Intent: {state.intent}")
    print(f"   Ready: {state.ready_for_execution}")
    print(f"   Extracted: {state.extracted_info}")
    
    # Step 3: CANCEL!
    print("\n\n🚫 Step 3: User cancels the email")
    print("User: 'Actually, cancel that email'")
    
    response3, state = agent.process_message(
        "Actually, cancel that email",
        state,
        state_id="test_switch"
    )
    
    print(f"\nBot: {response3}")
    print(f"\n📊 State after cancellation:")
    print(f"   Intent: {state.intent}")
    print(f"   Task type: {state.extracted_info.get('task_type', 'N/A')}")
    print(f"   Email data still there: {state.extracted_info}")
    
    # Step 4: SWITCH to completely different task
    print("\n\n🔄 Step 4: User switches to SEARCH task (completely different)")
    print("User: 'Search my emails from john@example.com sent last week'")
    
    response4, state = agent.process_message(
        "Search my emails from john@example.com sent last week",
        state,
        state_id="test_switch"
    )
    
    print(f"\nBot: {response4[:300]}...")
    print(f"\n📊 State after task switch:")
    print(f"   Intent: {state.intent}")
    print(f"   Task type: {state.extracted_info.get('task_type', 'N/A')}")
    print(f"   Extracted: {state.extracted_info}")
    
    # VERIFY
    print("\n" + "="*60)
    print("VERIFICATION:")
    print("="*60)
    
    # Check if old email data is gone
    old_email_data = {
        'recipient': 'john@example.com',
        'subject': 'Q4 Planning',
        'body': "Let's meet tomorrow"
    }
    
    has_old_email_data = any(
        key in state.extracted_info and 
        ('recipient' in str(state.extracted_info.get(key)).lower() or 
         'Q4 Planning' in str(state.extracted_info.get(key)) or
         'meet tomorrow' in str(state.extracted_info.get(key)))
        for key in ['to', 'recipient', 'subject', 'body']
    )
    
    has_search_data = any(
        'search' in str(state.extracted_info.get(key, '')).lower() or
        'query' in str(key).lower() or
        'from' in str(key).lower()
        for key in state.extracted_info.keys()
    )
    
    print(f"\n🔍 Old email data present: {has_old_email_data}")
    print(f"🔍 New search data present: {has_search_data}")
    
    if has_old_email_data and has_search_data:
        print("\n⚠️  PROBLEM: Both old and new task data mixed together!")
        print("   This creates confusion - old email data shouldn't persist")
        print(f"   Current extracted_info: {state.extracted_info}")
    elif has_old_email_data and not has_search_data:
        print("\n⚠️  PROBLEM: Still has old email data, new search task not recognized!")
        print(f"   Current extracted_info: {state.extracted_info}")
    elif not has_old_email_data and has_search_data:
        print("\n✅ GOOD: Old email data cleared, new search task data present")
        print(f"   Current extracted_info: {state.extracted_info}")
    else:
        print("\n⚠️  UNCLEAR: Neither old nor new data detected")
        print(f"   Current extracted_info: {state.extracted_info}")
    
    # Step 5: Try another completely new task
    print("\n\n🔄 Step 5: Switch to ANOTHER task (create document)")
    print("User: 'Create a Google doc titled Project Overview'")
    
    response5, state = agent.process_message(
        "Create a Google doc titled Project Overview",
        state,
        state_id="test_switch"
    )
    
    print(f"\nBot: {response5[:300]}...")
    print(f"\n📊 Final state:")
    print(f"   Intent: {state.intent}")
    print(f"   Task type: {state.extracted_info.get('task_type', 'N/A')}")
    print(f"   Extracted: {state.extracted_info}")
    
    # Check if search data is still there
    print("\n" + "="*60)
    print("FINAL CHECK: Are we mixing data from multiple tasks?")
    print("="*60)
    
    task_indicators = {
        'email': ['recipient', 'to', 'subject', 'body', 'Q4'],
        'search': ['query', 'search', 'from:'],
        'document': ['title', 'doc', 'document', 'Project Overview']
    }
    
    detected_tasks = []
    for task_name, indicators in task_indicators.items():
        if any(
            any(ind.lower() in str(v).lower() for ind in indicators)
            for k, v in state.extracted_info.items()
        ):
            detected_tasks.append(task_name)
    
    print(f"\nDetected task data: {detected_tasks}")
    
    if len(detected_tasks) > 1:
        print(f"\n❌ PROBLEM: Multiple task data present! {detected_tasks}")
        print("   extracted_info is accumulating data from different tasks")
        print(f"   Current: {state.extracted_info}")
    elif len(detected_tasks) == 1:
        print(f"\n✅ GOOD: Only current task data present ({detected_tasks[0]})")
        print(f"   Current: {state.extracted_info}")
    else:
        print("\n🤷 No clear task data detected")
        print(f"   Current: {state.extracted_info}")
    
    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)

if __name__ == "__main__":
    test_cancel_and_switch_task()
