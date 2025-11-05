"""
Quick Test for Thread Endpoints
Simple and focused tests for thread creation and messaging
"""

import requests
import json
import time

BASE_URL = "http://localhost:8000"

print("\n" + "="*60)
print("QUICK THREAD ENDPOINT TEST")
print("="*60 + "\n")

# Test 1: Create thread with initial message
print("1️⃣  Creating thread with initial message...")
create_payload = {
    "user_id": "quick_test_user",
    "message": "Hello! What can you help me with?",
    "tags": ["quick-test"]
}

response = requests.post(f"{BASE_URL}/threads", json=create_payload)
print(f"Status: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    thread_id = data["thread_id"]
    print(f"✓ Thread created: {thread_id}")
    print(f"Bot: {data.get('bot_response', '')[:100]}...")
    
    time.sleep(2)
    
    # Test 2: Send follow-up message
    print(f"\n2️⃣  Sending follow-up message to thread {thread_id}...")
    message_payload = {
        "message": "I want to search my emails from last week"
    }
    
    response2 = requests.post(
        f"{BASE_URL}/threads/{thread_id}/messages",
        json=message_payload
    )
    
    print(f"Status: {response2.status_code}")
    
    if response2.status_code == 200:
        data2 = response2.json()
        print(f"✓ Message sent successfully")
        print(f"Bot: {data2.get('bot_response', '')[:200]}...")
        print(f"Ready for execution: {data2.get('ready_for_execution', False)}")
        
        time.sleep(2)
        
        # Test 3: Get thread messages
        print(f"\n3️⃣  Retrieving conversation history...")
        response3 = requests.get(f"{BASE_URL}/threads/{thread_id}/messages")
        
        if response3.status_code == 200:
            data3 = response3.json()
            messages = data3.get("messages", [])
            print(f"✓ Retrieved {len(messages)} messages:")
            
            for msg in messages:
                role = msg["role"]
                content = msg["content"][:80]
                print(f"  [{role.upper()}]: {content}...")
        else:
            print(f"✗ Failed to get messages: {response3.status_code}")
    else:
        print(f"✗ Failed to send message: {response2.status_code}")
        print(f"Error: {response2.text}")
else:
    print(f"✗ Failed to create thread: {response.status_code}")
    print(f"Error: {response.text}")

print("\n" + "="*60)
print("TEST COMPLETE")
print("="*60 + "\n")
