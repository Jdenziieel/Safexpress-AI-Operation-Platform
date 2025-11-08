"""
Test script for Thread Management Endpoints

Tests:
1. Create thread without initial message
2. Create thread with initial message
3. Create thread with auto-execution
4. Send message to thread
5. Send message that triggers execution
6. Conflict prevention (409 error)
7. List threads for user
8. Get thread metadata
9. Get thread messages
"""

import requests
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:8000"

# Colors for output
GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def print_test(test_name):
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}TEST: {test_name}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")

def print_success(message):
    print(f"{GREEN}✓ {message}{RESET}")

def print_error(message):
    print(f"{RED}✗ {message}{RESET}")

def print_info(message):
    print(f"{YELLOW}ℹ {message}{RESET}")


# ============================================================
# TEST 1: Create Thread Without Initial Message
# ============================================================
def test_create_thread_empty():
    print_test("Create Thread Without Initial Message")
    
    payload = {
        "user_id": "test_user_123",
        "title": "Test Thread - Empty",
        "tags": ["test", "empty"]
    }
    
    print_info(f"Payload: {json.dumps(payload, indent=2)}")
    
    response = requests.post(f"{BASE_URL}/threads", json=payload)
    
    print_info(f"Status Code: {response.status_code}")
    print_info(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 200:
        data = response.json()
        thread_id = data.get("thread_id")
        print_success(f"Thread created: {thread_id}")
        return thread_id
    else:
        print_error(f"Failed to create thread: {response.text}")
        return None


# ============================================================
# TEST 2: Create Thread With Initial Message (Not Ready)
# ============================================================
def test_create_thread_with_message():
    print_test("Create Thread With Initial Message (Clarification Needed)")
    
    payload = {
        "user_id": "test_user_456",
        "message": "I want to send an email",  # Missing details
        "title": "Test Thread - Email",
        "tags": ["test", "email"]
    }
    
    print_info(f"Payload: {json.dumps(payload, indent=2)}")
    
    response = requests.post(f"{BASE_URL}/threads", json=payload)
    
    print_info(f"Status Code: {response.status_code}")
    print_info(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 200:
        data = response.json()
        thread_id = data.get("thread_id")
        bot_response = data.get("bot_response")
        ready = data.get("ready_for_execution", False)
        
        print_success(f"Thread created: {thread_id}")
        print_info(f"Bot Response: {bot_response}")
        print_info(f"Ready for Execution: {ready}")
        return thread_id
    else:
        print_error(f"Failed to create thread: {response.text}")
        return None


# ============================================================
# TEST 3: Create Thread With Auto-Execution
# ============================================================
def test_create_thread_with_execution():
    print_test("Create Thread With Auto-Execution")
    
    payload = {
        "user_id": "test_user_789",
        "message": "Search my emails from john@example.com from last week",
        "tags": ["test", "search", "auto-execute"]
    }
    
    print_info(f"Payload: {json.dumps(payload, indent=2)}")
    
    response = requests.post(f"{BASE_URL}/threads", json=payload)
    
    print_info(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        thread_id = data.get("thread_id")
        bot_response = data.get("bot_response")
        ready = data.get("ready_for_execution", False)
        
        print_success(f"Thread created: {thread_id}")
        print_info(f"Bot Response:\n{bot_response}")
        print_info(f"Ready for Execution: {ready}")
        
        # Check if execution summary is present
        if "executed" in bot_response.lower() or "search" in bot_response.lower():
            print_success("Execution summary detected in response")
        
        return thread_id
    else:
        print_error(f"Failed to create thread: {response.text}")
        return None


# ============================================================
# TEST 4: Send Message to Thread (Clarification)
# ============================================================
def test_send_message_to_thread(thread_id):
    print_test("Send Message to Thread (Continue Conversation)")
    
    if not thread_id:
        print_error("No thread_id provided. Skipping test.")
        return
    
    payload = {
        "message": "john@example.com"  # Providing missing recipient
    }
    
    print_info(f"Thread ID: {thread_id}")
    print_info(f"Payload: {json.dumps(payload, indent=2)}")
    
    response = requests.post(f"{BASE_URL}/threads/{thread_id}/messages", json=payload)
    
    print_info(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        bot_response = data.get("bot_response")
        ready = data.get("ready_for_execution", False)
        
        print_success("Message sent successfully")
        print_info(f"Bot Response: {bot_response}")
        print_info(f"Ready for Execution: {ready}")
        return ready
    else:
        print_error(f"Failed to send message: {response.text}")
        return False


# ============================================================
# TEST 5: Send Message That Triggers Execution
# ============================================================
def test_send_message_with_execution(thread_id):
    print_test("Send Message That Triggers Execution")
    
    if not thread_id:
        print_error("No thread_id provided. Skipping test.")
        return
    
    # First, send a message that requires clarification
    payload1 = {
        "message": "I want to send an email"
    }
    
    print_info(f"Thread ID: {thread_id}")
    print_info(f"Step 1 - Payload: {json.dumps(payload1, indent=2)}")
    
    response1 = requests.post(f"{BASE_URL}/threads/{thread_id}/messages", json=payload1)
    
    if response1.status_code == 200:
        print_success("Step 1: Initial request sent")
        print_info(f"Response: {response1.json().get('bot_response')}")
    
    time.sleep(1)
    
    # Now send complete information to trigger execution
    payload2 = {
        "message": "Send email to test@example.com with subject 'Test' and body 'This is a test message'"
    }
    
    print_info(f"Step 2 - Payload: {json.dumps(payload2, indent=2)}")
    
    response2 = requests.post(f"{BASE_URL}/threads/{thread_id}/messages", json=payload2)
    
    print_info(f"Status Code: {response2.status_code}")
    
    if response2.status_code == 200:
        data = response2.json()
        bot_response = data.get("bot_response")
        ready = data.get("ready_for_execution", False)
        
        print_success("Message sent and processed")
        print_info(f"Bot Response:\n{bot_response}")
        print_info(f"Ready for Execution: {ready}")
        
        # Check if execution happened
        if "executed" in bot_response.lower() or "sent" in bot_response.lower():
            print_success("Execution summary detected in response!")
        
    else:
        print_error(f"Failed to send message: {response2.text}")


# ============================================================
# TEST 6: Conflict Prevention (Try to send while executing)
# ============================================================
def test_conflict_prevention():
    print_test("Conflict Prevention (409 Error)")
    
    # Create a thread with a long-running task
    payload1 = {
        "user_id": "test_user_conflict",
        "message": "Search my emails from last month",
        "tags": ["test", "conflict"]
    }
    
    print_info("Creating thread with task...")
    response1 = requests.post(f"{BASE_URL}/threads", json=payload1)
    
    if response1.status_code != 200:
        print_error("Failed to create thread for conflict test")
        return
    
    thread_id = response1.json().get("thread_id")
    print_success(f"Thread created: {thread_id}")
    
    # Try to send another message immediately (might be executing)
    payload2 = {
        "message": "Actually, search from last week"
    }
    
    print_info("Attempting to send message immediately...")
    
    # Try multiple times to catch execution in progress
    for i in range(3):
        response2 = requests.post(f"{BASE_URL}/threads/{thread_id}/messages", json=payload2)
        
        if response2.status_code == 409:
            print_success(f"✓ Got expected 409 Conflict on attempt {i+1}")
            print_info(f"Error message: {response2.json().get('detail')}")
            return
        elif response2.status_code == 200:
            print_info(f"Attempt {i+1}: Execution completed before request")
        
        time.sleep(0.2)
    
    print_info("Note: Execution may have completed too quickly to catch conflict")


# ============================================================
# TEST 7: List Threads for User
# ============================================================
def test_list_threads():
    print_test("List Threads for User")
    
    user_id = "test_user_456"
    
    print_info(f"User ID: {user_id}")
    
    response = requests.get(f"{BASE_URL}/threads", params={"user_id": user_id})
    
    print_info(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        threads = data.get("threads", [])
        count = data.get("count", 0)
        
        print_success(f"Retrieved {count} threads")
        print_info(f"Response: {json.dumps(data, indent=2)}")
        
        for thread in threads[:3]:  # Show first 3
            print_info(f"  - Thread: {thread.get('thread_id')} | Title: {thread.get('title')}")
    else:
        print_error(f"Failed to list threads: {response.text}")


# ============================================================
# TEST 8: Get Thread Metadata
# ============================================================
def test_get_thread_metadata(thread_id):
    print_test("Get Thread Metadata")
    
    if not thread_id:
        print_error("No thread_id provided. Skipping test.")
        return
    
    print_info(f"Thread ID: {thread_id}")
    
    response = requests.get(f"{BASE_URL}/threads/{thread_id}")
    
    print_info(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print_success("Retrieved thread metadata")
        print_info(f"Response: {json.dumps(data, indent=2)}")
    else:
        print_error(f"Failed to get thread metadata: {response.text}")


# ============================================================
# TEST 9: Get Thread Messages
# ============================================================
def test_get_thread_messages(thread_id):
    print_test("Get Thread Messages (Conversation History)")
    
    if not thread_id:
        print_error("No thread_id provided. Skipping test.")
        return
    
    print_info(f"Thread ID: {thread_id}")
    
    response = requests.get(f"{BASE_URL}/threads/{thread_id}/messages")
    
    print_info(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        messages = data.get("messages", [])
        count = data.get("count", 0)
        
        print_success(f"Retrieved {count} messages")
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")[:100]  # First 100 chars
            created_at = msg.get("created_at")
            print_info(f"  [{role}] {content}... (at {created_at})")
    else:
        print_error(f"Failed to get thread messages: {response.text}")


# ============================================================
# MAIN TEST RUNNER
# ============================================================
def run_all_tests():
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}THREAD ENDPOINTS TEST SUITE{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")
    print(f"{YELLOW}Base URL: {BASE_URL}{RESET}")
    print(f"{YELLOW}Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    
    # Test 1: Create empty thread
    thread_id_empty = test_create_thread_empty()
    time.sleep(1)
    
    # Test 2: Create thread with message (needs clarification)
    thread_id_message = test_create_thread_with_message()
    time.sleep(1)
    
    # Test 3: Create thread with auto-execution
    thread_id_execute = test_create_thread_with_execution()
    time.sleep(2)  # Wait for execution
    
    # Test 4: Send message to continue conversation
    if thread_id_message:
        test_send_message_to_thread(thread_id_message)
        time.sleep(1)
    
    # Test 5: Send message that triggers execution
    if thread_id_empty:
        test_send_message_with_execution(thread_id_empty)
        time.sleep(2)
    
    # Test 6: Conflict prevention
    test_conflict_prevention()
    time.sleep(1)
    
    # Test 7: List threads
    test_list_threads()
    time.sleep(1)
    
    # Test 8: Get thread metadata
    if thread_id_message:
        test_get_thread_metadata(thread_id_message)
        time.sleep(1)
    
    # Test 9: Get thread messages
    if thread_id_message:
        test_get_thread_messages(thread_id_message)
    
    print(f"\n{GREEN}{'='*60}{RESET}")
    print(f"{GREEN}ALL TESTS COMPLETED{RESET}")
    print(f"{GREEN}{'='*60}{RESET}\n")


if __name__ == "__main__":
    try:
        run_all_tests()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Tests interrupted by user{RESET}")
    except Exception as e:
        print(f"\n{RED}Error running tests: {str(e)}{RESET}")
        import traceback
        traceback.print_exc()
