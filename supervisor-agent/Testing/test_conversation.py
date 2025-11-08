"""
Test script for Conversational Agent

Run this to test the conversational interface locally.
Make sure the supervisor agent is running on port 8000.
"""

import requests
import json
from typing import Optional

BASE_URL = "http://localhost:8080"  # Changed from 8000 to avoid conflict with PHP server

def send_chat_message(message: str, conversation_id: Optional[str] = None, auto_execute: bool = False):
    """Send a message to the conversational agent"""
    response = requests.post(
        f"{BASE_URL}/chat",
        json={
            "message": message,
            "conversation_id": conversation_id,
            "auto_execute": auto_execute
        }
    )
    
    # Debug: print status and raw response
    print(f"[DEBUG] Status Code: {response.status_code}")
    print(f"[DEBUG] Response Text: {response.text[:500]}")  # First 500 chars
    
    if response.status_code == 404:
        print("\n❌ ERROR: /chat endpoint not found!")
        print("   The supervisor agent may not have the conversational endpoints loaded.")
        print("   Please ensure you're running the latest supervisor_agent.py")
        raise Exception("Endpoint not found")
    
    if not response.text:
        print("\n❌ ERROR: Empty response from server")
        raise Exception("Empty response")
    
    try:
        return response.json()
    except json.JSONDecodeError as e:
        print(f"\n❌ ERROR: Response is not valid JSON")
        print(f"   Full response: {response.text}")
        raise

def execute_conversation(conversation_id: str):
    """Execute a conversation that's ready"""
    response = requests.post(f"{BASE_URL}/chat/{conversation_id}/execute")
    return response.json()

def get_conversation(conversation_id: str):
    """Get conversation details"""
    response = requests.get(f"{BASE_URL}/chat/{conversation_id}")
    return response.json()

def print_response(data: dict):
    """Pretty print the response"""
    print("="*70)
    print("🤖 BOT RESPONSE:")
    print("="*70)
    print(data.get("response", ""))
    print()
    print(f"Conversation ID: {data.get('conversation_id', 'N/A')}")
    print(f"Intent: {data.get('intent', 'N/A')}")
    print(f"Ready to Execute: {data.get('ready_for_execution', False)}")
    
    if data.get("extracted_info"):
        print("\nExtracted Information:")
        for key, value in data["extracted_info"].items():
            print(f"  - {key}: {value}")
    
    if data.get("execution_summary"):
        print(f"\n📋 Execution Summary: {data['execution_summary']}")
    
    print("="*70)
    print()

def test_scenario_incomplete_email():
    """Test Scenario 1: User provides incomplete information"""
    print("\n" + "🎬 "*20)
    print("SCENARIO 1: Incomplete Email Request - Multi-Turn Clarification")
    print("🎬 "*20 + "\n")
    
    # Turn 1: Vague request
    print("👤 USER: Send an email about the meeting tomorrow\n")
    result = send_chat_message("Send an email about the meeting tomorrow")
    print_response(result)
    conv_id = result["conversation_id"]
    
    # Turn 2: Provide recipient
    print("👤 USER: Send it to john@example.com\n")
    result = send_chat_message("Send it to john@example.com", conversation_id=conv_id)
    print_response(result)
    
    # Turn 3: Provide subject
    print("👤 USER: Subject is 'Q4 Planning Meeting'\n")
    result = send_chat_message("Subject is 'Q4 Planning Meeting'", conversation_id=conv_id)
    print_response(result)
    
    # Turn 4: Provide body
    print("👤 USER: Tell him the meeting is moved to 3pm\n")
    result = send_chat_message("Tell him the meeting is moved to 3pm", conversation_id=conv_id)
    print_response(result)
    
    if result["ready_for_execution"]:
        print("✅ Conversation is ready! Would execute here in production.")
        # Uncomment to actually execute:
        # print("\n🚀 EXECUTING...\n")
        # execute_result = execute_conversation(conv_id)
        # print(json.dumps(execute_result, indent=2))
    
    return conv_id

def test_scenario_infeasible():
    """Test Scenario 2: User asks for something we can't do"""
    print("\n" + "🎬 "*20)
    print("SCENARIO 2: Infeasible Task - Book Flight")
    print("🎬 "*20 + "\n")
    
    print("👤 USER: Book a flight to Paris for next week\n")
    result = send_chat_message("Book a flight to Paris for next week")
    print_response(result)
    
    return result["conversation_id"]

def test_scenario_too_complex():
    """Test Scenario 3: Task is too complex"""
    print("\n" + "🎬 "*20)
    print("SCENARIO 3: Complex Task - Multiple Operations")
    print("🎬 "*20 + "\n")
    
    print("👤 USER: Find all emails from last month, summarize them, and send to my team\n")
    result = send_chat_message(
        "Find all emails from last month, summarize them, and send to my team"
    )
    print_response(result)
    
    return result["conversation_id"]

def test_scenario_auto_execute():
    """Test Scenario 4: Complete request with auto-execute"""
    print("\n" + "🎬 "*20)
    print("SCENARIO 4: Complete Request - Auto Execute")
    print("🎬 "*20 + "\n")
    
    print("👤 USER: Search for emails from sarah@company.com about project alpha\n")
    result = send_chat_message(
        "Search for emails from sarah@company.com about project alpha",
        auto_execute=False  # Set to True to actually execute
    )
    print_response(result)
    
    return result["conversation_id"]

def test_scenario_small_talk():
    """Test Scenario 5: Small talk"""
    print("\n" + "🎬 "*20)
    print("SCENARIO 5: Small Talk")
    print("🎬 "*20 + "\n")
    
    print("👤 USER: Hello, how are you?\n")
    result = send_chat_message("Hello, how are you?")
    print_response(result)
    
    return result["conversation_id"]

def main():
    """Run all test scenarios"""
    print("\n" + "🧪"*35)
    print("CONVERSATIONAL AGENT TEST SUITE")
    print("🧪"*35)
    print("\nMake sure supervisor agent is running on http://localhost:8000")
    print("\nPress Enter to start tests...")
    input()
    
    try:
        # Run all scenarios
        test_scenario_incomplete_email()
        test_scenario_infeasible()
        test_scenario_too_complex()
        test_scenario_auto_execute()
        test_scenario_small_talk()
        
        print("\n" + "✅ "*35)
        print("ALL TESTS COMPLETED")
        print("✅ "*35)
        
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to supervisor agent")
        print("   Make sure it's running on http://localhost:8000")
        print("   Run: python supervisor_agent.py")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
