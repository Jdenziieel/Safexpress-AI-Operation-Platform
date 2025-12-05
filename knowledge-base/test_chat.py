"""
Test script to verify chat implementation is working correctly.
Run this after starting the Flask server.
"""
import requests
import json

BASE_URL = "http://localhost:8009"

def test_chat_flow():
    """Test the complete chat flow"""
    print("🧪 Testing Chat Implementation\n")
    
    # Test 1: Create a new session
    print("1️⃣ Creating new chat session...")
    response = requests.post(
        f"{BASE_URL}/chat/session/new",
        json={"user_id": "test-user"}
    )
    
    if response.status_code == 200:
        data = response.json()
        session_id = data.get('session_id')
        print(f"   ✅ Session created: {session_id}\n")
    else:
        print(f"   ❌ Failed to create session: {response.text}\n")
        return
    
    # Test 2: Send a message
    print("2️⃣ Sending message to chat...")
    response = requests.post(
        f"{BASE_URL}/chat/message",
        json={
            "session_id": session_id,
            "message": "What information is available in the knowledge base?",
            "options": {
                "max_sources": 5,
                "include_context": True
            }
        }
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ Response received")
        print(f"   📝 Content: {data.get('content', '')[:100]}...")
        print(f"   📚 Sources: {len(data.get('sources', []))} found")
        print(f"   🔢 Tokens used: {data.get('metadata', {}).get('tokens_used', 0)}\n")
    else:
        print(f"   ❌ Failed to send message: {response.text}\n")
        return
    
    # Test 3: Get chat history
    print("3️⃣ Retrieving chat history...")
    response = requests.get(f"{BASE_URL}/chat/session/{session_id}/history")
    
    if response.status_code == 200:
        data = response.json()
        message_count = len(data.get('messages', []))
        print(f"   ✅ History retrieved: {message_count} messages\n")
    else:
        print(f"   ❌ Failed to get history: {response.text}\n")
        return
    
    # Test 4: List sessions
    print("4️⃣ Listing user sessions...")
    response = requests.get(f"{BASE_URL}/chat/sessions?user_id=test-user")
    
    if response.status_code == 200:
        data = response.json()
        session_count = len(data.get('sessions', []))
        print(f"   ✅ Sessions listed: {session_count} sessions found\n")
    else:
        print(f"   ❌ Failed to list sessions: {response.text}\n")
        return
    
    # Test 5: Follow-up message (context-aware)
    print("5️⃣ Sending follow-up message...")
    response = requests.post(
        f"{BASE_URL}/chat/message",
        json={
            "session_id": session_id,
            "message": "Tell me more about that",
            "options": {
                "max_sources": 5,
                "include_context": True
            }
        }
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ Follow-up response received")
        print(f"   📝 Content: {data.get('content', '')[:100]}...")
        print(f"   🔍 Query resolved: {data.get('metadata', {}).get('search_query', '')}\n")
    else:
        print(f"   ❌ Failed to send follow-up: {response.text}\n")
    
    print("✨ All tests completed!")
    print(f"🗑️  Session ID for cleanup: {session_id}")

if __name__ == "__main__":
    try:
        test_chat_flow()
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to backend. Make sure Flask server is running on port 8009")
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
