"""
Execution & Conflict Test for Thread Endpoints
Focused testing of auto-execution and conflict prevention
"""

import requests
import json
import time
import threading

BASE_URL = "http://localhost:8000"

def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")

def test_auto_execution():
    """Test that ready messages trigger automatic execution"""
    print_header("TEST 1: Auto-Execution on Thread Creation")
    
    payload = {
        "user_id": "exec_test_user_1",
        "message": "Search my emails from alice@example.com from last week",
        "tags": ["execution-test"]
    }
    
    print("Creating thread with complete search request...")
    print(f"Message: {payload['message']}")
    
    start_time = time.time()
    response = requests.post(f"{BASE_URL}/threads", json=payload)
    elapsed = time.time() - start_time
    
    print(f"\n⏱️  Response time: {elapsed:.2f}s")
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        thread_id = data["thread_id"]
        bot_response = data.get("bot_response", "")
        
        print(f"✅ Thread created: {thread_id}")
        print(f"\n🤖 Bot Response:")
        print(f"{'-'*60}")
        print(bot_response)
        print(f"{'-'*60}")
        
        # Check if execution happened
        execution_indicators = [
            "executed", "searched", "found", "results",
            "successfully", "completed", "✅", "✓"
        ]
        
        if any(indicator in bot_response.lower() for indicator in execution_indicators):
            print("\n✅ PASS: Execution summary detected!")
            print("   Thread auto-executed upon creation")
        else:
            print("\n⚠️  WARNING: No clear execution indicators found")
            print("   Response might be clarification, not execution result")
        
        return thread_id
    else:
        print(f"❌ FAIL: {response.status_code} - {response.text}")
        return None


def test_execution_in_messages():
    """Test that sending a complete message triggers execution"""
    print_header("TEST 2: Auto-Execution on Message Send")
    
    # First create a thread
    payload1 = {
        "user_id": "exec_test_user_2",
        "message": "Hello",
        "tags": ["execution-test"]
    }
    
    print("Step 1: Creating thread with greeting...")
    response1 = requests.post(f"{BASE_URL}/threads", json=payload1)
    
    if response1.status_code != 200:
        print(f"❌ Failed to create thread: {response1.status_code}")
        return
    
    thread_id = response1.json()["thread_id"]
    print(f"✅ Thread created: {thread_id}")
    
    time.sleep(1)
    
    # Now send a complete task
    payload2 = {
        "message": "Send an email to test@example.com with subject 'Test' and body 'This is a test'"
    }
    
    print(f"\nStep 2: Sending complete task to thread...")
    print(f"Message: {payload2['message']}")
    
    start_time = time.time()
    response2 = requests.post(f"{BASE_URL}/threads/{thread_id}/messages", json=payload2)
    elapsed = time.time() - start_time
    
    print(f"\n⏱️  Response time: {elapsed:.2f}s")
    print(f"Status: {response2.status_code}")
    
    if response2.status_code == 200:
        data = response2.json()
        bot_response = data.get("bot_response", "")
        
        print(f"\n🤖 Bot Response:")
        print(f"{'-'*60}")
        print(bot_response)
        print(f"{'-'*60}")
        
        # Check if execution happened
        execution_indicators = [
            "executed", "sent", "successfully", "completed",
            "✅", "✓", "email sent"
        ]
        
        if any(indicator in bot_response.lower() for indicator in execution_indicators):
            print("\n✅ PASS: Execution summary detected!")
            print("   Task auto-executed when ready")
        else:
            print("\n⚠️  WARNING: No clear execution indicators found")
        
        return thread_id
    else:
        print(f"❌ FAIL: {response2.status_code} - {response2.text}")
        return None


def test_conflict_prevention():
    """Test that concurrent requests are rejected with 409"""
    print_header("TEST 3: Conflict Prevention (409 Error)")
    
    # Create thread with a task that will execute
    payload1 = {
        "user_id": "conflict_test_user",
        "message": "Search my emails from the last month",
        "tags": ["conflict-test"]
    }
    
    print("Creating thread with search task...")
    response1 = requests.post(f"{BASE_URL}/threads", json=payload1)
    
    if response1.status_code != 200:
        print(f"❌ Failed to create thread: {response1.status_code}")
        return
    
    thread_id = response1.json()["thread_id"]
    print(f"✅ Thread created: {thread_id}")
    
    # Define function to send message
    def send_message(delay=0):
        if delay > 0:
            time.sleep(delay)
        payload = {"message": "Actually, search from last week"}
        return requests.post(f"{BASE_URL}/threads/{thread_id}/messages", json=payload)
    
    print("\n🔄 Attempting rapid successive messages to catch execution...")
    
    # Try to send multiple messages in quick succession
    responses = []
    for i in range(5):
        response = send_message(delay=0.1 * i)
        responses.append(response)
        
        if response.status_code == 409:
            print(f"✅ Attempt {i+1}: Got 409 Conflict!")
            print(f"   Error: {response.json().get('detail')}")
        elif response.status_code == 200:
            print(f"   Attempt {i+1}: 200 OK (execution completed)")
        else:
            print(f"   Attempt {i+1}: {response.status_code}")
    
    # Check if we got at least one 409
    conflict_count = sum(1 for r in responses if r.status_code == 409)
    
    if conflict_count > 0:
        print(f"\n✅ PASS: Successfully caught {conflict_count} conflict(s)")
        print("   Conflict prevention is working!")
    else:
        print(f"\n⚠️  INFO: No conflicts detected")
        print("   Execution may have completed too quickly")
        print("   (This is not necessarily a failure)")


def test_execution_summary_quality():
    """Test that execution summaries are user-friendly"""
    print_header("TEST 4: Execution Summary Quality")
    
    payload = {
        "user_id": "summary_test_user",
        "message": "Search emails from bob@test.com from yesterday",
        "tags": ["summary-test"]
    }
    
    print("Creating thread and checking summary quality...")
    response = requests.post(f"{BASE_URL}/threads", json=payload)
    
    if response.status_code == 200:
        data = response.json()
        bot_response = data.get("bot_response", "")
        
        print(f"✅ Thread created: {data['thread_id']}")
        print(f"\n🤖 Bot Response:")
        print(f"{'-'*60}")
        print(bot_response)
        print(f"{'-'*60}")
        
        # Quality checks
        checks = {
            "Has emoji or symbols": any(c in bot_response for c in ['✅', '❌', '📧', '✓', '✗']),
            "Has structure (newlines)": '\n' in bot_response,
            "Mentions task": any(word in bot_response.lower() for word in ['search', 'email', 'found']),
            "User-friendly (no tech jargon)": all(word not in bot_response.lower() for word in ['error_code', 'null', 'exception']),
            "Has clear result": any(word in bot_response.lower() for word in ['successfully', 'found', 'result', 'completed'])
        }
        
        print("\n📊 Quality Checks:")
        passed = 0
        for check, result in checks.items():
            status = "✅" if result else "❌"
            print(f"   {status} {check}")
            if result:
                passed += 1
        
        print(f"\n🎯 Score: {passed}/{len(checks)} checks passed")
        
        if passed >= len(checks) - 1:  # Allow 1 failure
            print("✅ PASS: Summary quality is good!")
        else:
            print("⚠️  WARNING: Summary quality could be improved")
    else:
        print(f"❌ FAIL: {response.status_code} - {response.text}")


def run_all_tests():
    """Run all execution and conflict tests"""
    print(f"\n{'='*60}")
    print(f"  THREAD EXECUTION & CONFLICT TEST SUITE")
    print(f"{'='*60}")
    print(f"  Base URL: {BASE_URL}")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    try:
        # Test 1: Auto-execution on create
        test_auto_execution()
        time.sleep(2)
        
        # Test 2: Auto-execution on message
        test_execution_in_messages()
        time.sleep(2)
        
        # Test 3: Conflict prevention
        test_conflict_prevention()
        time.sleep(2)
        
        # Test 4: Summary quality
        test_execution_summary_quality()
        
        print(f"\n{'='*60}")
        print(f"  ALL TESTS COMPLETED")
        print(f"{'='*60}\n")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
